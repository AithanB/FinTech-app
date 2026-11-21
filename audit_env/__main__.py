import sys
import argparse
import json
from pathlib import Path
from decimal import Decimal
from zoneinfo import ZoneInfo

import pydantic


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit runtime, episode generation and isolated demonstrations")
    parser.add_argument("--fixture", type=Path, help="public episode directory")
    parser.add_argument("--demo-fixture", choices=("company-a", "company-b"), help="run a fixture episode")
    parser.add_argument("--isolated-fixture", choices=("company-a", "company-b"), help="run a restricted Linux policy")
    parser.add_argument("--generate", type=Path, help="export a generated episode to a NEW directory")
    parser.add_argument("--isolated-generated", action="store_true", help="run generated records with a restricted Linux policy")
    parser.add_argument("--generator-config", type=Path, help="versioned generator JSON configuration")
    parser.add_argument("--seed", type=int, default=6, help="trusted generator seed")
    parser.add_argument("--policy", type=Path, help="policy program for isolated execution")
    parser.add_argument("--seconds", type=float, default=60.0, help="isolated policy deadline")
    parser.add_argument("--private-result", type=Path, help="trusted result JSON (never sent to policy)")
    parser.add_argument("--trace", type=Path, help="write a public JSONL trajectory")
    args = parser.parse_args()
    if sum((args.generate is not None, args.isolated_generated, args.isolated_fixture is not None,
            args.demo_fixture is not None, args.fixture is not None)) > 1:
        parser.error("choose one episode operation")
    if args.generator_config and not (args.generate is not None or args.isolated_generated):
        parser.error("--generator-config requires --generate or --isolated-generated")
    if args.generate is not None or args.isolated_generated:
        from .generation import GeneratorConfig

        config = GeneratorConfig.model_validate_json(args.generator_config.read_text(encoding="utf-8")) if args.generator_config else GeneratorConfig()
    if args.generate is not None:
        from .generation import generate_episode, save_generated

        episode = generate_episode(args.seed, config)
        save_generated(args.generate, episode)
        print(f"Generated episode: {episode.public.manifest.episode_id}")
        print(f"Public directory: {args.generate / 'public'}")
        print(f"Trusted issue count: {len(episode.truth.issues)}")
        if config.version == "stage08-v1":
            from .validation import validate_final_evidence

            report = validate_final_evidence(episode.public, episode.truth)
            print(f"Validated ledger rows/documents: {report['ledger_rows']}/{report['documents']}")
            print(f"Public evidence discovery bound (including submit): {report['discovery_actions']}")
        return
    if args.isolated_fixture is not None or args.isolated_generated:
        from .isolation import run_isolated_fixture, run_isolated_generated

        options = {"policy_path": args.policy, "seconds": args.seconds}
        result = run_isolated_generated(args.seed, config, **options) if args.isolated_generated else run_isolated_fixture(args.isolated_fixture, **options)
        stage = {"stage06-v1": "stage-06", "stage07-v1": "stage-07", "stage08-v1": "stage-08"}[config.version] if args.isolated_generated else "stage-05"
        trace = args.trace or Path(f"runs/{stage}/trajectories.jsonl" if args.isolated_generated else "runs/stage-05/trajectories.jsonl")
        trace.parent.mkdir(parents=True, exist_ok=True)
        trace.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [
            {"metadata": {"initial_observation": result["initial_observation"]}}, *result["trajectory"],
        ]) + "\n", encoding="utf-8")
        private = args.private_result or trace.with_name("private-result.json")
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(json.dumps(result["private_result"], indent=2), encoding="utf-8")
        private.chmod(0o600)
        print(f"Public trajectory: {trace}")
        print(f"Trusted evaluator score: {result['private_result']['score']['score']}")
        print(f"Private result: {private}")
        return
    if args.demo_fixture is not None:
        from .runner import run_fixture_demo

        trace_path = args.trace or (Path("tests/fixtures") / "provisional-trajectory.jsonl")
        result = run_fixture_demo(args.demo_fixture, trace_path)
        for item in result["trajectory"]:
            print(json.dumps({
                "step": item["step"],
                "observation": item["observation"],
                "reward": item["reward"],
                "terminated": item["terminated"],
                "truncated": item["truncated"],
            }, ensure_ascii=False))
        print(f"Trusted evaluator score: {result['private_score']}")
        print(f"Trajectory: {trace_path}")
        return
    if args.fixture is not None:
        from .serialization import load_public
        from .views import settlement_view

        episode = load_public(args.fixture)
        print(json.dumps({
            "episode_id": episode.manifest.episode_id,
            "settlements": [settlement_view(payment, episode.ledger).model_dump(mode="json") for payment in episode.payments],
        }, indent=2))
        return
    print(f"Python: {sys.version.split()[0]}")
    print(f"Pydantic: {pydantic.__version__}")
    print(f"Decimal: {Decimal('0.1') + Decimal('0.2')}")
    print(f"Timezone: {ZoneInfo('Asia/Almaty').key}")
    print("Environment is ready.")


if __name__ == "__main__":
    main()
