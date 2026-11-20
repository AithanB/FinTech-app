import sys
import argparse
import json
from pathlib import Path
from decimal import Decimal
from zoneinfo import ZoneInfo

import pydantic


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit runtime smoke check and public fixture inspection")
    parser.add_argument("--fixture", type=Path, help="public episode directory")
    parser.add_argument("--demo-fixture", choices=("company-a", "company-b"), help="run a fixture episode")
    parser.add_argument("--trace", type=Path, help="write the provisional JSONL trajectory")
    args = parser.parse_args()
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
