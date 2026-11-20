import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from audit_env.schemas import Finding, Submission, Truth, TruthIssue
from audit_env.scoring import common_reward, maximum_matching, score_submission, validate_submission
from audit_env.serialization import read_json


FIXTURES = Path(__file__).parent / "fixtures"
TRUTH = read_json(FIXTURES / "company-b/private/truth.json", Truth)
SUBMISSION = json.loads((FIXTURES / "company-b/private/expected_submission.json").read_text())
EVIDENCE = {"doc-492", "settlement:pay-627", "row-957", "row-268", "doc-813"}


def score(payload=SUBMISSION, steps=0, truth=TRUTH, evidence=EVIDENCE):
    return score_submission(truth, payload, evidence, steps)


def test_fixture_answer_and_duplicate_prediction():
    result = score()
    assert (result.tp, result.fp, result.fn) == (1, 0, 0)
    assert result.f1 == 1.0

    duplicate = json.loads(json.dumps(SUBMISSION))
    duplicate["findings"].append(duplicate["findings"][0].copy())
    result = score(duplicate, steps=20)
    assert (result.tp, result.fp, result.fn) == (1, 1, 0)
    assert result.precision == 0.5
    assert result.recall == 1.0
    assert result.f1 == pytest.approx(2 / 3)
    assert result.score == pytest.approx(1 / 3 - 0.04)
    assert result.matches[0].submission_index == 0


def test_exact_fields_and_evidence_are_required_but_prose_is_not_scored():
    wrong_currency = json.loads(json.dumps(SUBMISSION))
    wrong_currency["findings"][0]["currency"] = "USD"
    result = score(wrong_currency)
    assert (result.tp, result.fp, result.fn) == (0, 1, 1)

    wrong_amount = json.loads(json.dumps(SUBMISSION))
    wrong_amount["findings"][0]["claimed_amount_minor"] += 1
    assert (score(wrong_amount).tp, score(wrong_amount).fp, score(wrong_amount).fn) == (0, 1, 1)

    unrelated = json.loads(json.dumps(SUBMISSION))
    unrelated["findings"][0]["evidence_ids"] = ["doc-813"]
    assert (score(unrelated).tp, score(unrelated).fp, score(unrelated).fn) == (0, 1, 1)

    partial = json.loads(json.dumps(SUBMISSION))
    partial["findings"][0]["evidence_ids"] = ["doc-492"]
    assert (score(partial).tp, score(partial).fp, score(partial).fn) == (0, 1, 1)

    guessed = json.loads(json.dumps(SUBMISSION))
    guessed["findings"][0]["evidence_ids"].append("invented-evidence")
    assert (score(guessed).tp, score(guessed).fp, score(guessed).fn) == (0, 1, 1)

    guessed_target = json.loads(json.dumps(SUBMISSION))
    guessed_target["findings"][0]["affected_ids"][0] = "invented-object"
    assert (score(guessed_target).tp, score(guessed_target).fp, score(guessed_target).fn) == (0, 1, 1)

    prose = json.loads(json.dumps(SUBMISSION))
    prose["findings"][0]["explanation"] = "Any explanation within the published limit."
    assert score(prose).score == score(SUBMISSION).score


def test_alternative_complete_proof_and_unordered_normalization():
    issue = TRUTH.issues[0].model_copy(update={
        "evidence_sets": [["doc-492", "settlement:pay-627"], ["row-957", "row-268"]]
    })
    truth = TRUTH.model_copy(update={"issues": [issue]})
    alternate = json.loads(json.dumps(SUBMISSION))
    alternate["findings"][0]["evidence_ids"] = ["row-268", "row-957"]
    alternate["findings"][0]["affected_ids"].reverse()
    assert score(alternate, truth=truth).tp == 1


