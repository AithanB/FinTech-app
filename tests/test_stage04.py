import json
from pathlib import Path

import pytest

from audit_env.environment import AuditEnvironment, calculate
from audit_env.runner import run_fixture_demo
from audit_env.schemas import PublicEpisode, Truth
from audit_env.serialization import load_public, read_json, save_public, write_json


FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED_B = json.loads((FIXTURES / "company-b/private/expected_submission.json").read_text())


def write_fixture_root(tmp_path: Path, ledger_count: int) -> Path:
    root = tmp_path / "fixtures"
    source_dir = FIXTURES / "company-a"
    source = load_public(source_dir / "public")
    rows = []
    if ledger_count:
        template = source.ledger[0]
        rows = [template.model_copy(update={"row_id": f"test-row-{index}"}) for index in range(ledger_count)]
    manifest = source.manifest.model_copy(update={
        "record_count": ledger_count + len(source.invoices) + len(source.payments) + len(source.fx)
    })
    episode = PublicEpisode(
        manifest=manifest, policy=source.policy, ledger=rows,
        invoices=source.invoices, payments=source.payments, fx=source.fx,
    )
    target = root / "company-a"
    save_public(target / "public", episode)
    (target / "private").mkdir(parents=True)
    for name in ("truth.json", "provenance.json", "expected_submission.json"):
        (target / "private" / name).write_bytes((source_dir / "private" / name).read_bytes())
    return root


@pytest.mark.parametrize("row_count", [0, 1, 50, 51])
def test_pagination_handles_zero_one_fifty_and_fifty_one_rows(tmp_path, row_count):
    env = AuditEnvironment(write_fixture_root(tmp_path, row_count))
    env.reset(config={"fixture": "company-a", "mode": "open"})
    first, reward, terminated, truncated, _ = env.step({
        "type": "list_records", "table": "ledger", "cursor": None, "limit": 50,
    })
    assert reward == 0 and not terminated and not truncated
    rows = first["result"]["rows"]
    assert len(rows) == min(50, row_count)
    if row_count <= 50:
        assert first["result"]["next_cursor"] is None
    else:
        assert first["result"]["next_cursor"] == "ledger:50"
        second, *_ = env.step({
            "type": "list_records", "table": "ledger", "cursor": "ledger:50", "limit": 50,
        })
        assert [item["id"] for item in second["result"]["rows"]] == ["test-row-50"]
        assert second["result"]["next_cursor"] is None


def test_invalid_cursor_limit_and_ids_are_bounded_action_results():
    env = AuditEnvironment()
    env.reset(config={"fixture": "company-b", "mode": "open"})
    cases = [
        ({"type": "list_records", "table": "ledger", "cursor": "payments:0", "limit": 1}, "INVALID_CURSOR"),
        ({"type": "list_records", "table": "ledger", "cursor": "ledger:999", "limit": 1}, "INVALID_CURSOR"),
        ({"type": "list_records", "table": "ledger", "cursor": None, "limit": 0}, "INVALID_ACTION"),
        ({"type": "list_records", "table": "ledger", "cursor": None, "limit": 51}, "INVALID_ACTION"),
        ({"type": "get_record", "table": "ledger", "id": "guessed-row"}, "UNKNOWN_ID"),
        ({"type": "get_document", "doc_id": "guessed-doc"}, "UNKNOWN_ID"),
    ]
    for action, expected_error in cases:
        observation, reward, terminated, truncated, _ = env.step(action)
        assert observation["error"] == expected_error
        assert reward == 0 and not terminated and not truncated
        assert "Traceback" not in json.dumps(observation)
    assert env.action_count == len(cases)


def test_calculator_is_decimal_bounded_and_reports_controlled_errors():
    assert calculate("(70000 - 50000) * 100") == "2000000"
    assert calculate("1 / 3") == "0.3333333333333333333333333333333333"
    for expression in (
        "1 / 0", "__import__('os')", "(1 + 2", "1 +", "1e1001", "1" * 257,
        "(" * 17 + "1" + ")" * 17,
    ):
        with pytest.raises(ValueError):
            calculate(expression)

    env = AuditEnvironment()
    env.reset()
    observation, *_ = env.step({"type": "calculator", "expression": "1 / 0"})
    assert observation["error"] == "CALCULATOR_ERROR"


