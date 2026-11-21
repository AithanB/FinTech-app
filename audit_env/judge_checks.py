"""Local checks of the published D01-D20 and P01-P20 matrix, via file loading."""

import argparse
import json
from pathlib import Path
import tempfile

from judge_adapter import generate_episode, make_env, score_episode
from .generation import generate_episode as generate
from .datasets import validate_episode
from .replay import digest, oracle_action
from .serialization import save_public, write_json
from .transformations import id_mapping, remap_ids, transform_episode


def specs():
    for index in range(20):
        config = dict(version="stage08-v1", invoice_count=36 + index,
                      currencies=["KZT", "USD", "EUR", "JPY"], boundary_cases=True,
                      timezone=("UTC", "Asia/Almaty", "America/New_York")[index % 3],
                      size_profile="small")
        if 5 <= index < 8:
            config["duplicate_invoices"] = 1
        elif 8 <= index < 11:
            config["missing_allocations" if index == 8 else "partial_allocations"] = 1
        elif 11 <= index < 13:
            config["wrong_fx_dates" if index == 11 else "wrong_fx_rates"] = 1
        elif 13 <= index < 15:
            config["misplaced_recognitions"] = 1
        elif 15 <= index < 18:
            config.update(partial_allocations=1, misplaced_applications=1,
                          boundary_scenario={"count": 1, "variant": "both"})
        elif index >= 18:
            config.update(duplicate_invoices=1, wrong_fx_rates=1,
                          duplicate_fx_scenario={"count": 1, "variant": "both"})
        yield 51001 + index, config


def check_matrix():
    rows = []
    with tempfile.TemporaryDirectory(prefix="jury-matrix-") as temporary:
        for index, (seed, config) in enumerate(specs()):
            source = Path(temporary) / f"D{index+1:02d}"
            generate_episode(seed, config, str(source))
            episode = validate_episode(generate(seed, config))
            mode = "order" if index < 5 else "ids" if index < 10 else "both"
            mapping = id_mapping(episode, 61001 + index)
            if mode == "order":
                mapping = {key: key for key in mapping}
            transformed, mapping = transform_episode(episode, 61001 + index, mapping=mapping,
                                                      rename=False, reorder=mode != "ids")
            validate_episode(transformed)
            target = Path(temporary) / f"P{index+1:02d}"
            target.mkdir()
            save_public(target, transformed.public)
            (target / "private").mkdir()
            write_json(target / "private/truth.json", transformed.truth)
            write_json(target / "private/provenance.json", transformed.provenance)
            native = oracle_action(episode)
            actions = [dict(name="list_records", args=dict(table="ledger", cursor=None, limit=50)),
                       dict(name="calculator", args=dict(expression="0.1+0.2")),
                       dict(name="submit", args=dict(findings=native["findings"]))]

            def replay(directory, requests):
                env = make_env()
                initial = env.reset(seed, dict(mode="closed", episode_dir=str(directory), team_config=config))
                return initial, [env.step(action) for action in requests]

            first = replay(source, actions)
            assert first == replay(source, actions), "source replay changed"
            mapped = remap_ids(actions, mapping)
            target_run = replay(target, mapped)
            assert target_run[0][0]["manifest"]["episode_id"] == transformed.public.manifest.episode_id
            assert target_run[1][-1] == first[1][-1]
            score = score_episode(str(source), actions[-1]["args"]["findings"], 2)
            other = score_episode(str(target), mapped[-1]["args"]["findings"], 2)
            assert score == other and score["f1"] == 1 and score["return"] == .996
            inverse = {value: key for key, value in mapping.items()}
            assert remap_ids(mapped[-1], inverse) == actions[-1]
            rows.append(dict(case=f"D{index+1:02d}", pair=f"P{index+1:02d}", seed=seed,
                             config=config, transformation=mode, issues=len(episode.truth.issues),
                             score=score, replay_sha256=digest(first)))
    return dict(version="jury-checks-2026-11-20", passed=True, episodes=20, pairs=20,
                transformations=dict(order=5, ids=5, both=10), rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check_matrix()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("D01-D20 and P01-P20: passed (5 order, 5 IDs, 10 combined)")


if __name__ == "__main__":
    main()
