"""Trusted single-process fixture runner for the Stage 04 demonstration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .environment import AuditEnvironment, FIXTURE_ROOT
from .schemas import Submission, Truth
from .serialization import read_json


class FixturePolicy:
    """Small scripted policy that inspects one public payment and submits."""

    def actions(self, episode_id: str, answer: Submission) -> list[dict[str, Any]]:
        # The expected answer is supplied by the trusted demo runner. Stage 05
        # replaces this in-process arrangement with a restricted agent process.
        document_id = "doc-492"
        return [
            {"type": "list_records", "table": "payments", "cursor": None, "limit": 50},
            {"type": "get_record", "table": "payments", "id": "pay-627"},
            {"type": "get_document", "doc_id": document_id},
            {"type": "calculator", "expression": "(70000 - 50000) * 100"},
            {"type": "submit", "findings": answer.model_dump(mode="json")},
        ]


def run_fixture_demo(
    fixture: str = "company-b",
    trace_path: Path | None = None,
    fixture_root: Path = FIXTURE_ROOT,
) -> dict[str, Any]:
    """Run a fixture from reset to submit; return public trace and private score."""
    fixture_directory = Path(fixture_root) / fixture
    truth = read_json(fixture_directory / "private" / "truth.json", Truth)
    answer = read_json(fixture_directory / "private" / "expected_submission.json", Submission)
    env = AuditEnvironment(fixture_root)
    initial_observation, _ = env.reset(config={"fixture": fixture, "mode": "closed"})
    policy = FixturePolicy()
    records: list[dict[str, Any]] = []
    for index, action in enumerate(policy.actions(truth.episode_id, answer), start=1):
        observation, reward, terminated, truncated, _ = env.step(action)
        records.append({
            "episode_id": truth.episode_id,
            "step": index,
            "action": action,
            "observation": observation,
            "reward": reward,
            "terminated": terminated,
            "truncated": truncated,
        })
        if terminated or truncated:
            break
    if trace_path is not None:
        trace_path = Path(trace_path)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps({"metadata": {"initial_observation": initial_observation}}, ensure_ascii=False) + "\n")
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {
        "initial_observation": initial_observation,
        "trajectory": records,
        "private_score": env._last_score,
        "private_result": env._last_submission,
    }