def test_payment_document_exposes_public_settlement_and_is_snapshot_safe():
    env = AuditEnvironment()
    initial, _ = env.reset(config={"fixture": "company-b", "mode": "open"})
    original_manifest = json.loads(json.dumps(initial["manifest"]))
    first, *_ = env.step({"type": "get_document", "doc_id": "doc-492"})
    assert first["result"]["payment"]["payment_id"] == "pay-627"
    assert first["result"]["settlement"]["applied_minor"] == 5000000
    assert first["result"]["settlement"]["unapplied_minor"] == 2000000
    first["result"]["settlement"]["allocations"].clear()

    second, *_ = env.step({"type": "get_document", "doc_id": "doc-492"})
    assert len(second["result"]["settlement"]["allocations"]) == 1
    assert initial["manifest"] == original_manifest
    initial["manifest"]["episode_id"] = "mutated by caller"
    third, *_ = env.step({"type": "list_records", "table": "ledger", "cursor": None, "limit": 1})
    assert initial["manifest"]["episode_id"] == "mutated by caller"
    assert third["remaining_steps"] == 97


def test_fixture_demo_runs_and_records_the_observations(tmp_path):
    trace = tmp_path / "provisional.jsonl"
    result = run_fixture_demo("company-b", trace)
    assert len(result["trajectory"]) == 5
    assert result["trajectory"][1]["observation"]["result"]["id"] == "pay-627"
    assert result["trajectory"][2]["observation"]["result"]["settlement"]["unapplied_minor"] == 2000000
    assert result["trajectory"][3]["observation"]["result"] == "2000000"
    assert result["trajectory"][4]["terminated"] is True
    assert all(row["reward"] == 0 for row in result["trajectory"])
    assert result["private_score"] == pytest.approx(1 - 0.002 * 4)
    assert result["private_result"].findings[0].claimed_amount_minor == 2000000
    trace_rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert trace_rows[0]["metadata"]["initial_observation"]["manifest"]["episode_id"] == "ep-431"
    assert len(trace_rows) == 6


def test_submit_on_action_one_hundred_and_inspection_truncation():
    env = AuditEnvironment()
    env.reset(config={"fixture": "company-b", "mode": "open"})
    for _ in range(99):
        observation, _, terminated, truncated, _ = env.step({"type": "get_record", "table": "ledger", "id": "missing"})
        assert observation["error"] == "UNKNOWN_ID"
        assert not terminated and not truncated
    observation, reward, terminated, truncated, _ = env.step({"type": "submit", "findings": EXPECTED_B})
    assert observation["result"]["accepted"] is True
    assert env.action_count == 100 and terminated and not truncated
    assert reward == pytest.approx(1 - 0.002 * 99)

    env.reset(config={"fixture": "company-b", "mode": "closed"})
    for _ in range(100):
        observation, reward, terminated, truncated, _ = env.step({"type": "get_record", "table": "ledger", "id": "missing"})
    assert observation["error"] == "UNKNOWN_ID"
    assert env.action_count == 100 and not terminated and truncated
    assert reward == 0.0 and env._last_score == -1.0


def test_malformed_submit_is_terminal_minus_one_and_closed_mode_masks_reward():
    env = AuditEnvironment()
    env.reset(config={"fixture": "company-b", "mode": "closed"})
    observation, reward, terminated, truncated, info = env.step({
        "type": "submit", "findings": {"episode_id": "wrong", "findings": []},
    })
    assert observation["error"] == "INVALID_SUBMISSION"
    assert reward == 0.0 and terminated and not truncated and info == {}
    assert env._last_score == -1.0
    assert env._last_validation_error == "WRONG_EPISODE_ID"
    used_steps = env.action_count
    second, second_reward, second_terminated, second_truncated, _ = env.step({"type": "submit", "findings": EXPECTED_B})
    assert second["error"] == "EPISODE_CLOSED"
    assert second_reward == 0.0 and second_terminated and not second_truncated
    assert env.action_count == used_steps and env._last_score == -1.0

    env.reset(config={"fixture": "company-a", "mode": "open"})
    _, reward, terminated, truncated, _ = env.step({
        "type": "submit", "findings": {"episode_id": "wrong", "findings": []},
    })
    assert reward == -1.0 and terminated and not truncated
    assert env._last_score == -1.0

    env.reset(config={"fixture": "company-b", "mode": "open"})
    observation, reward, terminated, truncated, _ = env.step({
        "type": "submit", "findings": EXPECTED_B, "unexpected": True,
    })
    assert observation["error"] == "INVALID_SUBMISSION"
    assert reward == -1.0 and terminated and not truncated


def test_reset_after_submit_clears_terminal_state_and_counter():
    env = AuditEnvironment()
    env.reset(config={"fixture": "company-b", "mode": "open"})
    env.step({"type": "submit", "findings": EXPECTED_B})
    assert env._last_score == 1.0
    observation, info = env.reset(seed=234, config={"fixture": "company-a", "mode": "closed"})
    assert observation["manifest"]["episode_id"] == "ep-431"
    assert observation["remaining_steps"] == 100 and info == {}
    assert env.action_count == 0 and env._last_score is None
    _, reward, terminated, truncated, _ = env.step({
        "type": "list_records", "table": "payments", "cursor": None, "limit": 1,
    })
    assert reward == 0 and not terminated and not truncated
