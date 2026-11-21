"""Replay, complete reference remapping, dataset separation and paired checks."""

import copy
import json
from pathlib import Path
import random

import pytest

from audit_env.baselines import POLICIES, run_baseline, run_local_policy
from audit_env.datasets import (
    DatasetPlan, PRIVATE_FILES, PUBLIC_FILES, export_dataset, load_episode,
    load_plan, paired_report, validate_episode,
)
from audit_env.environment import AuditEnvironment, FIXTURE_ROOT
from audit_env.generation import CashEvent, GeneratedEpisode, GeneratorConfig, History, SaleEvent, generate_episode
from audit_env.isolation import run_isolated_fixture
from audit_env.replay import check_pair, digest, oracle_action, replay_actions, verify_capture
from audit_env.schemas import Provenance, Submission, Truth
from audit_env.serialization import load_public, read_json
from audit_env.transformations import id_mapping, remap_ids, transform_episode
from audit_env.views import settlement_view
from test_stage05 import require_linux


ROOT = Path(__file__).resolve().parent.parent


def hand_episode():
    """Use the independent Stage 02 fixture, not generator-computed expectations."""
    public = load_public(FIXTURE_ROOT / "company-b/public")
    clean_data = load_public(FIXTURE_ROOT / "company-a/public").model_dump(mode="json")
    clean_data["manifest"]["episode_id"] = public.manifest.episode_id
    from audit_env.schemas import PublicEpisode

    clean = PublicEpisode.model_validate_json(json.dumps(clean_data))
    invoice, = public.invoices
    payment, = public.payments
    history = History(version="stage06-v1", seed=0, config=GeneratorConfig(),
                      sales=[SaleEvent(event_id="event-248", invoice_id=invoice.invoice_id,
                                       doc_id=invoice.doc_id, entity_id=invoice.entity_id,
                                       timestamp=invoice.service_at, currency="KZT", amount_minor=10_000_000,
                                       description=invoice.line_items[0].description)],
                      cash_events=[CashEvent(event_id="event-569", payment_id=payment.payment_id,
                                             doc_id=payment.doc_id, invoice_id=invoice.invoice_id,
                                             timestamp=payment.timestamp, currency="KZT", amount_minor=7_000_000,
                                             transaction_kind="receipt", original_payment_id=None)])
    return GeneratedEpisode(public=public, clean=clean, history=history,
                            truth=read_json(FIXTURE_ROOT / "company-b/private/truth.json", Truth),
                            provenance=read_json(FIXTURE_ROOT / "company-b/private/provenance.json", Provenance))


@pytest.fixture(scope="module")
def report():
    return paired_report(load_plan())


def test_hand_renaming_preserves_two_million_gap_and_four_inspection_score():
    episode = hand_episode()
    mapping = id_mapping(episode, 71)
    mapping["pay-627"] = "payment-renamed"
    mapping["settlement:pay-627"] = "settlement:payment-renamed"
    transformed, _ = transform_episode(episode, 71, mapping=mapping)
    before = run_local_policy("reconciliation", episode=episode)
    after = run_local_policy("reconciliation", episode=transformed)
    source, = before["private_result"]["submission"]["findings"]
    target, = after["private_result"]["submission"]["findings"]
    assert source["claimed_amount_minor"] == target["claimed_amount_minor"] == 2_000_000
    assert target["affected_ids"] == ["payment-renamed", mapping["inv-264"]]
    assert target["evidence_ids"] == [mapping["doc-492"], "settlement:payment-renamed"]
    assert before["private_result"]["inspection_steps"] == after["private_result"]["inspection_steps"] == 4
    assert before["private_result"]["return"] == after["private_result"]["return"] == .992
    assert check_pair(episode, 71)["passed"]


