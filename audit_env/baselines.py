"""Stage 09 runner: ordinary policies in the jail, oracle in the evaluator.

The local runner is a portable contract-test harness, not an isolation boundary.
The CLI always uses the prepared Linux process boundary for ordinary policies.
"""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import asdict
from pathlib import Path
import time

from policies.baselines import EpisodeEnded, ORDINARY_POLICIES, run_policy
from policies.oracle import run_policy as run_oracle

from .environment import AuditEnvironment
from .wire import initial_message, transition_message


POLICIES = (*ORDINARY_POLICIES, "oracle")
POLICY_VERSION = "stage09-v1"


def reset_options(fixture, generator):
    return {"mode": "closed", **({"fixture": fixture} if generator is None else {"generator": generator})}


def add_metrics(result, name):
    private = result["private_result"]
    actions = private["actions"]
    submitted = bool(result["trajectory"] and result["trajectory"][-1]["action"] is not None
                     and result["trajectory"][-1]["action"].get("type") == "submit")
    private.update({"policy": name, "policy_version": POLICY_VERSION,
                    "inspection_steps": actions - int(submitted), "total_actions": actions,
                    "return": private["score"]["score"]})
    return result


def run_local_policy(name, *, fixture="company-b", generator=None, seed=6, policy_seed=0, episode=None):
    """Trusted test harness. Ordinary adapter inputs remain public-only here."""
    if name not in POLICIES:
        raise ValueError("unknown policy")
    env = AuditEnvironment()
    if episode is not None and generator is not None:
        raise ValueError("choose generated configuration or loaded episode")
    initial, _ = (env.reset(seed=seed, config=reset_options(fixture, generator)) if episode is None
                  else env.reset_episode(episode.public, episode.truth))
    records = []
    started = time.monotonic()

    def act(action):
        # Cross a JSON serialization boundary just as the process transport does.
        request = json.loads(json.dumps(action, allow_nan=False))
        message = transition_message(request, env.step(request), closed=True)
        delivered = json.loads(json.dumps(message, allow_nan=False))
        records.append({"episode_id": initial["manifest"]["episode_id"],
                        "step": len(records) + 1, "action": request, "delivered": True,
                        **copy.deepcopy(delivered)})
        if delivered["terminated"] or delivered["truncated"]:
            raise EpisodeEnded
        return delivered["observation"]["result"]

    public_initial = initial_message(initial)["observation"]
    if name == "oracle":
        try:
            run_oracle(public_initial, act, truth=env._truth)
        except EpisodeEnded:
            pass
    else:
        run_policy(name, public_initial, act, seed=policy_seed)
    return add_metrics({
        "initial_observation": initial, "trajectory": records,
        "private_result": {
            "score": asdict(env._last_scoring_result),
            "submission": env._last_submission.model_dump(mode="json"),
            "actions": env.action_count,
            "reason": "step_limit" if records[-1]["truncated"] else "completed",
            "elapsed_seconds": time.monotonic() - started,
            "execution": "trusted oracle" if name == "oracle" else "local test harness",
        },
    }, name)


def policy_program(name, policy_seed=0):
    """Bundle only public-data adapters and the independent explorer seed."""
    if name not in ORDINARY_POLICIES:
        raise ValueError("oracle cannot be packaged as an ordinary policy")
    if type(policy_seed) is not int:
        raise ValueError("policy seed must be an integer")
    source = Path(__file__).resolve().parent.parent / "policies/baselines.py"
    return source.read_bytes() + f"\nwire_main({name!r}, {policy_seed!r})\n".encode()


def run_baseline(name, *, fixture="company-b", generator=None, seed=6, policy_seed=0, seconds=60, episode=None):
    if name == "oracle":
        return run_local_policy(name, fixture=fixture, generator=generator, seed=seed, episode=episode)
    from .isolation import run_isolated_fixture

    result = run_isolated_fixture(fixture, generator_config=generator, seed=seed,
                                  policy_program=policy_program(name, policy_seed), seconds=seconds, episode=episode)
    return add_metrics(result, name)


def save_run(result, directory):
    """Serialize captured delivery snapshots, keeping evaluator data separate."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    metadata = {"initial_observation": result["initial_observation"],
                "policy": result["private_result"]["policy"], "policy_version": POLICY_VERSION}
    with (directory / "trajectories.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for record in [{"metadata": metadata}, *result["trajectory"]]:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    private_path = directory / "private-result.json"
    private_path.touch(mode=0o600, exist_ok=True)
    private_path.chmod(0o600)
    private_path.write_text(json.dumps(result["private_result"], indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--fixture", choices=("company-a", "company-b"), default="company-b")
    source.add_argument("--generator-config", type=Path)
    source.add_argument("--episode", type=Path, help="exported public episode directory")
    parser.add_argument("--evaluator", type=Path, help="trusted evaluator directory for --episode")
    parser.add_argument("--baseline", choices=("all", *POLICIES), default="all")
    parser.add_argument("--seed", type=int, default=6, help="trusted company seed")
    parser.add_argument("--policy-seed", type=int, default=0, help="independent random explorer seed")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, default=Path("runs/stage-09"))
    args = parser.parse_args()
    if bool(args.episode) != bool(args.evaluator):
        parser.error("--episode and --evaluator are required together")
    episode = None
    if args.episode:
        from .datasets import load_episode

        episode = load_episode(args.episode, args.evaluator)
    generator = json.loads(args.generator_config.read_text(encoding="utf-8")) if args.generator_config else None
    for name in POLICIES if args.baseline == "all" else (args.baseline,):
        result = run_baseline(name, fixture=args.fixture, generator=generator, seed=args.seed,
                              policy_seed=args.policy_seed, seconds=args.seconds, episode=episode)
        save_run(result, args.output / name)
        private = result["private_result"]
        score = private["score"]
        print(json.dumps({"policy": name, "precision": score["precision"], "recall": score["recall"],
                          "f1": score["f1"], "return": private["return"],
                          "inspections": private["inspection_steps"], "actions": private["total_actions"],
                          "elapsed_seconds": private["elapsed_seconds"], "reason": private["reason"]}))


if __name__ == "__main__":
    main()
