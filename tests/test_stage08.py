"""Hand calculations, controlled interactions, scale and final proof discovery."""

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import random

import pytest

from audit_env.composition import scenario_variants
from audit_env.environment import AuditEnvironment
from audit_env.generation import GeneratorConfig, generate_episode, save_generated, validate_accounting
from audit_env.isolation import run_isolated_generated
from audit_env.schemas import PublicEpisode
from audit_env.serialization import load_public
from audit_env.validation import discovery_action_bound, reconstruct_findings, validate_final_evidence
from test_stage05 import require_linux


def config(name):
    return json.loads(Path(f"configs/stage08-{name}.json").read_text())


@pytest.mark.parametrize("scenario", ["boundary", "duplicate_fx"])
def test_four_controlled_variants_have_identical_clean_business_and_independent_sides(scenario):
    variants = scenario_variants(8, config("boundary" if scenario == "boundary" else "duplicate-fx"), scenario)
    controls = variants["clean"].clean
    expected_types = ("payment_allocation", "period_cutoff") if scenario == "boundary" else ("duplicate_invoice", "fx_conversion")
    for variant, episode in variants.items():
        assert episode.clean.ledger == controls.ledger
        assert episode.clean.invoices == controls.invoices
        assert episode.clean.payments == controls.payments
        assert episode.clean.fx == controls.fx
        wanted = [] if variant == "clean" else list(expected_types) if variant == "both" else [expected_types[0 if variant == "a_only" else 1]]
        assert Counter(t.type for t in episode.truth.issues) == Counter(wanted)
        assert reconstruct_findings(episode.clean) == []
        validate_final_evidence(episode.public, episode.truth)
        discover_and_submit(8, episode.history.config.model_dump(mode="json"))
    assert len({g.public.manifest.episode_id for g in variants.values()}) == 4


def test_usd_100_duplicate_49000_and_fx_1000_use_distinct_canonical_targets():
    g = generate_episode(8, config("duplicate-fx"))
    duplicate, fx = g.truth.issues
    assert duplicate.type == "duplicate_invoice" and duplicate.expected_amount_minor == 4_900_000
    assert fx.type == "fx_conversion" and fx.expected_amount_minor == 100_000
    invoice = next(i for i in g.public.invoices if i.invoice_id in duplicate.affected_ids)
    assert invoice.currency == "USD" and invoice.total_minor == 10000
    rows = sorted((r for r in g.public.ledger if r.invoice_id == invoice.invoice_id and r.account == "revenue"), key=lambda r: r.posting_sequence)
    assert [r.credit_minor for r in rows] == [5_000_000, 4_900_000]
    assert duplicate.affected_ids == [invoice.invoice_id]
    assert fx.affected_ids == [rows[1].journal_id]
    assert duplicate.affected_ids != fx.affected_ids
    required = next(r for r in g.public.fx if r.evidence_id in fx.evidence_sets[0])
    assert str(required.rate) == "500"
    # Both legs are balanced, and duplicate amount counts the extra revenue once.
    for row in rows:
        legs = [r for r in g.public.ledger if r.journal_id == row.journal_id]
        assert len(legs) == 2 and sum(r.debit_minor for r in legs) == sum(r.credit_minor for r in legs) == row.credit_minor
    assert sum(t.expected_amount_minor for t in g.truth.issues) == 5_000_000
    assert sum(r.credit_minor for r in rows) == 9_900_000  # These are different quantities.
    decision, = g.history.fx_decisions
    assert decision.journal_id == rows[1].journal_id and str(decision.used_rate) == "490.00"


def test_boundary_underapplication_and_mistiming_use_final_rows_and_payment_date():
    variants = scenario_variants(8, config("boundary"), "boundary")
    g = variants["both"]
    allocation, cutoff = g.truth.issues
    payment = next(p for p in g.public.payments if p.payment_id in allocation.affected_ids)
    assert payment.currency == "USD" and payment.amount_minor == 5000  # USD 50.
    assert payment.timestamp.isoformat() == "2026-11-30T23:30:00+05:00"
    assert payment.invoice_refs[0].amount_minor == 5000
    row, = [r for r in g.public.ledger if r.journal_id in cutoff.affected_ids and r.account == "receivables"]
    assert row.timestamp.isoformat() == "2026-12-01T00:00:00+05:00"
    assert row.credit_minor == 2_300_000  # 50 * 500 = 25,000 KZT; apply 23,000.
    assert allocation.expected_amount_minor == 200_000
    assert cutoff.expected_amount_minor == 2_300_000
    assert allocation.affected_ids == [payment.payment_id, row.invoice_id]
    assert cutoff.affected_ids == [row.journal_id]
    assert f"fx:2026-11-30:USD:KZT" in allocation.evidence_sets[0]
    assert variants["a_only"].truth.issues[0].expected_amount_minor == 200_000
    assert variants["b_only"].truth.issues[0].expected_amount_minor == 2_500_000
    assert [r for r in g.public.ledger if r.payment_id == payment.payment_id and r.account == "cash"][0].debit_minor == 2_500_000