def test_bijective_remapping_covers_refunds_histories_and_embedded_mutation_rows():
    config = load_plan().rehearsal[-1]
    episode = generate_episode(config.seed, config.generator)
    snapshot = episode.model_dump_json()
    state = random.getstate()
    transformed, mapping = transform_episode(episode, 88)
    assert episode.model_dump_json() == snapshot and random.getstate() == state
    assert len(mapping) == len(set(mapping.values()))
    assert all(mapping[row.evidence_id] == row.evidence_id for row in episode.public.fx)
    validate_episode(transformed)
    assert transformed == transform_episode(episode, 88)[0]
    assert transformed != transform_episode(episode, 89)[0]
    invoice_ids = {i.invoice_id for i in transformed.public.invoices}
    payment_ids = {p.payment_id for p in transformed.public.payments}
    for payment in transformed.public.payments:
        assert all(ref.invoice_id in invoice_ids for ref in payment.invoice_refs)
        assert payment.original_payment_id is None or payment.original_payment_id in payment_ids
    for old, new in zip(episode.provenance.mutations, transformed.provenance.mutations):
        assert new.event_id == mapping[old.event_id]
        assert new.object_ids == [mapping[value] for value in old.object_ids]
        for name in ("clean_value", "observed_value"):
            a, b = getattr(old, name), getattr(new, name)
            if a is not None:
                assert json.loads(b) == remap_ids(json.loads(a), mapping)
    # Without benign name/order changes, applying the inverse mapping restores
    # every public and private field, including the serialized row payloads.
    renamed, _ = transform_episode(episode, 88, rename=False, reorder=False)
    inverse = {new: old for old, new in mapping.items()}
    restored = GeneratedEpisode.model_validate_json(json.dumps(remap_ids(renamed.model_dump(mode="json"), inverse)))
    assert restored == episode


@pytest.mark.parametrize("damage", ["collision", "missing", "settlement", "fx"])
def test_reject_nonbijective_incomplete_or_inconsistent_maps(damage):
    spec = load_plan().rehearsal[-1]
    episode = generate_episode(spec.seed, spec.generator)
    mapping = id_mapping(episode, 1)
    if damage == "collision":
        keys = [key for key in mapping if not key.startswith(("settlement:", "fx:"))]
        mapping[keys[1]] = mapping[keys[0]]
    elif damage == "missing":
        del mapping[episode.truth.issues[0].issue_id]
    elif damage == "settlement":
        mapping[next(key for key in mapping if key.startswith("settlement:"))] = "settlement:wrong"
    else:
        mapping[next(key for key in mapping if key.startswith("fx:"))] = "fx:wrong"
    with pytest.raises(ValueError):
        transform_episode(episode, 1, mapping=mapping)


def test_recomputed_public_settlement_summaries_update_all_nested_ids():
    spec = load_plan().rehearsal[-1]
    episode = generate_episode(spec.seed, spec.generator)
    transformed, mapping = transform_episode(episode, 55)
    for old_payment in episode.public.payments:
        new_payment = next(p for p in transformed.public.payments if p.payment_id == mapping[old_payment.payment_id])
        expected = remap_ids(settlement_view(old_payment, episode.public.ledger).model_dump(mode="json"), mapping)
        actual = settlement_view(new_payment, transformed.public.ledger).model_dump(mode="json")
        for summary in (expected, actual):
            summary["ledger_row_ids"].sort()
            for allocation in summary["allocations"]:
                allocation["ledger_row_ids"].sort()
            summary["allocations"].sort(key=lambda item: item["invoice_id"])
        assert actual == expected


@pytest.mark.parametrize("mode", ["open", "closed"])
def test_identical_version_seed_config_actions_reproduce_public_records_flags_and_return(mode):
    spec = load_plan().rehearsal[-1]
    a = generate_episode(spec.seed, spec.generator)
    b = generate_episode(spec.seed, spec.generator)
    assert a.public.model_dump_json() == b.public.model_dump_json()
    actions = [
        {"type": "list_records", "table": "ledger", "cursor": None, "limit": 50},
        {"type": "list_records", "table": "ledger", "cursor": "ledger:50", "limit": 50},
        {"type": "get_record", "table": "invoices", "id": a.public.invoices[0].invoice_id},
        {"type": "get_document", "doc_id": a.public.payments[0].doc_id},
        {"type": "calculator", "expression": "1/0"},
        {"type": "get_document", "doc_id": "unknown-id"}, oracle_action(a),
    ]
    left, right = replay_actions(a, actions, mode=mode), replay_actions(b, actions, mode=mode)
    assert left == right and left["private_result"]["score"]["score"] == .988
    assert left["trajectory"][-1]["reward"] == (0 if mode == "closed" else .988)
    assert left["trajectory"][-1]["terminated"] and not left["trajectory"][-1]["truncated"]
    assert left["trajectory"][4]["observation"]["error"] == "CALCULATOR_ERROR"


