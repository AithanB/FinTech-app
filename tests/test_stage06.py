"""Independent accounting calculations, reproducible exports and generated runs."""

from collections import Counter, defaultdict
import json
import random

import pytest

from audit_env.environment import AuditEnvironment
from audit_env.generation import GeneratorConfig, generate_episode, save_generated, validate_accounting
from audit_env.isolation import run_isolated_generated
from audit_env.schemas import Finding, LedgerRow, Provenance, Submission, Truth
from audit_env.serialization import load_public, read_json
from audit_env.views import settlement_view
from test_stage05 import require_linux


FIXED = {"amount_min_minor": 10_000_000, "amount_max_minor": 10_000_000}
MIXED = {**FIXED, "duplicate_invoices": 1, "missing_allocations": 1, "partial_allocations": 1}


def independent_findings(public):
    """Public-only reconstruction; deliberately does not call settlement_view."""
    findings = []
    for invoice in public.invoices:
        rows = sorted((r for r in public.ledger if r.invoice_id == invoice.invoice_id and r.account == "revenue" and r.entry_kind == "recognition"), key=lambda r: r.posting_sequence)
        if len(rows) > 1:
            findings.append(Finding(
                type="duplicate_invoice", affected_ids=[invoice.invoice_id],
                claimed_amount_minor=sum(r.credit_minor for r in rows[1:]), currency="KZT",
                evidence_ids=[invoice.doc_id] + [r.row_id for r in rows], explanation="Repeated recognition.",
            ))
    for payment in public.payments:
        if payment.transaction_kind == "refund":
            continue
        for ref in payment.invoice_refs:
            applied = sum(r.credit_minor - r.debit_minor for r in public.ledger
                          if r.payment_id == payment.payment_id and r.invoice_id == ref.invoice_id
                          and r.account == "receivables" and r.entry_kind == "allocation")
            if applied != ref.amount_minor:
                findings.append(Finding(
                    type="payment_allocation", affected_ids=[payment.payment_id, ref.invoice_id],
                    claimed_amount_minor=abs(ref.amount_minor - applied), currency="KZT",
                    evidence_ids=[payment.doc_id, f"settlement:{payment.payment_id}"], explanation="Directed vs applied.",
                ))
    return findings


def independently_balanced(public):
    groups = defaultdict(list)
    for row in public.ledger:
        groups[row.journal_id].append(row)
    for rows in groups.values():
        assert len(rows) == 2
        assert sum(r.debit_minor for r in rows) == sum(r.credit_minor for r in rows) > 0
        assert rows[0].currency == rows[1].currency == "KZT"
    assert sum(r.debit_minor for r in public.ledger) == sum(r.credit_minor for r in public.ledger)


@pytest.mark.parametrize("knobs,counts", [
    ({}, {}), ({"duplicate_invoices": 1}, {"duplicate_invoice": 1}),
    ({"missing_allocations": 1}, {"payment_allocation": 1}),
    ({"partial_allocations": 1}, {"payment_allocation": 1}),
    ({"duplicate_invoices": 1, "missing_allocations": 1, "partial_allocations": 1}, {"duplicate_invoice": 1, "payment_allocation": 2}),
])
def test_each_profile_has_only_its_publicly_supported_issues(knobs, counts):
    generated = generate_episode(6, {**FIXED, **knobs})
    public = generated.public
    independently_balanced(generated.clean)
    independently_balanced(public)
    assert independent_findings(generated.clean) == []
    assert Counter(f.type for f in independent_findings(public)) == counts
    assert Counter(t.type for t in generated.truth.issues) == counts
    assert public.manifest.record_count == len(public.ledger) + len(public.invoices) + len(public.payments) + len(public.fx)
    assert public.manifest.document_count == len(public.invoices) + len(public.payments) == 14
    for invoice in public.invoices:
        assert sum(line.amount_minor for line in invoice.line_items) == invoice.total_minor == 10_000_000
    # Independently reconstructed claims must match one-to-one through the real environment.
    env = AuditEnvironment()
    initial, info = env.reset(seed=6, config={"generator": {**FIXED, **knobs}, "mode": "open"})
    answer = Submission(episode_id=initial["manifest"]["episode_id"], findings=independent_findings(public))
    _, reward, terminated, truncated, _ = env.step({"type": "submit", "findings": answer.model_dump(mode="json")})
    assert info == {} and reward == 1 and terminated and not truncated
    assert env._last_scoring_result.tp == len(generated.truth.issues)


