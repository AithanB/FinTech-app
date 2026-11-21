"""Three-minute release demo through the same isolated runner and evaluator."""

import argparse
import json
from pathlib import Path

from .baselines import add_metrics, run_baseline, save_run
from .isolation import run_isolated_fixture
from .verify import preflight, require, write_json


def run_demo(output):
    preflight()
    output = Path(output)
    require(not output.exists() or not any(output.iterdir()), "demo output must be empty or new")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    cases = (
        ("supported-finding", lambda: run_baseline("reconciliation", fixture="company-b"), (1, 0, 0, .992, 5)),
        ("clean-answer", lambda: run_baseline("reconciliation", fixture="company-a"), (0, 0, 0, .992, 5)),
        ("failed-accusation", lambda: add_metrics(run_isolated_fixture(
            fixture="company-a", policy_path=Path(__file__).resolve().parent.parent / "policies/demo_accusation.py"),
            "demo-accusation"), (0, 1, 0, -1, 2)),
    )
    rows = []
    for name, run, expected in cases:
        result = run()
        private = result["private_result"]
        score = private["score"]
        actual = (score["tp"], score["fp"], score["fn"], private["return"], private["total_actions"])
        require(actual == expected and score["validation_error"] is None, f"demo outcome mismatch: {name}")
        require(private["agent_uid"] == 65534 and private["agent_reaped"] and private["reason"] == "completed",
                "demo did not use completed isolated policy execution")
        require(all(event["reward"] == 0 for event in result["trajectory"]), "closed reward leaked")
        if name == "supported-finding":
            finding, = private["submission"]["findings"]
            require(finding["claimed_amount_minor"] == 2_000_000 and
                    set(finding["evidence_ids"]) == {"doc-492", "settlement:pay-627"}, "unsupported demo proof")
        save_run(result, output / name)
        rows.append({"case": name, "episode_id": result["initial_observation"]["manifest"]["episode_id"],
                     "tp": score["tp"], "fp": score["fp"], "fn": score["fn"], "f1": score["f1"],
                     "return": private["return"], "inspection_steps": private["inspection_steps"],
                     "total_actions": private["total_actions"], "trajectory": f"{name}/trajectories.jsonl"})
    report = {"version": "stage12-demo-v1", "passed": True, "cases": rows}
    write_json(output / "demo.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/stage-12-demo"))
    args = parser.parse_args()
    try:
        print(json.dumps(run_demo(args.output), indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"demo failed: {exc}\n")


if __name__ == "__main__":
    main()