def test_replay_truncation_malformed_submit_and_no_post_terminal_actions():
    episode = hand_episode()
    inspections = [{"type": "calculator", "expression": "1+2"}] * 100
    result = replay_actions(episode, inspections)
    assert result["trajectory"][-1]["truncated"] and result["private_result"]["actions"] == 100
    assert result == replay_actions(episode, inspections)
    timeout = replay_actions(episode, [inspections[0], None])
    assert timeout["private_result"]["actions"] == 1 and timeout["trajectory"][-1]["truncated"]
    malformed = replay_actions(episode, [{"type": "submit", "findings": {}}])
    assert malformed["private_result"]["score"]["score"] == -1
    assert malformed["trajectory"][-1]["terminated"]
    with pytest.raises(ValueError, match="after termination"):
        replay_actions(episode, [oracle_action(episode), inspections[0]])


def test_retained_stage09_captures_replay_and_corruption_is_detected():
    episode = hand_episode()
    directory = ROOT / "episodes/examples/stage09/company-b"
    for name in POLICIES:
        capture = [json.loads(line) for line in (directory / name / "trajectories.jsonl").read_text(encoding="utf-8").splitlines()]
        assert verify_capture(episode, capture)["actions"] == len(capture) - 1
    timeout = [json.loads(line) for line in (ROOT / "episodes/examples/stage09/timeout/trajectories.jsonl").read_text(encoding="utf-8").splitlines()]
    assert verify_capture(episode, timeout)["actions"] == 0
    corrupted = copy.deepcopy(capture)
    corrupted[1]["reward"] = 123
    with pytest.raises(ValueError, match="response mismatch"):
        verify_capture(episode, corrupted)


def test_twenty_pairs_preserve_oracle_answers_scores_and_clean_controls(report):
    assert report["passed"] and report["pair_count"] == len(report["pairs"]) == 20
    assert report["clean_pairs"] == report["interacting_pairs"] == 5
    assert len({r["episode_id"] for r in report["pairs"]}) == 20
    assert len({r["transformed_episode_id"] for r in report["pairs"]}) == 20
    for row in report["pairs"]:
        assert row["passed"] and row["source_return"] == row["transformed_return"] == .992
        assert row["replay_sha256"] == row["repeated_replay_sha256"]
        assert row["public_sha256"] != row["transformed_public_sha256"]
        assert row["inspection_steps"] == 4 and row["total_actions"] == 5
        assert row["reconciliation_actions"] <= 100
    assert max(row["issue_count"] for row in report["pairs"]) == 12


def test_names_and_row_order_change_without_creating_clean_issues():
    spec = load_plan().rehearsal[0]
    episode = generate_episode(spec.seed, spec.generator)
    changed, mapping = transform_episode(episode, 99)
    assert episode.truth.issues == changed.truth.issues == []
    for table, key in (("ledger", "row_id"), ("invoices", "invoice_id"), ("payments", "payment_id")):
        assert [mapping[getattr(r, key)] for r in getattr(episode.public, table)] != [getattr(r, key) for r in getattr(changed.public, table)]
    old = {mapping[i.invoice_id]: i.line_items[0].description for i in episode.public.invoices}
    assert all(i.line_items[0].description != old[i.invoice_id] for i in changed.public.invoices)
    result = run_local_policy("reconciliation", episode=changed)
    assert result["private_result"]["submission"]["findings"] == []


@pytest.mark.parametrize("overlap", ["seed", "config", "count"])
def test_split_plan_rejects_overlap_and_wrong_counts(overlap):
    data = load_plan().model_dump(mode="json")
    if overlap == "seed":
        data["dev"][0]["seed"] = data["train"][0]["seed"]
    elif overlap == "config":
        data["dev"][0]["generator"] = data["train"][0]["generator"]
    else:
        data["train"].pop()
    with pytest.raises(ValueError):
        DatasetPlan.model_validate_json(json.dumps(data))


