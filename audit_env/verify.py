"""Offline Stage 11 verification and local rehearsal, never jury evaluation.

Run the default command inside the prepared Linux image with --network none.
Ordinary policies always use the jail. Each benchmark run has a fresh trusted
worker, so kernel memory high-water marks do not accumulate across episodes.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from .baselines import POLICIES, POLICY_VERSION, run_baseline, run_local_policy, save_run
from .datasets import DATASET_VERSION, DEFAULT_PLAN, export_dataset, load_plan, paired_report, validate_episode
from .generation import generate_episode
from .isolation import RUNTIME, run_isolated_fixture
from .replay import REPLAY_VERSION, digest, verify_capture
from .transformations import TRANSFORM_VERSION


ROOT = Path(__file__).resolve().parent.parent
VERIFY_VERSION = "stage11-v1"
DEFAULT_EXPECTATIONS = ROOT / "configs/stage11-expected.json"
MEAN_FIELDS = ("precision", "recall", "f1", "return", "inspection_steps", "total_actions", "elapsed_seconds")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    path.chmod(0o600)


def check_canary(expectations=DEFAULT_EXPECTATIONS):
    """Independent Stage 02 fixture: 7M intended - 5M applied, four inspections."""
    expected = json.loads(Path(expectations).read_text(encoding="utf-8"))
    result = run_local_policy("reconciliation", fixture="company-b")
    private = result["private_result"]
    finding, = private["submission"]["findings"]
    actual = {"version": "stage11-canary-v1", "claimed_amount_minor": finding["claimed_amount_minor"],
              **{key: private["score"][key] for key in ("tp", "fp", "fn", "precision", "recall", "f1")},
              **{key: private[key] for key in ("return", "inspection_steps", "total_actions")}}
    require(expected == actual, "hand-calculated canary mismatch")
    return actual


def preflight():
    require(sys.platform == "linux" and os.geteuid() == 0 and (RUNTIME / "bootstrap.py").is_file(),
            "use the prepared Linux image as root; ordinary policies require its isolation runtime")
    interfaces = sorted(p.name for p in Path("/sys/class/net").iterdir())
    require(interfaces == ["lo"], "verification requires --network none (only loopback may exist)")
    return interfaces


def hardware():
    def read(path):
        target = Path(path)
        return target.read_text().strip() if target.is_file() else None

    cpu_model = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                      if line.startswith("model name")), platform.machine())
    return {"platform": platform.platform(), "machine": platform.machine(), "cpu_model": cpu_model,
            "host_logical_cpus": os.cpu_count(), "affinity_cpus": len(os.sched_getaffinity(0)),
            "cgroup_cpu_max": read("/sys/fs/cgroup/cpu.max"),
            "cgroup_memory_max": read("/sys/fs/cgroup/memory.max"),
            "host_mem_total": next(line for line in Path("/proc/meminfo").read_text().splitlines()
                                   if line.startswith("MemTotal:"))}


def worker(spec_path):
    """Internal fresh-process entry: evaluator owns the input spec and output path."""
    import resource

    preflight()
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    episode = validate_episode(generate_episode(spec["seed"], spec["generator"]))
    result = run_baseline(spec["policy"], episode=episode, policy_seed=spec["policy_seed"], seconds=spec["seconds"])
    save_run(result, Path(spec["output"]))
    # Linux ru_maxrss is KiB. The child mark includes jail setup before exec.
    evaluator_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    policy_peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024
    print(json.dumps({"public_sha256": digest(episode.public.model_dump(mode="json")),
                      "evaluator_peak_rss_bytes": evaluator_peak, "policy_peak_rss_bytes": policy_peak,
                      "memory_peak_upper_bound_bytes": evaluator_peak + policy_peak}))


def capture_metrics(episode, directory, policy, memory, elapsed):
    """Reconcile metrics against retained actions and semantic response replay."""
    capture = [json.loads(line) for line in (directory / "trajectories.jsonl").read_text(encoding="utf-8").splitlines()]
    private = json.loads((directory / "private-result.json").read_text(encoding="utf-8"))
    replay = verify_capture(episode, capture)
    # Dataclass match tuples become arrays in saved JSON; compare wire values.
    require(json.loads(json.dumps(replay["score"])) == private["score"], "trace and private score disagree")
    actions = [row["action"] for row in capture[1:] if row["action"] is not None]
    submitted = bool(actions and actions[-1].get("type") == "submit")
    inspections = len(actions) - int(submitted)
    require(private["actions"] == private["total_actions"] == replay["actions"] == len(actions), "action count mismatch")
    require(private["inspection_steps"] == inspections, "inspection count mismatch")
    require(0 < len(actions) <= 100 and private["reason"] == "completed" and submitted, "benchmark did not submit within budget")
    require(private["score"]["validation_error"] is None, "baseline submission is malformed")
    require(all(row["reward"] == 0 and row["info"] == {} and row["delivered"] for row in capture[1:]),
            "benchmark trace is not a completed closed-mode delivery capture")
    require(policy == private["policy"], "policy identity mismatch")
    require(memory["public_sha256"] == digest(episode.public.model_dump(mode="json")), "worker episode mismatch")
    if policy != "oracle":
        require(private["agent_uid"] == 65534 and private["agent_reaped"], "ordinary policy was not jailed and reaped")
    score = private["score"]
    tp, fp, fn = (score[key] for key in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 1
    expected_return = max(-1, min(1, 2 * f1 - 1 - .002 * inspections))
    require((score["precision"], score["recall"], score["f1"], score["score"], private["return"])
            == (precision, recall, f1, expected_return, expected_return), "score arithmetic mismatch")
    require(tp + fn == len(episode.truth.issues), "truth count mismatch")
    require(math.isfinite(elapsed) and 0 < elapsed <= 60, "episode exceeded 60-second end-to-end target")
    require(0 < memory["memory_peak_upper_bound_bytes"] <= 4 * 1024**3, "episode exceeded memory target")
    return {"episode_id": episode.public.manifest.episode_id, "policy": policy,
            "issue_count": len(episode.truth.issues), "ledger_rows": len(episode.public.ledger),
            "documents": episode.public.manifest.document_count,
            **{key: score[key] for key in ("tp", "fp", "fn", "precision", "recall", "f1")},
            "return": private["return"], "inspection_steps": inspections, "total_actions": len(actions),
            "elapsed_seconds": elapsed, "policy_elapsed_seconds": private["elapsed_seconds"],
            "reason": private["reason"], **memory}


def summarize(rows):
    summary = {}
    for policy in POLICIES:
        selected = [row for row in rows if row["policy"] == policy]
        require(bool(selected), "missing policy rows")
        summary[policy] = {"episodes": len(selected),
                           "means": {key: math.fsum(row[key] for row in selected) / len(selected) for key in MEAN_FIELDS},
                           "totals": {key: sum(row[key] for row in selected) for key in ("tp", "fp", "fn")},
                           "max_elapsed_seconds": max(row["elapsed_seconds"] for row in selected),
                           "max_memory_peak_upper_bound_bytes": max(row["memory_peak_upper_bound_bytes"] for row in selected)}
    return summary


def check_results(rows, summary, plan):
    ids = {generate_episode(spec.seed, spec.generator).public.manifest.episode_id for spec in plan.rehearsal}
    require(len(rows) == 80 and len(ids) == 20, "expected 80 policy-episode rows and 20 episode IDs")
    require({(row["episode_id"], row["policy"]) for row in rows} == {(eid, p) for eid in ids for p in POLICIES},
            "benchmark is missing or duplicating policy-episode combinations")
    require(summary == summarize(rows), "summary does not reconcile with individual rows")


def run_tests(output):
    junit = output / "tests.xml"
    command = [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}"]
    result = subprocess.run(command, cwd=ROOT, env={**os.environ, "AUDIT_REQUIRE_ISOLATION": "1"},
                            capture_output=True, text=True, timeout=300)
    (output / "tests.log").write_text(result.stdout + result.stderr, encoding="utf-8", newline="\n")
    require(result.returncode == 0, "pytest failed; see tests.log")
    cases = list(ET.parse(junit).iter("testcase"))
    skipped = [case.attrib["name"] for case in cases if case.find("skipped") is not None]
    require(bool(cases) and all(name == "test_never_fall_back_to_unrestricted_windows_policy" for name in skipped),
            "required checks were skipped or no tests ran")
    return {"command": command, "passed": len(cases) - len(skipped), "skipped": skipped}


def timeout_probe(output):
    """Actual nonresponsive jailed process, separate from the 80 benchmark rows."""
    program = b"import json,sys,time\njson.loads(sys.stdin.readline())\ntime.sleep(10)\n"
    result = run_isolated_fixture(policy_program=program, seconds=.2)
    private = result["private_result"]
    event = result["trajectory"][-1]
    require(private["reason"] == "timeout" and private["agent_reaped"] and private["actions"] == 0
            and event["action"] is None and event["truncated"] and not event["delivered"], "timeout probe failed")
    from .baselines import add_metrics

    save_run(add_metrics(result, "timeout-probe"), output / "timeout")
    return {"reason": private["reason"], "actions": private["actions"], "agent_reaped": private["agent_reaped"],
            "elapsed_seconds": private["elapsed_seconds"], "trace": "timeout/trajectories.jsonl"}


def negative_control(output, expectations):
    """Run the real CLI with a throwaway incorrect answer; never edit the source."""
    original = Path(expectations).read_bytes()
    wrong = json.loads(original)
    wrong["claimed_amount_minor"] += 1
    path = output / "negative-control" / "incorrect-expected.json"
    write_json(path, wrong)
    process = subprocess.run([sys.executable, "-m", "audit_env.verify", "--expectations", str(path),
                              "--output", str(output / "negative-control" / "rejected-run")],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
    unchanged = Path(expectations).read_bytes() == original
    require(process.returncode == 1 and "hand-calculated canary mismatch" in process.stderr and unchanged,
            "incorrect expected result did not fail the verification command")
    check_canary(expectations)
    return {"returncode": process.returncode, "stderr": process.stderr.strip(), "original_unchanged": unchanged,
            "incorrect_input": "negative-control/incorrect-expected.json"}


def failure_analysis(rows, output, plan):
    failures = []
    for policy in POLICIES:
        candidates = [row for row in rows if row["policy"] == policy and row["issue_count"] and row["return"] < 0]
        if not candidates:
            continue
        row = min(candidates, key=lambda r: (r["return"], r["episode_id"]))
        trace_path = Path("trajectories") / row["episode_id"] / policy / "trajectories.jsonl"
        trace = [json.loads(line) for line in (output / trace_path).read_text(encoding="utf-8").splitlines()]
        findings = trace[-1]["action"]["findings"]["findings"]
        spec = plan.rehearsal[row["config_index"]]
        episode = generate_episode(spec.seed, spec.generator)
        complete_proofs = sum(any(set(proof).issubset(finding["evidence_ids"])
                                  for issue in episode.truth.issues for proof in issue.evidence_sets)
                              for finding in findings)
        require(row["tp"] == 0 and complete_proofs == 0, "failure narrative needs review: a guessed claim had complete proof")
        explanation = ("Submitted within budget; no supported finding matched. "
                       "The policy guessed document-only accusations without reconciling accounting relationships. "
                       "It missed the truth issues and supplied insufficient proof, rather than exhausting steps."
                       if findings else
                       "Submitted an empty answer within budget, so every truth issue was missed. "
                       "No accusations were made; the low return comes from false negatives, rather than exhausted steps.")
        failures.append({"policy": policy, "episode_id": row["episode_id"], "trace": trace_path.as_posix(),
                         "tp": row["tp"], "fp": row["fp"], "fn": row["fn"], "return": row["return"],
                         "inspection_steps": row["inspection_steps"], "total_actions": row["total_actions"],
                         "submitted_findings": len(findings), "terminal_step": trace[-1]["step"],
                         "findings_with_complete_truth_proof": complete_proofs,
                         "missed_issue_types": sorted({issue.type for issue in episode.truth.issues}),
                         "example_submitted_finding": findings[0] if findings else None,
                         "explanation": explanation})
    return failures


def report_text(report):
    lines = ["# Stage 11 local offline rehearsal", "", "Status: passed. These are local rehearsal results, not jury hidden evaluation.", "",
             f"Version: {VERIFY_VERSION}. Tests: {report['tests']['passed']} passed; {len(report['tests']['skipped'])} platform guard skipped.",
             "80 policy-episode runs; 20 separate transformed pairs; five clean and five interacting rehearsal inputs.", "",
             "## Policy arithmetic means", "", "Undefined precision/recall are zero, including clean oracle answers. Clean empty-answer F1 is one.", ""]
    for policy, summary in report["summary"].items():
        m = summary["means"]
        lines.append(f"- {policy}: P {m['precision']:.6f}, R {m['recall']:.6f}, F1 {m['f1']:.6f}, return {m['return']:.6f}; "
                     f"{m['inspection_steps']:.2f} inspections, {m['total_actions']:.2f} actions, {m['elapsed_seconds']:.4f} seconds. "
                     f"Totals TP/FP/FN: {summary['totals']['tp']}/{summary['totals']['fp']}/{summary['totals']['fn']}.")
    lines += ["", "## Resources and limits", "",
              f"Maximum episode wall time: {max(row['elapsed_seconds'] for row in report['rows']):.4f} seconds.",
              f"Maximum episode RSS upper bound: {max(row['memory_peak_upper_bound_bytes'] for row in report['rows']) / 1024**2:.2f} MiB.",
              "Memory is the sum of fresh-worker evaluator and child policy kernel RSS high-water marks; "
              "these peaks need not occur simultaneously. It is a conservative bound, not a simultaneous process-tree measurement. "
              "The child mark includes jail setup before exec. Wall time includes worker startup, generation, jail preparation, policy and trace writes.",
              f"CPU model: {report['hardware']['cpu_model']}. Cgroup CPU quota: {report['hardware']['cgroup_cpu_max']}; "
              f"memory limit: {report['hardware']['cgroup_memory_max']} bytes.",
              f"Actual upper rehearsal case: {max(row['ledger_rows'] for row in report['rows'])} ledger rows / "
              f"{max(row['documents'] for row in report['rows'])} documents. This generator does not reach the suggested 2,000-row upper envelope.",
              "The four policies are fixed scripts; this benchmark does not demonstrate learned-model improvement or general accounting ability.",
              "", "## Trace-supported failures", ""]
    for failure in report["failures"]:
        lines += [f"- {failure['policy']} on {failure['episode_id']}: return {failure['return']}, "
                  f"TP/FP/FN {failure['tp']}/{failure['fp']}/{failure['fn']}, "
                  f"{failure['total_actions']} actions, submit at step {failure['terminal_step']}. "
                  f"{failure['explanation']} Trace: [{failure['trace']}]({failure['trace']})."]
    lines += ["", "The timeout probe is separate from benchmark rows: a nonresponsive jailed policy was reaped, "
              "with a null-action timeout event and zero consumed actions.", "",
              f"Incorrect-expectation control: CLI exit {report['negative_control']['returncode']}; "
              f"original expectation unchanged: {report['negative_control']['original_unchanged']}.", "",
              "Full per-episode metrics, versions, hardware and source/config digests are in results.json. "
              "Paired checks are in paired-checks.json. Delivered closed rewards stay zero in traces; true scores stay in evaluator files.", ""]
    return "\n".join(lines)


def verify(output, *, plan_path=DEFAULT_PLAN, expectations=DEFAULT_EXPECTATIONS):
    canary = check_canary(expectations)
    interfaces = preflight()
    output = Path(output).resolve()
    # Never mingle an old pass report with a failed rerun.
    require(not output.exists() or not any(output.iterdir()), "output must be an empty or new directory")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    try:
        print("offline preflight and independent canary passed; running required test suite", flush=True)
        tests = run_tests(output)
        print(f"tests passed: {tests['passed']}; checking exported data and 20 pairs", flush=True)
        plan = load_plan(plan_path)
        from .judge_checks import check_matrix
        jury_matrix = check_matrix()
        write_json(output / "jury-matrix.json", jury_matrix)
        manifest = export_dataset(plan, ROOT, check=True)
        paired = paired_report(plan)
        require(paired["passed"] and paired["pair_count"] == 20 and paired["clean_pairs"] == paired["interacting_pairs"] == 5,
                "paired check coverage failed")
        write_json(output / "paired-checks.json", paired)
        timeout = timeout_probe(output)
        negative = negative_control(output, expectations)
        print("data, pairs, timeout and incorrect-expectation controls passed; starting 80 policy runs", flush=True)
        rows = []
        for index, spec in enumerate(plan.rehearsal):
            episode = validate_episode(generate_episode(spec.seed, spec.generator))
            for policy in POLICIES:
                relative = Path("trajectories") / episode.public.manifest.episode_id / policy
                directory = output / relative
                worker_spec = {"seed": spec.seed, "generator": spec.generator.model_dump(mode="json"),
                               "policy": policy, "policy_seed": 0, "seconds": 60, "output": str(directory)}
                with tempfile.TemporaryDirectory(prefix="audit-verify-") as temporary:
                    path = Path(temporary) / "spec.json"
                    write_json(path, worker_spec)
                    started = time.monotonic()
                    process = subprocess.run([sys.executable, "-m", "audit_env.verify", "--worker-spec", str(path)],
                                             cwd=ROOT, capture_output=True, text=True, timeout=70)
                    elapsed = time.monotonic() - started
                require(process.returncode == 0, f"benchmark worker failed: {policy}: {process.stderr[-1000:]}")
                memory = json.loads(process.stdout)
                row = capture_metrics(episode, directory, policy, memory, elapsed)
                row.update({"source_seed": spec.seed, "config_index": index, "trajectory": (relative / "trajectories.jsonl").as_posix()})
                rows.append(row)
            print(f"rehearsal {index + 1}/20: four policies completed", flush=True)
        summary = summarize(rows)
        check_results(rows, summary, plan)
        require(max(row["documents"] for row in rows) == 200, "upper size profile was not exercised")
        report = {"version": VERIFY_VERSION, "status": "passed", "scope": "local rehearsal; not jury hidden evaluation",
                  "created_at_utc": datetime.now(timezone.utc).isoformat(),
                  "versions": {"python": platform.python_version(), "pydantic": version("pydantic"), "pytest": version("pytest"),
                               "policy": POLICY_VERSION, "dataset": DATASET_VERSION, "replay": REPLAY_VERSION, "transform": TRANSFORM_VERSION},
                  "source_sha256": digest({p.relative_to(ROOT).as_posix(): p.read_bytes().hex()
                                          for p in [ROOT / "judge_adapter.py", *sorted(
                                              path for area in ("audit_env", "policies", "tests", "configs", "scripts")
                                              for path in (ROOT / area).rglob("*"))] if p.is_file() and "__pycache__" not in p.parts}),
                  "hardware": hardware(), "network_interfaces": interfaces,
                  "policy_seed": 0, "episode_seconds": 60,
                  "plan_sha256": digest(plan.model_dump(mode="json")), "plan": plan.model_dump(mode="json"),
                  "public_split_counts": {key: len(value) for key, value in manifest["splits"].items()},
                  "canary": canary, "tests": tests, "timeout_probe": timeout, "negative_control": negative,
                  "jury_matrix": jury_matrix,
                  "pair_count": paired["pair_count"], "rows": rows, "summary": summary,
                  "failures": failure_analysis(rows, output, plan)}
        saved = json.loads(json.dumps(report, allow_nan=False))
        check_results(saved["rows"], saved["summary"], plan)
        (output / "report.md").write_text(report_text(report), encoding="utf-8", newline="\n")
        # The pass artifact is written last, after validation and human report.
        write_json(output / "results.json", saved)
        return report
    except Exception as exc:
        write_json(output / "failure.json", {"version": VERIFY_VERSION, "status": "failed", "error": str(exc)})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/stage-11" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--expectations", type=Path, default=DEFAULT_EXPECTATIONS,
                        help="hand-calculated canary fixture; a mismatch fails verification")
    parser.add_argument("--worker-spec", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker_spec:
            worker(args.worker_spec)
        else:
            result = verify(args.output, plan_path=args.plan, expectations=args.expectations)
            print(json.dumps({"status": result["status"], "runs": len(result["rows"]), "pairs": result["pair_count"], "output": str(args.output)}))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
