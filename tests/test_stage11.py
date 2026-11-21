"""Independent verifier canary, aggregation, artifact reconciliation and failures."""

import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from audit_env.baselines import POLICIES, run_local_policy, save_run
from audit_env.datasets import load_plan
from audit_env.generation import generate_episode
from audit_env.replay import digest
from audit_env.verify import (
    DEFAULT_EXPECTATIONS, ROOT, capture_metrics, check_canary, check_results, failure_analysis,
    preflight, summarize, timeout_probe, verify,
)
from test_stage05 import require_linux


def test_canary_uses_independent_seven_minus_five_million_fixture():
    actual = check_canary()
    assert actual["claimed_amount_minor"] == 7_000_000 - 5_000_000
    assert actual["return"] == 1 - .002 * 4
    assert (actual["tp"], actual["fp"], actual["fn"]) == (1, 0, 0)


def test_actual_cli_rejects_deliberately_wrong_temporary_expectation(tmp_path):
    original = DEFAULT_EXPECTATIONS.read_bytes()
    wrong = json.loads(original)
    wrong["claimed_amount_minor"] = 3_000_000
    path = tmp_path / "incorrect-expected.json"
    path.write_text(json.dumps(wrong), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "audit_env.verify", "--expectations", str(path),
                             "--output", str(tmp_path / "failed-output")], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1 and "hand-calculated canary mismatch" in result.stderr
    assert DEFAULT_EXPECTATIONS.read_bytes() == original
    assert not (tmp_path / "failed-output/results.json").exists()
    assert check_canary()["claimed_amount_minor"] == 2_000_000


def test_summary_is_arithmetic_mean_including_clean_zero_precision():
    rows = []
    for name in POLICIES:
        for tp, fp, fn, p, r, f1, reward, steps, seconds in (
            (0, 0, 0, 0, 0, 1, .992, 4, .25),
            (1, 1, 2, .5, 1 / 3, .4, -.212, 6, .75),
        ):
            rows.append({"policy": name, "tp": tp, "fp": fp, "fn": fn,
                         "precision": p, "recall": r, "f1": f1, "return": reward,
                         "inspection_steps": steps, "total_actions": steps + 1,
                         "elapsed_seconds": seconds, "memory_peak_upper_bound_bytes": 1024 * steps})
    for summary in summarize(rows).values():
        assert summary["means"] == {"precision": .25, "recall": 1 / 6, "f1": .7, "return": .39,
                                     "inspection_steps": 5, "total_actions": 6, "elapsed_seconds": .5}
        assert summary["totals"] == {"tp": 1, "fp": 1, "fn": 2}
        assert summary["max_elapsed_seconds"] == .75
        assert summary["max_memory_peak_upper_bound_bytes"] == 6144


def captured_case(tmp_path):
    spec = load_plan().rehearsal[0]
    episode = generate_episode(spec.seed, spec.generator)
    result = run_local_policy("oracle", episode=episode)
    save_run(result, tmp_path)
    memory = {"public_sha256": digest(episode.public.model_dump(mode="json")),
              "evaluator_peak_rss_bytes": 1024, "policy_peak_rss_bytes": 0, "memory_peak_upper_bound_bytes": 1024}
    return episode, memory


@pytest.mark.parametrize("damage", ["reward", "count", "score", "episode", "slow", "memory"])
def test_reconciliation_detects_corrupt_artifacts_or_exceeded_resources(tmp_path, damage):
    episode, memory = captured_case(tmp_path)
    assert capture_metrics(episode, tmp_path, "oracle", memory, .1)["f1"] == 1
    elapsed = .1
    if damage == "reward":
        path = tmp_path / "trajectories.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[-1]["reward"] = 1
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    elif damage in ("count", "score"):
        path = tmp_path / "private-result.json"
        result = json.loads(path.read_text())
        if damage == "count":
            result["total_actions"] = 100
        else:
            result["score"]["f1"] = .5
        path.write_text(json.dumps(result), encoding="utf-8")
    elif damage == "episode":
        memory["public_sha256"] = "wrong"
    elif damage == "slow":
        elapsed = 61
    else:
        memory["memory_peak_upper_bound_bytes"] = 5 * 1024**3
    with pytest.raises(ValueError):
        capture_metrics(episode, tmp_path, "oracle", memory, elapsed)