def test_delivered_exports_exact_counts_disjoint_inputs_and_family_coverage():
    plan = load_plan()
    manifest = json.loads((ROOT / "episodes/split-manifest.json").read_text())
    assert manifest["plan_sha256"] == digest(plan.model_dump(mode="json"))
    seeds, ids, mixes = set(), set(), set()
    for split in ("train", "dev"):
        entries = manifest["splits"][split]
        assert len(entries) == len(list((ROOT / "episodes" / split).iterdir())) == 10
        families, counts = set(), []
        for spec, row in zip(getattr(plan, split), entries):
            assert spec.seed not in seeds and row["episode_id"] not in ids
            assert spec.generator.model_dump_json() not in mixes
            seeds.add(spec.seed); ids.add(row["episode_id"]); mixes.add(spec.generator.model_dump_json())
            public = ROOT / row["public_path"]
            private = ROOT / "evaluator/stage10" / split / row["episode_id"]
            assert {p.name for p in public.iterdir()} == PUBLIC_FILES
            assert all(b"\r\n" not in p.read_bytes() for p in public.iterdir())
            assert {p.name for p in private.iterdir()} == PRIVATE_FILES
            episode = load_episode(public, private)
            assert row["public_sha256"] == digest(episode.public.model_dump(mode="json"))
            assert 200 <= row["ledger_rows"] <= 2000 and 20 <= row["documents"] <= 200
            families.update(t.type for t in episode.truth.issues)
            counts.append(len(episode.truth.issues))
        assert families == {"duplicate_invoice", "payment_allocation", "fx_conversion", "period_cutoff"}
        assert 0 in counts and 1 in counts and 12 in counts
    assert all(s.seed not in seeds and s.generator.model_dump_json() not in mixes for s in plan.rehearsal)


def test_export_is_idempotent_and_rejects_stale_or_corrupt_files(tmp_path):
    plan = load_plan()
    first = export_dataset(plan, tmp_path)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert export_dataset(plan, tmp_path, check=True) == first
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    row = first["splits"]["train"][0]
    path = tmp_path / row["public_path"] / "ledger.csv"
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b"corruption\n")
    with pytest.raises(ValueError, match="export differs"):
        export_dataset(plan, tmp_path, check=True)
    assert path.read_bytes().endswith(b"corruption\n")


def test_corrupted_private_history_is_rejected_without_repairing_fixture():
    spec = load_plan().rehearsal[-1]
    episode, _ = transform_episode(generate_episode(spec.seed, spec.generator), 44)
    bad = episode.provenance.mutations[0].model_copy(update={"object_ids": ["guessed-row"]})
    damaged = episode.model_copy(update={"provenance": episode.provenance.model_copy(update={
        "mutations": [bad, *episode.provenance.mutations[1:]]})})
    with pytest.raises(ValueError, match="payload ID"):
        validate_episode(damaged)
    validate_episode(episode)


def test_linux_loaded_and_transformed_episode_policy_boundary(tmp_path):
    require_linux()
    plan = load_plan()
    for spec in (plan.rehearsal[0], plan.rehearsal[-1]):
        transformed, _ = transform_episode(generate_episode(spec.seed, spec.generator), 901)
        for name in POLICIES:
            actual = run_baseline(name, episode=transformed)
            local = run_local_policy(name, episode=transformed)
            assert actual["trajectory"] == local["trajectory"]
            assert actual["private_result"]["score"] == local["private_result"]["score"]
            if name != "oracle":
                assert actual["private_result"]["agent_uid"] == 65534 and actual["private_result"]["agent_reaped"]


def test_linux_exported_evaluator_and_inputs_are_inaccessible(tmp_path):
    require_linux()
    manifest = json.loads((ROOT / "episodes/split-manifest.json").read_text())
    row = manifest["splits"]["dev"][-1]
    private = ROOT / "evaluator/stage10/dev" / row["episode_id"]
    public = ROOT / row["public_path"]
    episode = load_episode(public, private)
    assert private.stat().st_mode & 0o077 == 0
    assert all(p.stat().st_mode & 0o077 == 0 for p in private.iterdir())
    sentinel = tmp_path / "private-sentinel"
    sentinel.write_text("PRIVATE-STAGE10-SENTINEL")
    sentinel.chmod(0o600)
    paths = [str(private / "truth.json"), str(private / "history.json"), str(public / "ledger.csv"),
             str(ROOT / "configs/stage10-splits.json"), str(sentinel)]
    probe = tmp_path / "probe.py"
    probe.write_text('''import json,sys
for path in PATHS:
    for mode in ("r","w"):
        try:
            open(path,mode)
        except OSError:
            pass
        else:
            raise AssertionError("unexpected exported data access")
initial=json.loads(sys.stdin.readline())["observation"]
print(json.dumps({"type":"submit","findings":{"episode_id":initial["manifest"]["episode_id"],"findings":[]}}),flush=True)
assert json.loads(sys.stdin.readline())["reward"]==0
'''.replace("PATHS", repr(paths)))
    result = run_isolated_fixture(episode=episode, policy_path=probe)
    assert result["private_result"]["reason"] == "completed" and result["private_result"]["agent_reaped"]
    assert "PRIVATE-STAGE10-SENTINEL" not in json.dumps(result)
    assert sentinel.read_text() == "PRIVATE-STAGE10-SENTINEL"
