"""Fixture-backed audit episode with bounded public investigation tools."""

from __future__ import annotations

import copy
import re
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .schemas import ACTION_ADAPTER, PublicEpisode, Submission, Truth
from .scoring import score_submission
from .serialization import load_public, read_json
from .views import settlement_view


FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
MAX_STEPS = 100


class ExpressionError(ValueError):
    """A safe, bounded calculator input or arithmetic error."""


class _DecimalParser:
    _number = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")

    def __init__(self, expression: str):
        if not isinstance(expression, str) or not expression or len(expression) > 256:
            raise ExpressionError("expression length is invalid")
        self.expression = expression
        self.tokens: list[str] = []
        position = 0
        while position < len(expression):
            if expression[position].isspace():
                position += 1
                continue
            match = self._number.match(expression, position)
            if match:
                self.tokens.append(match.group())
                position = match.end()
                continue
            char = expression[position]
            if char in "+-*/()":
                self.tokens.append(char)
                position += 1
                continue
            raise ExpressionError("unsupported expression token")
        self.index = 0
        self.depth = 0

    def parse(self) -> Decimal:
        with localcontext() as context:
            context.prec = 34
            value = self._sum()
            if self.index != len(self.tokens):
                raise ExpressionError("unexpected expression token")
            if not value.is_finite():
                raise ExpressionError("nonfinite calculator result")
            if abs(value.as_tuple().exponent) > 1000 or (value and abs(value.adjusted()) > 1000):
                raise ExpressionError("calculator result exceeds bounds")
            return +value

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise ExpressionError("incomplete expression")
        self.index += 1
        return token

    def _sum(self) -> Decimal:
        value = self._product()
        while self._peek() in ("+", "-"):
            operator = self._take()
            right = self._product()
            value = value + right if operator == "+" else value - right
        return value

    def _product(self) -> Decimal:
        value = self._unary()
        while self._peek() in ("*", "/"):
            operator = self._take()
            right = self._unary()
            if operator == "/" and right == 0:
                raise ExpressionError("division by zero")
            value = value * right if operator == "*" else value / right
        return value

    def _unary(self) -> Decimal:
        if self._peek() in ("+", "-"):
            operator = self._take()
            value = self._unary()
            return value if operator == "+" else -value
        if self._peek() == "(":
            self._take()
            self.depth += 1
            if self.depth > 16:
                raise ExpressionError("parenthesis nesting exceeds limit")
            value = self._sum()
            if self._take() != ")":
                raise ExpressionError("unclosed parenthesis")
            self.depth -= 1
            return value
        token = self._take()
        if token in "+-*/)":
            raise ExpressionError("expected decimal number")
        try:
            value = Decimal(token)
        except DecimalException as exc:
            raise ExpressionError("invalid decimal number") from exc
        if not value.is_finite():
            raise ExpressionError("nonfinite decimal number")
        if abs(value.as_tuple().exponent) > 1000 or (value and abs(value.adjusted()) > 1000):
            raise ExpressionError("decimal literal exceeds bounds")
        return value


def calculate(expression: str) -> str:
    """Evaluate only bounded decimal arithmetic and return a decimal string."""
    try:
        value = _DecimalParser(expression).parse()
    except (DecimalException, RecursionError) as exc:
        raise ExpressionError("calculator arithmetic error") from exc
    return format(value, "f")


def _lookup_id(table: str, record: Any) -> str:
    if table == "ledger":
        return record.row_id
    if table == "invoices":
        return record.invoice_id
    if table == "payments":
        return record.payment_id
    return record.evidence_id