@pytest.mark.parametrize("profile,n,issues,rows,documents", [
    ("small-clean", 36, 0, 224, 74), ("small-mixed", 36, 12, 226, 74),
    ("large-clean", 96, 0, 584, 194), ("large-mixed", 96, 12, 586, 194),
])
def test_size_profiles_actual_counts_balanced_books_and_exact_family_counts(profile, n, issues, rows, documents):
    g = generate_episode(8, config(profile))
    assert len(g.public.invoices) == n and len(g.public.ledger) == rows
    assert g.public.manifest.document_count == documents
    assert g.public.manifest.record_count == sum(map(len, (g.public.ledger, g.public.invoices, g.public.payments, g.public.fx)))
    assert 200 <= rows <= 2000 and 20 <= documents <= 200
    assert len(g.truth.issues) == issues
    validate_accounting(g.clean, clean=True)
    validate_accounting(g.public)
    if issues:
        assert Counter(t.type for t in g.truth.issues) == {"duplicate_invoice": 2, "payment_allocation": 3, "fx_conversion": 3, "period_cutoff": 4}
    assert all(1 <= len(proof) <= 10 for t in g.truth.issues for proof in t.evidence_sets)


def discover_and_submit(seed, values):
    """Only reset/tools supply the public company; neither truth nor history read."""
    env = AuditEnvironment()
    initial, info = env.reset(seed=seed, config={"generator": values, "mode": "open"})
    assert info == {}
    data, returned = {}, set()
    for table in ("ledger", "invoices", "payments", "fx"):
        cursor, data[table] = None, []
        while True:
            observation, reward, terminated, truncated, _ = env.step({"type": "list_records", "table": table, "cursor": cursor, "limit": 50})
            assert reward == 0 and not terminated and not truncated
            page = observation["result"]
            for item in page["rows"]:
                data[table].append(item["record"])
                returned.add(item["id"])
                if table in ("invoices", "payments"):
                    returned.add(item["record"]["doc_id"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
    public = PublicEpisode.model_validate({"manifest": initial["manifest"], "policy": initial["policy"], **data})
    findings = reconstruct_findings(public)
    # Only payments found discrepant by listed rows need a completeness view.
    inspected = set()
    for finding in findings:
        if finding.type != "payment_allocation":
            continue
        payment = next(p for p in public.payments if p.payment_id in finding.affected_ids)
        if payment.payment_id not in inspected:
            document = env.step({"type": "get_document", "doc_id": payment.doc_id})[0]["result"]
            returned.add(document["settlement"]["evidence_id"])
            assert document["settlement"]["applied_minor"] == sum(
                r.credit_minor - r.debit_minor for r in public.ledger if r.payment_id == payment.payment_id
                and r.account == "receivables" and r.entry_kind == "allocation")
            inspected.add(payment.payment_id)
    assert all(set(f.evidence_ids) <= returned for f in findings)
    result = env.step({"type": "submit", "findings": {"episode_id": initial["manifest"]["episode_id"],
                                                       "findings": [f.model_dump(mode="json") for f in findings]}})
    assert env.action_count == discovery_action_bound(public) <= 100
    assert result[2] and not result[3]
    assert env._last_scoring_result.fp == env._last_scoring_result.fn == 0
    assert env._last_scoring_result.tp == len(findings)
    assert result[1] == pytest.approx(1 - .002 * (env.action_count - 1))
    return env.action_count


@pytest.mark.parametrize("profile,actions", [("boundary", 7), ("duplicate-fx", 6), ("small-clean", 10),
                                              ("small-mixed", 13), ("large-clean", 19), ("large-mixed", 22)])
def test_public_proof_discovery_and_submit_within_100_actions(profile, actions):
    assert discover_and_submit(8, config(profile)) == actions


def test_maximum_document_count_and_allocation_limits_still_fit_budget():
    values = {**config("large-mixed"), "invoice_count": 99}
    g = generate_episode(8, values)
    assert g.public.manifest.document_count == 200
    assert len(g.public.ledger) == 604
    assert discover_and_submit(8, values) <= 30


@pytest.mark.parametrize("seed", [0, 1, 17, 42, 2147483647])
@pytest.mark.parametrize("profile", ["small-clean", "small-mixed", "large-mixed"])
def test_seeds_vary_amounts_names_patterns_and_order_without_label_hints(seed, profile):
    values = config(profile)
    a, b = generate_episode(seed, values), generate_episode(seed + 1, values)
    validate_final_evidence(a.public, a.truth)
    assert {i.doc_id for i in a.public.invoices}.isdisjoint(i.doc_id for i in b.public.invoices)
    assert [i.total_minor for i in a.public.invoices] != [i.total_minor for i in b.public.invoices]
    assert {i.line_items[0].description for i in a.public.invoices} != {i.line_items[0].description for i in b.public.invoices}
    assert a.public.invoices != sorted(a.public.invoices, key=lambda i: i.service_at)
    first, second = a.history.sales[:2]
    assert (first.currency, first.amount_minor, first.entity_id) == (second.currency, second.amount_minor, second.entity_id)
    grouped = defaultdict(list)
    for payment in a.public.payments:
        if payment.transaction_kind == "receipt":
            grouped[payment.invoice_refs[0].invoice_id].append(payment)
    assert any(len(payments) == 2 for payments in grouped.values())
    assert any(p.transaction_kind == "refund" for p in a.public.payments)
    ratios = set()
    by_id = {i.invoice_id: i for i in a.public.invoices}
    for invoice_id, payments in grouped.items():
        ratios.add(sum(p.amount_minor for p in payments) * 100 // by_id[invoice_id].total_minor)
    assert len(ratios) >= 2
    public_text = a.public.model_dump_json().lower()
    for hidden in ("stage08", "scenario", "a_only", "b_only", "mutation", "issue-", "truth", "provenance"):
        assert hidden not in public_text


def test_replay_serialization_provenance_reconstructs_and_reverses_final_interactions(tmp_path):
    state = random.getstate()
    values = config("small-mixed")
    a, b = generate_episode(8, values), generate_episode(8, values)
    assert random.getstate() == state and a == b
    for name, episode in (("a", a), ("b", b)):
        save_generated(tmp_path / name, episode)
    files = [p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*") if p.is_file()]
    assert len(files) == 10
    for path in files:
        assert (tmp_path / "a" / path).read_bytes() == (tmp_path / "b" / path).read_bytes()
    assert load_public(tmp_path / "a/public") == a.public
    records = {r.row_id: r.model_dump(mode="json") for r in a.clean.ledger}
    events = {s.event_id for s in a.history.sales} | {p.event_id for p in a.history.cash_events}
    for m in a.provenance.mutations:
        assert m.event_id in events
        key, = m.object_ids
        assert records.pop(key, None) == (json.loads(m.clean_value) if m.clean_value else None)
        if m.observed_value:
            records[key] = json.loads(m.observed_value)
    assert records == {r.row_id: r.model_dump(mode="json") for r in a.public.ledger}
    for m in reversed(a.provenance.mutations):
        key, = m.object_ids
        assert records.pop(key, None) == (json.loads(m.observed_value) if m.observed_value else None)
        if m.clean_value:
            records[key] = json.loads(m.clean_value)
    assert records == {r.row_id: r.model_dump(mode="json") for r in a.clean.ledger}


@pytest.mark.parametrize("corruption,error", [("amount", "amount"), ("omission", "targets"),
                                              ("target", "targets"), ("proof", "proof"), ("count", "counts")])
def test_independent_audit_rejects_deliberately_false_truth(corruption, error):
    g = generate_episode(8, config("small-mixed"))
    issues = list(g.truth.issues)
    counts = None
    if corruption == "amount":
        issues[0] = issues[0].model_copy(update={"expected_amount_minor": issues[0].expected_amount_minor + 1})
    elif corruption == "omission":
        issues.pop()
    elif corruption == "target":
        issues[0] = issues[0].model_copy(update={"affected_ids": ["guessed-object"]})
    elif corruption == "proof":
        issues[0] = issues[0].model_copy(update={"evidence_sets": [[g.public.invoices[0].doc_id]]})
    else:
        counts = {"duplicate_invoice": 1}
    with pytest.raises(ValueError, match=error):
        validate_final_evidence(g.public, g.truth.model_copy(update={"issues": issues}), counts)


def test_independent_audit_detects_balanced_final_row_change_after_truth_was_built():
    g = generate_episode(8, config("duplicate-fx"))
    journal_id = next(t.affected_ids[0] for t in g.truth.issues if t.type == "fx_conversion")
    rows = [r.model_copy(update={"credit_minor": r.credit_minor + 1 if r.credit_minor else 0,
                                 "debit_minor": r.debit_minor + 1 if r.debit_minor else 0})
            if r.journal_id == journal_id else r for r in g.public.ledger]
    changed = g.public.model_copy(update={"ledger": rows})
    validate_accounting(changed)
    with pytest.raises(ValueError, match="amount"):
        validate_final_evidence(changed, g.truth)


@pytest.mark.parametrize("extra", [
    {"invoice_count": 3}, {"invoice_count": 100}, {"invoice_count": 4, "size_profile": "small"},
    {"invoice_count": 32, "size_profile": "small", "missing_allocations": 1},
    {"boundary_scenario": {"variant": "both"}}, {"duplicate_fx_scenario": {"variant": "both"}},
    {"boundary_scenario": {"count": True}}, {"misplaced_applications": True},
    {"currencies": ["KZT"], "partial_allocations": 1, "misplaced_applications": 1, "boundary_scenario": {"variant": "both"}},
    {"currencies": ["KZT"], "duplicate_invoices": 1, "wrong_fx_rates": 1, "duplicate_fx_scenario": {"variant": "both"}},
    {"partial_allocations": 6, "misplaced_applications": 6, "duplicate_invoices": 1},
    {"invoice_count": 4, "currencies": ["USD"], "boundary_scenario": {"count": 3, "variant": "clean"},
     "duplicate_fx_scenario": {"count": 3, "variant": "clean"}},
    {"fx_profile": "flat", "wrong_fx_dates": 1},
    {"version": "stage07-v1", "boundary_scenario": {"variant": "clean"}},
])
def test_invalid_impossible_or_undersized_profiles_fail_before_export(extra):
    with pytest.raises(ValueError):
        generate_episode(8, {"version": "stage08-v1", **extra})


def test_multiple_interaction_pairs_consume_exactly_twelve_family_counts():
    values = {**config("boundary"), "boundary_scenario": {"count": 3, "variant": "both"},
              "duplicate_fx_scenario": {"count": 3, "variant": "both"},
              "partial_allocations": 3, "misplaced_applications": 3, "duplicate_invoices": 3, "wrong_fx_rates": 3}
    g = generate_episode(8, values)
    assert Counter(t.type for t in g.truth.issues) == dict.fromkeys(("payment_allocation", "period_cutoff", "duplicate_invoice", "fx_conversion"), 3)
    assert len(g.truth.issues) == 12
    validate_final_evidence(g.public, g.truth)


def test_linux_scenarios_and_scale_use_public_tools_and_preserve_closed_rewards():
    require_linux()
    cases = [(name, config(name), issues) for name, issues in (
        ("small-clean", 0), ("small-mixed", 12), ("large-clean", 0), ("large-mixed", 12))]
    for scenario, filename in (("boundary", "boundary"), ("duplicate_fx", "duplicate-fx")):
        for variant, episode in scenario_variants(8, config(filename), scenario).items():
            cases.append((scenario + ":" + variant, episode.history.config.model_dump(mode="json"), len(episode.truth.issues)))
    for name, values, issues in cases:
        result = run_isolated_generated(8, values)
        private, trace = result["private_result"], result["trajectory"]
        assert private["reason"] == "completed" and private["agent_reaped"]
        assert private["score"]["tp"] == issues and private["score"]["fp"] == private["score"]["fn"] == 0
        assert private["actions"] <= 100 and private["score"]["f1"] == 1
        assert all(row["reward"] == 0 and row["delivered"] for row in trace)
        assert trace[-1]["terminated"] and not trace[-1]["truncated"]
        assert private["agent_uid"] == 65534 and private["evaluator_uid"] == 0
        assert not any(word in json.dumps(trace) for word in ("stage08-v1", "boundary_scenario", "duplicate_fx_scenario"))
        if name == "large-mixed":
            assert private["actions"] == 22 and private["score"]["score"] == pytest.approx(.958)