def test_split_receipts_legitimate_outstanding_recurring_amounts_and_refund():
    generated = generate_episode(6, FIXED)
    public = generated.public
    assert generated.truth.issues == []
    grouped = defaultdict(list)
    for payment in public.payments:
        grouped[payment.invoice_refs[0].invoice_id].append(payment)
    split_id, split = next((key, value) for key, value in grouped.items() if len(value) == 2 and all(p.transaction_kind == "receipt" for p in value))
    assert sorted(p.amount_minor for p in split) == [3_500_000, 3_500_000]
    outstanding = sum(r.debit_minor - r.credit_minor for r in public.ledger if r.invoice_id == split_id and r.account == "receivables")
    assert outstanding == 3_000_000  # 100,000 - 35,000 - 35,000 KZT, no defect.
    assert len({p.payment_id for p in split}) == 2
    refund = next(p for p in public.payments if p.transaction_kind == "refund")
    original = next(p for p in public.payments if p.payment_id == refund.original_payment_id)
    assert original.amount_minor == 7_000_000 and refund.amount_minor == 1_750_000
    view = settlement_view(refund, public.ledger)
    assert (view.received_minor, view.applied_minor, view.unapplied_minor) == (-1_750_000, -1_750_000, 0)
    assert settlement_view(original, public.ledger).applied_minor == 7_000_000
    outstanding = sum(r.debit_minor - r.credit_minor for r in public.ledger if r.invoice_id == original.invoice_refs[0].invoice_id and r.account == "receivables")
    assert outstanding == 4_750_000  # 100,000 - 70,000 + 17,500 KZT.
    # Every invoice repeats this amount, but distinct invoice identity is decisive.
    for invoice in public.invoices:
        journals = {r.journal_id for r in public.ledger if r.invoice_id == invoice.invoice_id and r.entry_kind == "recognition"}
        assert len(journals) == 1


def test_balanced_duplicate_counts_one_revenue_leg_and_leaves_controls_clean():
    generated = generate_episode(6, {**FIXED, "duplicate_invoices": 1})
    independently_balanced(generated.public)
    issue, = generated.truth.issues
    assert issue.type == "duplicate_invoice" and issue.expected_amount_minor == 10_000_000
    rows = [r for r in generated.public.ledger if r.invoice_id in issue.affected_ids and r.entry_kind == "recognition"]
    assert len(rows) == 4 and len({r.journal_id for r in rows}) == 2
    assert sum(r.debit_minor + r.credit_minor for r in rows) == 40_000_000
    assert len(independent_findings(generated.public)) == 1
    with pytest.raises(ValueError, match="recognition"):
        validate_accounting(generated.public, clean=True)
    evidence = issue.evidence_sets[0]
    cited_rows = [r for r in rows if r.row_id in evidence]
    assert len(cited_rows) == 2 and all(r.account == "revenue" for r in cited_rows)
    assert len({r.posting_sequence for r in cited_rows}) == 2


def test_worked_partial_and_wholly_missing_allocations_from_final_rows():
    generated = generate_episode(6, MIXED)
    allocation_issues = [t for t in generated.truth.issues if t.type == "payment_allocation"]
    # Seed 6 selects two distinct halves of the split 70,000 KZT receipt.
    assert sorted(t.expected_amount_minor for t in allocation_issues) == [2_000_000, 3_500_000]
    for issue in allocation_issues:
        payment = next(p for p in generated.public.payments if p.payment_id in issue.affected_ids)
        rows = [r for r in generated.public.ledger if r.payment_id == payment.payment_id and r.entry_kind == "allocation"]
        view = settlement_view(payment, generated.public.ledger)
        assert payment.amount_minor == 3_500_000
        if issue.expected_amount_minor == 3_500_000:
            assert rows == [] and view.allocations[0].ledger_row_ids == []
            assert view.applied_minor == 0
        else:
            assert len(rows) == 2 and view.applied_minor == 1_500_000
        assert view.unapplied_minor == issue.expected_amount_minor
        assert issue.expected_amount_minor == payment.invoice_refs[0].amount_minor - sum(r.credit_minor for r in rows if r.account == "receivables")


