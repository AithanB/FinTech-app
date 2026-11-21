"""Independent baseline expectations, capture fidelity and real jailed adapters."""

import json
import random

import pytest

from audit_env.baselines import (
    POLICIES, add_metrics, policy_program, run_baseline, run_local_policy, save_run,
)
from audit_env.environment import AuditEnvironment
from audit_env.isolation import run_isolated_fixture, supervise
from audit_env.schemas import Submission
from audit_env.wire import transition_message
from test_stage05 import Channel, Clock, require_linux


def config(profile):
    from pathlib import Path

    return json.loads(Path(f"configs/stage08-{profile}.json").read_text())


@pytest.mark.parametrize("fixture,issues", [("company-a", 0), ("company-b", 1)])
@pytest.mark.parametrize("name", POLICIES)
def test_four_adapters_on_identical_hand_authored_fixtures(name, fixture, issues):
    result = run_local_policy(name, fixture=fixture)
    metrics, trace = result["private_result"], result["trajectory"]
    score = metrics["score"]
    assert metrics["reason"] == "completed" and score["validation_error"] is None
    assert trace[-1]["terminated"] and not trace[-1]["truncated"]
    assert all(r["delivered"] and r["reward"] == 0 and r["info"] == {} for r in trace)
    assert metrics["total_actions"] == len(trace) == metrics["inspection_steps"] + 1
    if name in ("reconciliation", "oracle"):
        assert (score["tp"], score["fp"], score["fn"]) == (issues, 0, 0)
        assert score["f1"] == 1
        assert metrics["return"] == 1 - .002 * metrics["inspection_steps"]
        assert metrics["inspection_steps"] == (4 if name == "reconciliation" else 0)
        if issues:
            finding, = metrics["submission"]["findings"]
            assert finding["claimed_amount_minor"] == 2_000_000
            assert finding["evidence_ids"] == ["doc-492", "settlement:pay-627"]
    else:
        assert score["fp"] > 0 and metrics["return"] == -1
        if name == "mass_accusation":
            assert score["fp"] == 4
    # Re-execute captured actions against the fixture and compare full delivered
    # messages, including masked rewards; no regeneration from private answers.
    env = AuditEnvironment()
    env.reset(config={"fixture": fixture, "mode": "closed"})
    for row in trace:
        message = transition_message(row["action"], env.step(row["action"]), closed=True)
        assert message == {key: row[key] for key in message}


def test_supported_findings_beat_silence_and_clean_silence_beats_accusations():
    faulty = run_local_policy("reconciliation")
    env = AuditEnvironment()
    initial, _ = env.reset(config={"fixture": "company-b"})
    env.step({"type": "submit", "findings": {"episode_id": initial["manifest"]["episode_id"], "findings": []}})
    assert faulty["private_result"]["return"] == .992 > env._last_score == -1
    assert run_local_policy("oracle", fixture="company-a")["private_result"]["return"] == 1
    assert run_local_policy("mass_accusation", fixture="company-a")["private_result"]["return"] == -1


def test_oracle_uses_common_scorer_and_pays_for_actual_prior_inspections():
    from policies.oracle import run_policy as oracle

    env = AuditEnvironment()
    initial, _ = env.reset()
    for _ in range(2):
        env.step({"type": "calculator", "expression": "1+1"})
    oracle(initial, env.step, truth=env._truth)
    assert env.action_count == 3 and env._last_score == .996
    assert env._last_scoring_result.tp == 1


def test_valid_mass_attack_reaches_cap_and_oversize_is_separate_invalid_submission():
    values = config("large-clean")
    result = run_local_policy("mass_accusation", generator=values, seed=912)
    metrics = result["private_result"]
    submission = Submission.model_validate(metrics["submission"])
    assert len(submission.findings) == 30
    assert metrics["score"]["fp"] == 30 and metrics["score"]["validation_error"] is None
    env = AuditEnvironment()
    env.reset(seed=912, config={"generator": values})
    attack = submission.model_dump(mode="json")
    attack["findings"].append(attack["findings"][0])
    obs, reward, terminated, truncated, _ = env.step({"type": "submit", "findings": attack})
    assert obs["error"] == "INVALID_SUBMISSION" and reward == 0
    assert terminated and not truncated
    assert env._last_score == -1 and env._last_validation_error == "INVALID_SUBMISSION"


@pytest.mark.parametrize("values,family", [
    ({"duplicate_invoices": 1}, "duplicate_invoice"),
    ({"missing_allocations": 1}, "payment_allocation"),
    ({"version": "stage07-v1", "currencies": ["USD"], "wrong_fx_rates": 1}, "fx_conversion"),
    ({"version": "stage07-v1", "boundary_cases": True, "misplaced_recognitions": 1}, "period_cutoff"),
])
def test_unseen_seed_each_family_uses_public_evidence(values, family):
    # This company seed is never passed to the adapter.
    result = run_local_policy("reconciliation", generator=values, seed=92341)
    metrics = result["private_result"]
    assert (metrics["score"]["tp"], metrics["score"]["fp"], metrics["score"]["fn"]) == (1, 0, 0)
    assert metrics["submission"]["findings"][0]["type"] == family