def test_exact_eighty_results_and_summary_reconciliation_reject_damage():
    plan = load_plan()
    rows = []
    for spec in plan.rehearsal:
        eid = generate_episode(spec.seed, spec.generator).public.manifest.episode_id
        for name in POLICIES:
            rows.append({"episode_id": eid, "policy": name,
                         **{key: 0 for key in ("tp", "fp", "fn", "precision", "recall", "f1", "return",
                                              "inspection_steps", "total_actions", "elapsed_seconds", "memory_peak_upper_bound_bytes")}})
    summary = summarize(rows)
    check_results(rows, summary, plan)
    with pytest.raises(ValueError, match="80"):
        check_results(rows[:-1], summary, plan)
    duplicate = copy.deepcopy(rows)
    duplicate[-1] = duplicate[0]
    with pytest.raises(ValueError, match="combinations"):
        check_results(duplicate, summary, plan)
    summary["oracle"]["means"]["return"] = 1
    with pytest.raises(ValueError, match="summary"):
        check_results(rows, summary, plan)


def test_existing_output_is_not_overwritten_and_failed_suite_cannot_report_pass(tmp_path, monkeypatch):
    import audit_env.verify as module

    monkeypatch.setattr(module, "preflight", lambda: ["lo"])
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "results.json"
    sentinel.write_text("previous report")
    with pytest.raises(ValueError, match="empty or new"):
        verify(occupied)
    assert sentinel.read_text() == "previous report"

    def failed_tests(_):
        raise ValueError("injected failing suite")

    monkeypatch.setattr(module, "run_tests", failed_tests)
    fresh = tmp_path / "failed"
    with pytest.raises(ValueError, match="injected"):
        verify(fresh)
    assert json.loads((fresh / "failure.json").read_text())["status"] == "failed"
    assert not (fresh / "results.json").exists()


@pytest.mark.parametrize("policy,findings", [("random", 0), ("mass_accusation", 30)])
def test_failure_narrative_distinguishes_silence_from_unsupported_accusations(tmp_path, policy, findings):
    plan = load_plan()
    spec = plan.rehearsal[6]  # Retained failure: seed 30007, one allocation issue.
    episode = generate_episode(spec.seed, spec.generator)
    result = run_local_policy(policy, episode=episode, policy_seed=0)
    directory = tmp_path / "trajectories" / episode.public.manifest.episode_id / policy
    save_run(result, directory)
    private = result["private_result"]
    assert len(private["submission"]["findings"]) == findings
    row = {"episode_id": episode.public.manifest.episode_id, "policy": policy, "issue_count": 1,
           "config_index": 6, "tp": 0, "fp": findings, "fn": 1, "return": -1,
           "inspection_steps": private["inspection_steps"], "total_actions": private["total_actions"]}
    failure, = failure_analysis([row], tmp_path, plan)
    assert failure["submitted_findings"] == findings and failure["findings_with_complete_truth_proof"] == 0
    assert failure["missed_issue_types"] == ["payment_allocation"]
    if findings:
        assert "document-only accusations" in failure["explanation"]
    else:
        assert "empty answer" in failure["explanation"] and "false negatives" in failure["explanation"]
        assert "guessed" not in failure["explanation"]


def test_linux_fresh_worker_measures_memory_and_uses_actual_jail(tmp_path):
    require_linux()
    assert preflight() == ["lo"]
    spec = load_plan().rehearsal[-1]
    worker_spec = {"seed": spec.seed, "generator": spec.generator.model_dump(mode="json"),
                   "policy": "reconciliation", "policy_seed": 0, "seconds": 60, "output": str(tmp_path / "run")}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(worker_spec))
    result = subprocess.run([sys.executable, "-m", "audit_env.verify", "--worker-spec", str(path)],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    memory = json.loads(result.stdout)
    assert memory["policy_peak_rss_bytes"] > 0 and memory["evaluator_peak_rss_bytes"] > 0
    assert memory["memory_peak_upper_bound_bytes"] == memory["policy_peak_rss_bytes"] + memory["evaluator_peak_rss_bytes"]
    row = capture_metrics(generate_episode(spec.seed, spec.generator), tmp_path / "run", "reconciliation", memory, 1)
    assert row["documents"] == 200 and row["tp"] == 12 and row["fp"] == row["fn"] == 0


def test_linux_timeout_probe_preserves_actual_null_event(tmp_path):
    require_linux()
    result = timeout_probe(tmp_path)
    assert result["reason"] == "timeout" and result["actions"] == 0 and result["agent_reaped"]
    trace = [json.loads(line) for line in (tmp_path / result["trace"]).read_text().splitlines()]
    assert trace[-1]["action"] is None and trace[-1]["truncated"] and not trace[-1]["delivered"]
