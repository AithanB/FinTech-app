"""Pure submission validation, evidence matching, and common reward scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pydantic import ValidationError

from .schemas import Finding, Submission, Truth, TruthIssue


@dataclass(frozen=True)
class Match:
    issue_id: str
    submission_index: int


@dataclass(frozen=True)
class ScoreResult:
    score: float
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    matches: tuple[Match, ...]
    validation_error: str | None = None


def validate_submission(payload: object, expected_episode_id: str) -> Submission:
    """Validate the complete wire envelope, including its episode ID.

    Evidence/object IDs are deliberately checked during matching: a well-formed
    claim that guesses an ID is an unmatched prediction, not a malformed envelope.
    """
    try:
        submission = payload if isinstance(payload, Submission) else Submission.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("INVALID_SUBMISSION") from exc
    if submission.episode_id != expected_episode_id:
        raise ValueError("WRONG_EPISODE_ID")
    return submission


def _compatible(
    issue: TruthIssue,
    finding: Finding,
    available_evidence_ids: frozenset[str],
) -> bool:
    if finding.type != issue.type:
        return False
    if set(finding.affected_ids) != set(issue.affected_ids):
        return False
    if finding.claimed_amount_minor != issue.expected_amount_minor:
        return False
    if finding.currency != issue.currency:
        return False

    supplied = set(finding.evidence_ids)
    if not supplied.issubset(available_evidence_ids):
        return False
    return any(set(proof).issubset(supplied) for proof in issue.evidence_sets)


def _maximum_size(edges: list[tuple[int, int]], blocked_predictions: set[int], blocked_truths: set[int]) -> int:
    """Return maximum matching size for the remaining bipartite graph."""
    truth_to_prediction: dict[int, int] = {}
    adjacency: dict[int, list[int]] = {}
    for prediction, truth in edges:
        if prediction not in blocked_predictions and truth not in blocked_truths:
            adjacency.setdefault(prediction, []).append(truth)

    def augment(prediction: int, visited: set[int]) -> bool:
        for truth in adjacency.get(prediction, ()):
            if truth in visited:
                continue
            visited.add(truth)
            previous = truth_to_prediction.get(truth)
            if previous is None or augment(previous, visited):
                truth_to_prediction[truth] = prediction
                return True
        return False

    size = 0
    for prediction in sorted(adjacency):
        if augment(prediction, set()):
            size += 1
    return size


def maximum_matching(
    issues: Iterable[TruthIssue],
    findings: Iterable[Finding],
    available_evidence_ids: Iterable[str],
) -> tuple[Match, ...]:
    """Find a deterministic maximum one-to-one compatible matching.

    Among maximum matchings, choose the lexicographically smallest sorted list
    of ``(issue_id, submission_index)`` pairs. Sequential feasibility checks
    implement that tie rule without allowing greedy choices to reduce cardinality.
    """
    issue_list = list(issues)
    finding_list = list(findings)
    evidence = frozenset(available_evidence_ids)
    # Sort by the published pair, then by truth position only to make malformed
    # private truth containing repeated issue IDs deterministic as well.
    candidates: list[tuple[str, int, int]] = []
    for truth_index, issue in enumerate(issue_list):
        for prediction_index, finding in enumerate(finding_list):
            if _compatible(issue, finding, evidence):
                candidates.append((issue.issue_id, prediction_index, truth_index))
    candidates.sort()
    pair_edges = [(prediction, truth) for _, prediction, truth in candidates]
    target_size = _maximum_size(pair_edges, set(), set())
    selected: list[Match] = []
    used_predictions: set[int] = set()
    used_truths: set[int] = set()

    for position, (issue_id, prediction, truth) in enumerate(candidates):
        if len(selected) == target_size:
            break
        if prediction in used_predictions or truth in used_truths:
            continue
        next_predictions = used_predictions | {prediction}
        next_truths = used_truths | {truth}
        remaining_edges = pair_edges[position + 1 :]
        if len(selected) + 1 + _maximum_size(remaining_edges, next_predictions, next_truths) >= target_size:
            selected.append(Match(issue_id=issue_id, submission_index=prediction))
            used_predictions = next_predictions
            used_truths = next_truths

    return tuple(selected)


def common_reward(f1: float, inspection_steps: int) -> float:
    """R06 reward: clip(2*F1 - 1 - 0.002*inspection_steps, -1, 1)."""
    if isinstance(inspection_steps, bool) or not isinstance(inspection_steps, int) or inspection_steps < 0:
        raise ValueError("inspection_steps must be a nonnegative integer")
    if not 0.0 <= f1 <= 1.0:
        raise ValueError("f1 must be between 0 and 1")
    return max(-1.0, min(1.0, 2.0 * f1 - 1.0 - 0.002 * inspection_steps))


def score_submission(
    truth: Truth,
    payload: object,
    available_evidence_ids: Iterable[str],
    inspection_steps: int,
) -> ScoreResult:
    """Validate and privately grade a wire payload.

    A malformed envelope has the specified terminal score -1. Diagnostics are
    returned for the trusted runner and must stay private in closed mode.
    """
    if isinstance(inspection_steps, bool) or not isinstance(inspection_steps, int) or inspection_steps < 0:
        raise ValueError("inspection_steps must be a nonnegative integer")
    try:
        submission = validate_submission(payload, truth.episode_id)
    except ValueError as exc:
        return ScoreResult(-1.0, 0, 0, len(truth.issues), 0.0, 0.0, 0.0, (), str(exc))

    matches = maximum_matching(truth.issues, submission.findings, available_evidence_ids)
    tp = len(matches)
    fp = len(submission.findings) - tp
    fn = len(truth.issues) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    if tp + fp + fn == 0:
        f1 = 1.0
    elif tp == 0:
        f1 = 0.0
    else:
        f1 = 2.0 * tp / (2 * tp + fp + fn)
    return ScoreResult(
        common_reward(f1, inspection_steps), tp, fp, fn,
        precision, recall, f1, matches,
    )