@pytest.mark.parametrize("name", POLICIES)
@pytest.mark.parametrize("profile,issues", [("large-clean", 0), ("large-mixed", 12)])
def test_large_budget_and_actual_oracle_maximum(name, profile, issues):
    result = run_local_policy(name, generator=config(profile), seed=7091)
    metrics = result["private_result"]
    assert metrics["total_actions"] <= 100 and metrics["reason"] == "completed"
    assert metrics["score"]["validation_error"] is None
    if name in ("oracle", "reconciliation"):
        assert (metrics["score"]["tp"], metrics["score"]["fp"], metrics["score"]["fn"]) == (issues, 0, 0)
        assert metrics["return"] == 1 - .002 * metrics["inspection_steps"]
    if name == "oracle":
        assert metrics["return"] == 1 and metrics["inspection_steps"] == 0


def test_policy_rng_and_episode_memory_are_reset():
    state = random.getstate()
    a = run_local_policy("random", policy_seed=13)["trajectory"]
    run_local_policy("random", fixture="company-a", policy_seed=99)
    assert run_local_policy("random", policy_seed=13)["trajectory"] == a
    assert random.getstate() == state
    assert run_local_policy("random", policy_seed=14)["trajectory"] != a
    run_local_policy("reconciliation", fixture="company-b")
    assert run_local_policy("reconciliation", fixture="company-a")["private_result"]["submission"]["findings"] == []
    with pytest.raises(ValueError, match="oracle"):
        policy_program("oracle")
    program = policy_program("random", 13).decode()
    assert "truth.json" not in program and "from audit_env" not in program


def test_saved_snapshots_are_delivered_messages_and_metrics_are_separate(tmp_path):
    result = run_local_policy("reconciliation")
    save_run(result, tmp_path)
    lines = [json.loads(line) for line in (tmp_path / "trajectories.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines[0]["metadata"]["initial_observation"] == result["initial_observation"]
    assert lines[1:] == result["trajectory"]
    serialized = json.dumps(lines)
    for forbidden in ("matches", "issue-735", "precision", "truth", "validation_error"):
        assert forbidden not in serialized
    private = json.loads((tmp_path / "private-result.json").read_text())
    assert private["return"] == .992 and private["inspection_steps"] == 4


def test_policy_mutation_cannot_rewrite_a_delivered_snapshot(monkeypatch):
    def mutating_policy(name, initial, act, **kwargs):
        from policies.baselines import EpisodeEnded

        result = act({"type": "list_records", "table": "invoices", "cursor": None, "limit": 50})
        result["rows"][0]["record"]["total_minor"] = 1
        result.clear()
        try:
            act({"type": "submit", "findings": {"episode_id": initial["manifest"]["episode_id"], "findings": []}})
        except EpisodeEnded:
            pass

    monkeypatch.setattr("audit_env.baselines.run_policy", mutating_policy)
    result = run_local_policy("random")
    assert result["trajectory"][0]["observation"]["result"]["rows"][0]["record"]["total_minor"] == 10_000_000


def test_timeout_log_is_distinct_from_submit_without_consuming_an_action(tmp_path):
    env = AuditEnvironment()
    initial, _ = env.reset()
    clock = Clock()
    channel = Channel(clock, [(0, {"type": "calculator", "expression": "1+2"}), (2, None)])
    trace, reason = supervise(env, initial, channel, seconds=1, clock=clock)
    assert reason == "timeout" and env.action_count == 1
    assert trace[0]["delivered"] and trace[0]["observation"]["result"] == "3"
    assert trace[-1]["action"] is None and trace[-1]["step"] == 2
    assert trace[-1]["truncated"] and not trace[-1]["terminated"] and not trace[-1]["delivered"]
    assert trace[-1]["observation"] == {"error": "TIME_LIMIT", "remaining_steps": 99}


@pytest.mark.parametrize("name", POLICIES)
def test_linux_four_adapters_fixtures_and_large_episode(name):
    require_linux()
    for fixture, generator in (("company-a", None), ("company-b", None), ("company-b", config("large-mixed"))):
        result = run_baseline(name, fixture=fixture, generator=generator, seed=7091)
        local = run_local_policy(name, fixture=fixture, generator=generator, seed=7091)
        assert result["trajectory"] == local["trajectory"]
        assert result["private_result"]["score"] == local["private_result"]["score"]
        if name != "oracle":
            assert result["private_result"]["agent_uid"] == 65534
            assert result["private_result"]["agent_reaped"]


def test_linux_timeout_capture_and_fresh_adapter(tmp_path):
    require_linux()
    sleeper = tmp_path / "sleep.py"
    sleeper.write_text("import time\ntime.sleep(10)\n")
    result = run_isolated_fixture(policy_path=sleeper, seconds=.2)
    result = add_metrics(result, "sleeping-test")
    save_run(result, tmp_path / "timeout")
    assert result["private_result"]["inspection_steps"] == 0
    assert result["private_result"]["reason"] == "timeout"
    assert result["trajectory"][-1]["action"] is None
    assert result["trajectory"][-1]["truncated"] and not result["trajectory"][-1]["delivered"]
    assert run_baseline("reconciliation", fixture="company-a")["private_result"]["submission"]["findings"] == []