class AuditEnvironment:
    """One in-process episode. Process isolation is intentionally Stage 05."""

    def __init__(self, fixture_root: Path = FIXTURE_ROOT):
        self.fixture_root = Path(fixture_root)
        self._episode: PublicEpisode | None = None
        self._truth: Truth | None = None
        self._steps = 0
        self._closed = True
        self._episode_done = False
        self._last_score: float | None = None
        self._last_scoring_result = None
        self._last_validation_error: str | None = None
        self._last_submission: Submission | None = None

    def reset(self, seed: int | None = None, config: dict[str, Any] | None = None):
        # Seed ownership belongs to the trusted runner; fixtures are deterministic.
        del seed
        config = {} if config is None else config
        if not isinstance(config, dict) or set(config) - {"fixture", "mode"}:
            raise ValueError("invalid reset configuration")
        fixture = config.get("fixture", "company-b")
        mode = config.get("mode", "closed")
        if fixture not in ("company-a", "company-b") or mode not in ("open", "closed"):
            raise ValueError("invalid reset configuration")
        directory = self.fixture_root / fixture
        episode = load_public(directory / "public")
        truth = read_json(directory / "private" / "truth.json", Truth)
        if truth.episode_id != episode.manifest.episode_id:
            raise ValueError("fixture episode ID mismatch")
        self._episode = episode
        self._truth = truth
        self._steps = 0
        self._closed = mode == "closed"
        self._episode_done = False
        self._last_score = None
        self._last_scoring_result = None
        self._last_validation_error = None
        self._last_submission = None
        observation = {
            "task": "Inspect the public company records and submit supported audit findings.",
            "manifest": episode.manifest.model_dump(mode="json"),
            "policy": episode.policy.model_dump(mode="json"),
            "remaining_steps": MAX_STEPS,
        }
        return copy.deepcopy(observation), {}

    @property
    def action_count(self) -> int:
        return self._steps

    def step(self, action: object):
        if self._episode is None or self._truth is None:
            raise RuntimeError("reset must be called before step")
        if self._episode_done:
            # Calls after completion are rejected without mutating budget or score.
            return self._reply(error="EPISODE_CLOSED"), 0.0, True, False, {}

        if not isinstance(action, dict) or not isinstance(action.get("type"), str):
            self._steps += 1
            return self._finish_inspection(self._reply(error="INVALID_ACTION"))

        self._steps += 1
        if action.get("type") == "submit":
            submission_payload = action.get("findings") if set(action) == {"type", "findings"} else {"invalid_envelope": True}
            result = score_submission(
                self._truth,
                submission_payload,
                self._evidence_ids(),
                self._steps - 1,
            )
            self._last_score = result.score
            self._last_scoring_result = result
            self._last_validation_error = result.validation_error
            if result.validation_error is None:
                self._last_submission = submission_payload if isinstance(submission_payload, Submission) else Submission.model_validate(submission_payload)
                observation = self._reply(result={"accepted": True})
            else:
                observation = self._reply(error="INVALID_SUBMISSION")
            self._episode_done = True
            return observation, self._transport_reward(result.score), True, False, {}

        try:
            parsed = ACTION_ADAPTER.validate_python(action)
        except ValidationError:
            return self._finish_inspection(self._reply(error="INVALID_ACTION"))
        if parsed.type == "list_records":
            response = self._list_records(parsed.table, parsed.cursor, parsed.limit)
        elif parsed.type == "get_record":
            response = self._get_record(parsed.table, parsed.id)
        elif parsed.type == "get_document":
            response = self._get_document(parsed.doc_id)
        elif parsed.type == "calculator":
            try:
                response = self._reply(result=calculate(parsed.expression))
            except ExpressionError:
                response = self._reply(error="CALCULATOR_ERROR")
        else:  # Submit is handled before strict action parsing to penalize malformed submits.
            response = self._reply(error="INVALID_ACTION")
        return self._finish_inspection(response)

    def _finish_inspection(self, observation: dict[str, Any]):
        if self._steps >= MAX_STEPS:
            self._episode_done = True
            self._last_submission = Submission(episode_id=self._truth.episode_id, findings=[])
            result = score_submission(self._truth, self._last_submission, self._evidence_ids(), self._steps)
            self._last_score = result.score
            self._last_scoring_result = result
            return observation, self._transport_reward(result.score), False, True, {}
        return observation, 0.0, False, False, {}

    def _transport_reward(self, score: float) -> float:
        # Closed evaluation keeps true reward and diagnostics in the trusted runner.
        return 0.0 if self._closed else score

    def _reply(self, *, result: Any | None = None, error: str | None = None) -> dict[str, Any]:
        reply: dict[str, Any] = {"remaining_steps": MAX_STEPS - self._steps}
        if error is not None:
            reply["error"] = error
        elif result is not None:
            reply["result"] = result
        return copy.deepcopy(reply)

    def _table(self, table: str) -> list[Any]:
        return getattr(self._episode, table)

    def _list_records(self, table: str, cursor: str | None, limit: int) -> dict[str, Any]:
        rows = self._table(table)
        start = 0
        if cursor is not None:
            match = re.fullmatch(re.escape(table) + r":(0|[1-9][0-9]*)", cursor)
            if match is None:
                return self._reply(error="INVALID_CURSOR")
            start = int(match.group(1))
            if start > len(rows):
                return self._reply(error="INVALID_CURSOR")
        selected = rows[start : start + limit]
        next_index = start + len(selected)
        next_cursor = f"{table}:{next_index}" if next_index < len(rows) else None
        result = {
            "rows": [
                {"id": _lookup_id(table, row), "record": row.model_dump(mode="json")}
                for row in selected
            ],
            "next_cursor": next_cursor,
        }
        return self._reply(result=result)

    def _get_record(self, table: str, record_id: str) -> dict[str, Any]:
        for row in self._table(table):
            if _lookup_id(table, row) == record_id:
                return self._reply(result={"id": record_id, "record": row.model_dump(mode="json")})
        return self._reply(error="UNKNOWN_ID")

    def _get_document(self, doc_id: str) -> dict[str, Any]:
        for invoice in self._episode.invoices:
            if invoice.doc_id == doc_id:
                return self._reply(result=invoice.model_dump(mode="json"))
        for payment in self._episode.payments:
            if payment.doc_id == doc_id:
                return self._reply(result={
                    "payment": payment.model_dump(mode="json"),
                    "settlement": settlement_view(payment, self._episode.ledger).model_dump(mode="json"),
                })
        return self._reply(error="UNKNOWN_ID")

    def _evidence_ids(self) -> set[str]:
        evidence = {row.row_id for row in self._episode.ledger}
        evidence.update(item.doc_id for item in self._episode.invoices + self._episode.payments)
        evidence.update(row.evidence_id for row in self._episode.fx)
        evidence.update(f"settlement:{payment.payment_id}" for payment in self._episode.payments)
        return evidence