def test_hand_calculated_100000_invoice_70000_receipt_50000_application():
    generated = generate_episode(0, {**FIXED, "partial_allocations": 1})
    issue, = generated.truth.issues
    payment = next(p for p in generated.public.payments if p.payment_id in issue.affected_ids)
    invoice = next(i for i in generated.public.invoices if i.invoice_id in issue.affected_ids)
    assert invoice.total_minor == 10_000_000 and payment.amount_minor == 7_000_000
    applied = sum(r.credit_minor for r in generated.public.ledger if r.payment_id == payment.payment_id and r.account == "receivables")
    assert applied == 5_000_000 and issue.expected_amount_minor == 2_000_000
    assert sum(r.debit_minor - r.credit_minor for r in generated.public.ledger if r.invoice_id == invoice.invoice_id and r.account == "receivables") == 5_000_000


def test_provenance_reconstructs_every_row_and_links_back_to_latent_events():
    generated = generate_episode(6, MIXED)
    original = {r.row_id: r.model_dump(mode="json") for r in generated.clean.ledger}
    changed = dict(original)
    events = {e.event_id for e in generated.history.sales + generated.history.cash_events}
    assert set(generated.provenance.event_ids) == events
    assert Counter(m.operation for m in generated.provenance.mutations) == {"remove": 2, "replace": 2, "insert": 2}
    for mutation in generated.provenance.mutations:
        assert mutation.event_id in events and mutation.field == "ledger_row"
        key, = mutation.object_ids
        if mutation.operation != "insert":
            assert changed.pop(key) == json.loads(mutation.clean_value)
        else:
            assert mutation.clean_value is None and key not in changed
        if mutation.operation != "remove":
            changed[key] = json.loads(mutation.observed_value)
            LedgerRow.model_validate(changed[key])
        else:
            assert mutation.observed_value is None
    assert changed == {r.row_id: r.model_dump(mode="json") for r in generated.public.ledger}
    for mutation in reversed(generated.provenance.mutations):
        key, = mutation.object_ids
        if mutation.operation != "remove":
            changed.pop(key)
        if mutation.operation != "insert":
            changed[key] = json.loads(mutation.clean_value)
    assert changed == original


def test_repeat_seed_config_reproduces_all_serialized_files_without_global_rng(tmp_path):
    before = random.getstate()
    first, second = generate_episode(18, MIXED), generate_episode(18, MIXED)
    assert random.getstate() == before and first == second
    assert generate_episode(19, MIXED).public != first.public
    for name, episode in (("a", first), ("b", second)):
        save_generated(tmp_path / name, episode)
    paths = sorted(path.relative_to(tmp_path / "a") for path in (tmp_path / "a").rglob("*") if path.is_file())
    assert len(paths) == 10
    for path in paths:
        assert (tmp_path / "a" / path).read_bytes() == (tmp_path / "b" / path).read_bytes()
    assert load_public(tmp_path / "a/public") == first.public
    assert read_json(tmp_path / "a/private/truth.json", Truth) == first.truth
    assert read_json(tmp_path / "a/private/provenance.json", Provenance) == first.provenance
    with pytest.raises(FileExistsError):
        save_generated(tmp_path / "a", first)


def test_generator_reset_repeats_and_clears_previous_state_without_seed_leaks():
    env = AuditEnvironment()
    initial, info = env.reset(seed=71539, config={"generator": MIXED})
    action = {"type": "list_records", "table": "ledger", "cursor": None, "limit": 50}
    first = env.step(action)
    env.step({"type": "submit", "findings": {"episode_id": "wrong", "findings": []}})
    repeated, _ = env.reset(seed=71539, config={"generator": MIXED})
    assert repeated == initial and env.action_count == 0 and env._last_score is None
    assert env.step(action) == first
    assert info == {} and "71539" not in json.dumps(initial)
    assert not any(word in json.dumps(initial).lower() for word in ("seed", "provenance", "truth", "partial_allocations"))
    with pytest.raises(ValueError):
        env.reset(seed=6, config={"fixture": "company-a", "generator": {}})
    with pytest.raises(ValueError):
        env.reset(config={"generator": {}})


