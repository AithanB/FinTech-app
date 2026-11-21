"""Stage 10 dataset exports and reproducibility checks; no hidden jury inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .generation import GeneratedEpisode, GeneratorConfig, History, generate_episode, validate_accounting
from .replay import REPLAY_VERSION, check_pair, digest
from .schemas import Provenance, PublicEpisode, StrictModel, Truth
from .serialization import load_public, read_json, save_public
from .transformations import TRANSFORM_VERSION, transform_episode
from .validation import validate_final_evidence


DATASET_VERSION = "stage10-splits-v1"
DEFAULT_PLAN = Path(__file__).resolve().parent.parent / "configs/stage10-splits.json"
PUBLIC_FILES = {"manifest.json", "policy.json", "ledger.csv", "invoices.jsonl", "payments.jsonl", "fx.csv"}
PRIVATE_FILES = {"truth.json", "provenance.json", "history.json", "clean.json"}


class EpisodeSpec(StrictModel):
    seed: int
    generator: GeneratorConfig


class DatasetPlan(StrictModel):
    version: Literal["stage10-splits-v1"]
    train: Annotated[list[EpisodeSpec], Field(min_length=10, max_length=10)]
    dev: Annotated[list[EpisodeSpec], Field(min_length=10, max_length=10)]
    rehearsal: Annotated[list[EpisodeSpec], Field(min_length=20, max_length=20)]

    @model_validator(mode="after")
    def independent(self):
        specs = [*self.train, *self.dev, *self.rehearsal]
        if len({spec.seed for spec in specs}) != len(specs):
            raise ValueError("train/dev/rehearsal seeds must be disjoint")
        mixes = [spec.generator.model_dump_json() for spec in specs]
        if len(set(mixes)) != len(mixes):
            raise ValueError("train/dev/rehearsal parameter mixes must be disjoint")
        if any(s.generator.version != "stage08-v1" or s.generator.size_profile == "tiny" for s in specs):
            raise ValueError("dataset episodes require versioned non-tiny profiles")
        return self


def load_plan(path=DEFAULT_PLAN):
    return read_json(Path(path), DatasetPlan)


def validate_episode(episode):
    """Check exported/tranformed references, proofs, and causal row history."""
    episode_id = episode.public.manifest.episode_id
    if any(value != episode_id for value in (episode.clean.manifest.episode_id,
                                             episode.truth.episode_id, episode.provenance.episode_id)):
        raise ValueError("episode identity mismatch")
    validate_accounting(episode.clean, clean=True)
    validate_accounting(episode.public)
    validate_final_evidence(episode.public, episode.truth)
    event_ids = {e.event_id for e in [*episode.history.sales, *episode.history.cash_events]}
    if set(episode.provenance.event_ids) != event_ids or len(episode.provenance.event_ids) != len(event_ids):
        raise ValueError("dangling or repeated provenance events")
    invoices = {i.invoice_id: i for i in episode.clean.invoices}
    payments = {p.payment_id: p for p in episode.clean.payments}
    for sale in episode.history.sales:
        invoice = invoices.get(sale.invoice_id)
        if invoice is None or invoice.doc_id != sale.doc_id or invoice.entity_id != sale.entity_id:
            raise ValueError("dangling sale history")
    for event in episode.history.cash_events:
        payment = payments.get(event.payment_id)
        if payment is None or event.invoice_id not in invoices or payment.doc_id != event.doc_id:
            raise ValueError("dangling payment history")
        if event.original_payment_id != payment.original_payment_id:
            raise ValueError("dangling refund history")
    rows = {r.row_id: r.model_dump(mode="json") for r in episode.clean.ledger}
    for mutation in episode.provenance.mutations:
        if mutation.event_id not in event_ids or mutation.field != "ledger_row" or len(mutation.object_ids) != 1:
            raise ValueError("unsupported or dangling mutation")
        row_id, = mutation.object_ids
        before = json.loads(mutation.clean_value) if mutation.clean_value is not None else None
        after = json.loads(mutation.observed_value) if mutation.observed_value is not None else None
        if before is not None and before["row_id"] != row_id or after is not None and after["row_id"] != row_id:
            raise ValueError("mutation payload ID mismatch")
        if rows.pop(row_id, None) != before:
            raise ValueError("mutation clean value mismatch")
        if after is not None:
            rows[row_id] = after
    if rows != {r.row_id: r.model_dump(mode="json") for r in episode.public.ledger}:
        raise ValueError("provenance does not reproduce final ledger")
    journals = {r.journal_id for r in episode.public.ledger}
    if any(d.event_id not in event_ids or d.journal_id not in journals for d in episode.history.fx_decisions):
        raise ValueError("dangling FX history")
    return episode


def load_episode(public_directory, evaluator_directory):
    """Trusted host-side loader. Neither directory is exposed to an ordinary policy."""
    private = Path(evaluator_directory)
    episode = GeneratedEpisode(
        public=load_public(Path(public_directory)),
        clean=read_json(private / "clean.json", PublicEpisode),
        truth=read_json(private / "truth.json", Truth),
        provenance=read_json(private / "provenance.json", Provenance),
        history=read_json(private / "history.json", History),
    )
    return validate_episode(episode)


def _write_expected(path, data, *, private=False, check=False):
    """Idempotent export: verify existing bytes; never overwrite different artifacts."""
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"export differs: {path}")
    elif check:
        raise ValueError(f"missing export: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o755)
        with path.open("xb") as stream:
            stream.write(data)
    if not check:
        path.chmod(0o600 if private else 0o444)


def export_dataset(plan, root=Path("."), *, check=False):
    """Exactly ten public train and ten dev episodes, with separate evaluator trees."""
    root = Path(root)
    generated = {split: [generate_episode(s.seed, s.generator) for s in getattr(plan, split)]
                 for split in ("train", "dev")}
    ids = [e.public.manifest.episode_id for values in generated.values() for e in values]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate split episode IDs")
    manifest = {"version": DATASET_VERSION, "plan_sha256": digest(plan.model_dump(mode="json")), "splits": {}}
    for split, episodes in generated.items():
        expected_ids = {e.public.manifest.episode_id for e in episodes}
        directory = root / "episodes" / split
        if directory.exists() and {p.name for p in directory.iterdir()} - expected_ids:
            raise ValueError(f"unexpected {split} export entries")
        manifest["splits"][split] = []
        for index, (spec, episode) in enumerate(zip(getattr(plan, split), episodes)):
            validate_episode(episode)
            episode_id = episode.public.manifest.episode_id
            public = directory / episode_id
            private = root / "evaluator/stage10" / split / episode_id
            if public.exists() and {p.name for p in public.iterdir()} - PUBLIC_FILES:
                raise ValueError("unexpected public export files")
            if private.exists() and {p.name for p in private.iterdir()} - PRIVATE_FILES:
                raise ValueError("unexpected evaluator export files")
            with tempfile.TemporaryDirectory(prefix="audit-export-") as temporary:
                staging = Path(temporary)
                save_public(staging, episode.public)
                for path in sorted(staging.iterdir()):
                    _write_expected(public / path.name, path.read_bytes(), check=check)
            for name in ("truth", "provenance", "history", "clean"):
                data = (getattr(episode, name).model_dump_json(indent=2) + "\n").encode()
                _write_expected(private / f"{name}.json", data, private=True, check=check)
            manifest["splits"][split].append({
                "episode_id": episode_id, "seed": spec.seed, "config_index": index,
                "public_path": public.relative_to(root).as_posix(),
                "public_sha256": digest(episode.public.model_dump(mode="json")),
                "ledger_rows": len(episode.public.ledger),
                "documents": episode.public.manifest.document_count,
            })
    path = root / "episodes/split-manifest.json"
    _write_expected(path, (json.dumps(manifest, indent=2) + "\n").encode(), check=check)
    return manifest


def paired_report(plan):
    rows = []
    for index, spec in enumerate(plan.rehearsal):
        episode = generate_episode(spec.seed, spec.generator)
        repeated = generate_episode(spec.seed, spec.generator)
        validate_episode(episode)
        validate_episode(transform_episode(episode, 40_000 + index)[0])
        row = check_pair(episode, 40_000 + index, duplicate=repeated)
        row["source_seed"] = spec.seed
        rows.append(row)
    return {"version": REPLAY_VERSION, "transform_version": TRANSFORM_VERSION,
            "plan_sha256": digest(plan.model_dump(mode="json")),
            "pair_count": len(rows), "passed": all(row["passed"] for row in rows),
            "clean_pairs": sum(row["issue_count"] == 0 for row in rows),
            "interacting_pairs": sum(any(scenario is not None and scenario.variant == "both"
                                          for scenario in (spec.generator.boundary_scenario,
                                                           spec.generator.duplicate_fx_scenario))
                                     for spec in plan.rehearsal),
            "pairs": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--root", type=Path, default=Path("."), help="dataset root")
    parser.add_argument("--check", action="store_true", help="verify existing files without writes")
    parser.add_argument("--paired-report", type=Path, help="also verify 20 rehearsal pairs and save JSON")
    args = parser.parse_args()
    plan = load_plan(args.plan)
    manifest = export_dataset(plan, args.root, check=args.check)
    print(json.dumps({"version": DATASET_VERSION, "train": len(manifest["splits"]["train"]),
                      "dev": len(manifest["splits"]["dev"]), "checked": args.check}))
    if args.paired_report:
        report = paired_report(plan)
        _write_expected(args.paired_report, (json.dumps(report, indent=2) + "\n").encode(), private=True)
        print(json.dumps({"pairs": report["pair_count"], "passed": report["passed"],
                          "clean_pairs": report["clean_pairs"]}))


if __name__ == "__main__":
    main()