def test_maximum_matching_avoids_greedy_loss():
    # Both predictions fit issue A, but only the broad prediction fits B.
    # Taking A's first available edge would leave B unmatched.
    common = dict(type="payment_allocation", affected_ids=["pay", "inv"],
                  expected_amount_minor=10, currency="KZT")
    issue_a = TruthIssue(issue_id="a", evidence_sets=[["ev-a"]], **common)
    issue_b = TruthIssue(issue_id="b", evidence_sets=[["ev-b"]], **common)
    broad = Finding(type="payment_allocation", affected_ids=["inv", "pay"],
                    claimed_amount_minor=10, currency="KZT", evidence_ids=["ev-a", "ev-b"], explanation="")
    only_a = broad.model_copy(update={"evidence_ids": ["ev-a"]})
    matches = maximum_matching([issue_a, issue_b], [broad, only_a], {"ev-a", "ev-b"})
    assert [(item.issue_id, item.submission_index) for item in matches] == [("a", 1), ("b", 0)]


def test_ambiguous_edges_use_published_lexicographic_tie_break():
    common = dict(type="payment_allocation", affected_ids=["pay", "inv"],
                  expected_amount_minor=10, currency="KZT", evidence_sets=[["ev"]])
    issues = [TruthIssue(issue_id="z", **common), TruthIssue(issue_id="a", **common)]
    finding = Finding(type="payment_allocation", affected_ids=["pay", "inv"],
                      claimed_amount_minor=10, currency="KZT", evidence_ids=["ev"], explanation="")
    matches = maximum_matching(issues, [finding, finding], {"ev"})
    assert [(item.issue_id, item.submission_index) for item in matches] == [("a", 0), ("z", 1)]


def test_reward_cost_clipping_and_empty_cases():
    assert common_reward(1.0, 20) == pytest.approx(0.96)
    assert common_reward(1.0, 50) == pytest.approx(0.90)
    assert common_reward(1.0, 1000) == -1.0
    assert common_reward(0.0, 0) == -1.0
    with pytest.raises(ValueError):
        common_reward(1.0, True)

    clean_truth = Truth(episode_id=TRUTH.episode_id, issues=[])
    silence = {"episode_id": TRUTH.episode_id, "findings": []}
    assert score(silence, truth=clean_truth).f1 == 1.0
    false_claim = json.loads(json.dumps(SUBMISSION))
    false_claim["episode_id"] = TRUTH.episode_id
    empty_result = score(false_claim, truth=clean_truth)
    assert (empty_result.tp, empty_result.fp, empty_result.fn, empty_result.f1) == (0, 1, 0, 0.0)


def test_submission_limits_and_malformed_penalty():
    finding = SUBMISSION["findings"][0]
    valid_30 = {"episode_id": TRUTH.episode_id, "findings": [finding] * 30}
    assert validate_submission(valid_30, TRUTH.episode_id)
    too_many = {"episode_id": TRUTH.episode_id, "findings": [finding] * 31}
    assert score(too_many).score == -1.0
    with pytest.raises(ValueError, match="INVALID_SUBMISSION"):
        validate_submission(too_many, TRUTH.episode_id)

    ten_evidence = dict(finding, evidence_ids=[f"evidence-{n}" for n in range(10)])
    valid_ten = {"episode_id": TRUTH.episode_id, "findings": [ten_evidence]}
    assert validate_submission(valid_ten, TRUTH.episode_id).findings[0].evidence_ids
    eleven_evidence = dict(finding, evidence_ids=[f"evidence-{n}" for n in range(11)])
    assert score({"episode_id": TRUTH.episode_id, "findings": [eleven_evidence]}).score == -1.0

    explanation_1000 = dict(finding, explanation="x" * 1000)
    assert validate_submission({"episode_id": TRUTH.episode_id, "findings": [explanation_1000]}, TRUTH.episode_id)
    explanation_1001 = dict(finding, explanation="x" * 1001)
    assert score({"episode_id": TRUTH.episode_id, "findings": [explanation_1001]}).score == -1.0

    assert score({"episode_id": "wrong", "findings": []}).score == -1.0
    assert score({"episode_id": TRUTH.episode_id, "findings": [], "extra": 1}).score == -1.0
    bad_boolean_amount = json.loads(json.dumps(SUBMISSION))
    bad_boolean_amount["findings"][0]["claimed_amount_minor"] = True
    assert score(bad_boolean_amount).score == -1.0


def test_public_evidence_id_collection_is_explicit():
    assert score(SUBMISSION, evidence=EVIDENCE - {"settlement:pay-627"}).tp == 0