def test_partial_targets_are_reserved_before_missing_targets_and_variants_have_unique_episode_ids():
    for seed in range(5):
        generated = generate_episode(seed, {**FIXED, "missing_allocations": 5, "partial_allocations": 1, "partial_shortfall_minor": 5_000_000})
        assert len(generated.truth.issues) == 6
    clean = generate_episode(6, FIXED)
    faulty = generate_episode(6, {**FIXED, "duplicate_invoices": 1})
    assert clean.public.manifest.episode_id != faulty.public.manifest.episode_id
    assert clean.clean.ledger == faulty.clean.ledger  # Same underlying business control.


@pytest.mark.parametrize("config", [
    {"invoice_count": 3}, {"invoice_count": True}, {"duplicate_invoices": -1},
    {"duplicate_invoices": 7}, {"missing_allocations": 7}, {"partial_allocations": 1.0},
    {"duplicate_invoices": 5, "missing_allocations": 4, "partial_allocations": 4},
    {"amount_min_minor": 1000, "amount_max_minor": 100},
    {"amount_min_minor": 100, "amount_max_minor": 100, "partial_allocations": 1},
    {"version": "unknown"}, {"seed": 1},
])
def test_reject_invalid_or_impossible_configuration(config):
    with pytest.raises(ValueError):
        generate_episode(6, config)


def test_clean_validator_detects_broken_journal_and_misdirected_application():
    clean = generate_episode(6, FIXED).clean
    row = clean.ledger[0]
    bad = clean.model_copy(update={"ledger": [row.model_copy(update={"debit_minor": row.debit_minor + 1}), *clean.ledger[1:]]})
    with pytest.raises(ValueError, match="unbalanced"):
        validate_accounting(bad, clean=True)
    allocation = next(r for r in clean.ledger if r.entry_kind == "allocation" and r.account == "receivables")
    rows = [r.model_copy(update={"debit_minor": r.debit_minor // 2, "credit_minor": r.credit_minor // 2}) if r.journal_id == allocation.journal_id else r for r in clean.ledger]
    with pytest.raises(ValueError, match="allocation"):
        validate_accounting(clean.model_copy(update={"ledger": rows}), clean=True)


@pytest.mark.parametrize("seed", [0, 1, 17, 42, 2147483647])
def test_varied_amounts_ids_order_and_seeds_have_independent_public_proof(seed):
    config = {"duplicate_invoices": 2, "missing_allocations": 1, "partial_allocations": 2}
    generated = generate_episode(seed, config)
    independently_balanced(generated.public)
    assert len(independent_findings(generated.public)) == len(generated.truth.issues) == 5
    expected = {(t.type, frozenset(t.affected_ids)): t.expected_amount_minor for t in generated.truth.issues}
    assert {(f.type, frozenset(f.affected_ids)): f.claimed_amount_minor for f in independent_findings(generated.public)} == expected
    assert all(len(proof) <= 10 for issue in generated.truth.issues for proof in issue.evidence_sets)


def test_linux_generated_clean_and_mixed_episode_through_same_tools():
    require_linux()
    for config, expected_tp in ((FIXED, 0), (MIXED, 3)):
        result = run_isolated_generated(6, config)
        private, trace = result["private_result"], result["trajectory"]
        assert private["reason"] == "completed" and private["agent_reaped"]
        assert private["record_storage"] == "trusted evaluator memory"
        assert private["agent_uid"] == 65534 and private["evaluator_uid"] == 0
        assert private["score"]["tp"] == expected_tp and private["score"]["fp"] == private["score"]["fn"] == 0
        assert private["score"]["f1"] == 1
        assert private["score"]["score"] == pytest.approx(0.98)  # 3 list + 7 receipt documents = 10 inspections.
        assert private["actions"] == 11
        assert all(row["reward"] == 0 and row["delivered"] for row in trace)
        assert trace[-1]["terminated"] and not trace[-1]["truncated"]
        assert "stage06-v1" not in json.dumps(trace)  # Private configuration is never sent.
