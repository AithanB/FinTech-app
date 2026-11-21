"""Independent public reconstruction of FX and local-period discrepancies."""

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
import json
from pathlib import Path
import random
from zoneinfo import ZoneInfo

import pytest

from audit_env.accounting import applicable_fx, convert_minor, in_period, local_date
from audit_env.environment import AuditEnvironment
from audit_env.generation import GeneratorConfig, generate_episode, save_generated, validate_accounting
from audit_env.isolation import run_isolated_generated
from audit_env.schemas import Finding, PublicEpisode
from audit_env.serialization import load_public
from test_stage05 import require_linux


BASE = {"version": "stage07-v1", "currencies": ["KZT", "USD", "EUR", "JPY"],
        "boundary_cases": True, "amount_min_minor": 10000, "amount_max_minor": 10000,
        "partial_shortfall_minor": 2000}
MIXED = json.loads(Path("configs/stage07-mixed.json").read_text())


def public_findings(public):
    """No production conversion, period helper, settlement view or truth input."""
    zone = ZoneInfo(public.manifest.timezone)

    def member(timestamp):
        local = timestamp.astimezone(zone)
        return public.manifest.period_start.astimezone(zone) <= local < public.manifest.period_end.astimezone(zone)

    def converted(amount, currency, timestamp):
        if currency == "KZT":
            return amount, []
        rate, = [r for r in public.fx if r.date == timestamp.astimezone(zone).date()
                 and r.source_currency == currency and r.target_currency == "KZT"]
        # Independent major-unit arithmetic, with fixed published exponents.
        source_units = 1 if currency == "JPY" else 100
        with localcontext() as context:
            context.prec = 80
            value = (Decimal(amount) / source_units * Decimal(str(rate.rate)) * 100).to_integral_value(rounding=ROUND_HALF_UP)
        return int(value), [rate.evidence_id]

    findings = []

    def add(kind, affected, amount, evidence):
        findings.append(Finding(type=kind, affected_ids=affected, claimed_amount_minor=amount,
                                currency="KZT", evidence_ids=evidence, explanation="Reconstructed from public records."))

    for invoice in public.invoices:
        rows = sorted((r for r in public.ledger if r.invoice_id == invoice.invoice_id
                       and r.entry_kind == "recognition" and r.account == "revenue"), key=lambda r: r.posting_sequence)
        if len(rows) > 1:
            add("duplicate_invoice", [invoice.invoice_id], sum(r.credit_minor for r in rows[1:]),
                [invoice.doc_id, *[r.row_id for r in rows]])
        for row in rows:
            expected, fx = converted(invoice.total_minor, invoice.currency, invoice.service_at)
            if row.credit_minor != expected:
                add("fx_conversion", [row.journal_id], abs(expected - row.credit_minor), [invoice.doc_id, row.row_id, *fx])
            if member(invoice.service_at) != member(row.timestamp):
                add("period_cutoff", [row.journal_id], row.credit_minor, [invoice.doc_id, row.row_id])
    for payment in public.payments:
        if payment.transaction_kind == "refund":
            continue
        for ref in payment.invoice_refs:
            expected, fx = converted(ref.amount_minor, payment.currency, payment.timestamp)
            actual = sum(r.credit_minor - r.debit_minor for r in public.ledger
                         if r.payment_id == payment.payment_id and r.invoice_id == ref.invoice_id
                         and r.entry_kind == "allocation" and r.account == "receivables")
            if actual != expected:
                add("payment_allocation", [payment.payment_id, ref.invoice_id], abs(expected - actual),
                    [payment.doc_id, f"settlement:{payment.payment_id}", *fx])
    return findings


@pytest.mark.parametrize("amount,source,target,rate,expected", [
    (10000, "USD", "KZT", "500", 5_000_000),  # USD 100 -> KZT 50,000.
    (100, "JPY", "KZT", "3.2", 32_000),       # JPY has no minor decimal places.
    (12345, "USD", "JPY", "150", 18518),      # 123.45 * 150 = 18517.5 -> 18518.
    (1, "USD", "KZT", "0.5", 1),            # Exactly half of a target minor unit.
    (1, "JPY", "KZT", "0.005", 1),
    (100, "USD", "JPY", "0.5", 1),
    (1, "USD", "KZT", "0.499999", 0),
    (123, "JPY", "USD", "0.0067", 82),
])
def test_hand_calculated_conversion_and_one_half_up_round(amount, source, target, rate, expected):
    with localcontext() as context:
        context.prec = 2  # Production must not depend on caller decimal state.
        assert convert_minor(amount, source, target, rate) == expected


@pytest.mark.parametrize("kwargs,counts", [
    ({}, {}), ({"duplicate_invoices": 1}, {"duplicate_invoice": 1}),
    ({"missing_allocations": 1}, {"payment_allocation": 1}),
    ({"partial_allocations": 1}, {"payment_allocation": 1}),
    ({"wrong_fx_dates": 1}, {"fx_conversion": 1}),
    ({"wrong_fx_rates": 1}, {"fx_conversion": 1}),
    ({"misplaced_recognitions": 1}, {"period_cutoff": 1}),
    ({k: MIXED[k] for k in ("duplicate_invoices", "missing_allocations", "partial_allocations", "wrong_fx_dates", "wrong_fx_rates", "misplaced_recognitions")},
     {"duplicate_invoice": 1, "payment_allocation": 2, "fx_conversion": 2, "period_cutoff": 1}),
])
def test_independent_switches_final_public_proof_and_real_submit(kwargs, counts):
    config = {**BASE, **kwargs}
    generated = generate_episode(7, config)
    assert public_findings(generated.clean) == []
    findings = public_findings(generated.public)
    assert Counter(f.type for f in findings) == Counter(t.type for t in generated.truth.issues) == counts
    assert {(f.type, frozenset(f.affected_ids), f.claimed_amount_minor) for f in findings} == {
        (t.type, frozenset(t.affected_ids), t.expected_amount_minor) for t in generated.truth.issues}
    env = AuditEnvironment()
    initial, _ = env.reset(seed=7, config={"generator": config, "mode": "open"})
    observation, reward, terminated, truncated, _ = env.step({"type": "submit", "findings": {
        "episode_id": initial["manifest"]["episode_id"], "findings": [f.model_dump(mode="json") for f in findings]}})
    assert observation["result"]["accepted"] and terminated and not truncated and reward == 1
    assert env._last_scoring_result.tp == len(findings)
    assert env._last_scoring_result.fp == env._last_scoring_result.fn == 0


@pytest.mark.parametrize("knob", ["wrong_fx_dates", "wrong_fx_rates"])
def test_usd_100_at_500_posted_49000_has_100000_minor_discrepancy(knob):
    g = generate_episode(7, {**BASE, "boundary_cases": False, "currencies": ["USD", "KZT"], knob: 3})
    invoice = next(i for i in g.public.invoices if i.service_at.day == 1)
    assert invoice.currency == "USD" and invoice.total_minor == 10000
    rate = applicable_fx(g.public, invoice.currency, invoice.service_at)
    assert rate.rate == Decimal("500")
    row = next(r for r in g.public.ledger if r.invoice_id == invoice.invoice_id and r.account == "revenue")
    assert row.credit_minor == 4_900_000
    issue = next(t for t in g.truth.issues if t.affected_ids == [row.journal_id])
    assert issue.expected_amount_minor == 100_000
    # A distinct KZT event stays clean while every selected foreign journal changes.
    control = next(i for i in g.public.invoices if i.currency == "KZT")
    assert not any(control.doc_id in proof for t in g.truth.issues for proof in t.evidence_sets)
    for mutation in g.provenance.mutations:
        before, after = json.loads(mutation.clean_value), json.loads(mutation.observed_value)
        assert before["timestamp"] == after["timestamp"]
        assert (before["debit_minor"], before["credit_minor"]) != (after["debit_minor"], after["credit_minor"])
    for decision in g.history.fx_decisions:
        assert decision.variant == ("date" if knob == "wrong_fx_dates" else "rate")
        assert (decision.used_date < decision.required_date) == (decision.variant == "date")
        row = next(r for r in g.public.ledger if r.journal_id == decision.journal_id and r.account == "revenue")
        assert row.credit_minor == int((Decimal("100") * decision.used_rate * 100).to_integral_value(rounding=ROUND_HALF_UP))


def test_local_policy_date_uses_service_not_issuance_or_utc():
    g = generate_episode(7, {**BASE, "currencies": ["USD"]})
    invoice = next(i for i in g.public.invoices if i.service_at.day == 1 and i.service_at.month == 11)
    assert invoice.service_at.isoformat() == "2026-11-01T00:30:00+05:00"
    assert invoice.service_at.astimezone(timezone.utc).isoformat() == "2026-10-31T19:30:00+00:00"
    assert invoice.issued_at.date().isoformat() == "2026-10-31"
    row = next(r for r in g.public.ledger if r.invoice_id == invoice.invoice_id and r.account == "revenue")
    assert applicable_fx(g.public, "USD", invoice.service_at).rate == Decimal("500")
    assert row.credit_minor == 5_000_000 and in_period(row.timestamp, g.public.manifest)
    assert public_findings(g.public) == [] and g.truth.issues == []


@pytest.mark.parametrize("timestamp,expected", [
    ("2026-10-31T23:59:59.999999+05:00", False),
    ("2026-11-01T00:00:00+05:00", True),
    ("2026-11-01T00:30:00+05:00", True),
    ("2026-11-30T23:59:59.999999+05:00", True),
    ("2026-12-01T00:00:00+05:00", False),
    ("2026-12-01T00:00:00.000001+05:00", False),
    ("2026-11-30T19:00:00+00:00", False),
])
def test_inclusive_start_exclusive_end_in_policy_zone(timestamp, expected):
    manifest = generate_episode(7, BASE).public.manifest
    assert in_period(datetime.fromisoformat(timestamp), manifest) is expected


@pytest.mark.parametrize("zone", ["Asia/Almaty", "UTC", "Asia/Tokyo", "America/New_York"])
def test_timezones_boundary_controls_and_both_mutation_directions(zone):
    g = generate_episode(17, {**BASE, "timezone": zone, "misplaced_recognitions": 6})
    assert public_findings(g.clean) == []
    assert len(public_findings(g.public)) == 6
    seen = set()
    for invoice in g.public.invoices:
        row = next(r for r in g.public.ledger if r.invoice_id == invoice.invoice_id and r.account == "revenue")
        intended = in_period(invoice.service_at, g.public.manifest)
        assert in_period(row.timestamp, g.public.manifest) != intended
        seen.add(intended)
    assert seen == {True, False}


def test_adjacent_period_documents_rows_and_fx_are_accessible_through_tools():
    env = AuditEnvironment()
    env.reset(seed=7, config={"generator": {**BASE, "currencies": ["USD"]}})
    page = env.step({"type": "list_records", "table": "invoices", "cursor": None, "limit": 50})[0]["result"]
    adjacent = [item for item in page["rows"] if item["record"]["service_at"].startswith(("2026-10-31", "2026-12-01"))]
    assert len(adjacent) == 2
    for item in adjacent:
        document = env.step({"type": "get_document", "doc_id": item["record"]["doc_id"]})[0]["result"]
        assert document == item["record"]
        evidence = f"fx:{document['service_at'][:10]}:USD:KZT"
        assert env.step({"type": "get_record", "table": "fx", "id": evidence})[0]["result"]["id"] == evidence
    rows = env.step({"type": "list_records", "table": "ledger", "cursor": None, "limit": 50})[0]["result"]["rows"]
    assert {item["record"]["invoice_id"] for item in rows} >= {item["id"] for item in adjacent}


def test_missing_required_rate_invalidates_company_and_wrong_direction_does_not_substitute():
    public = generate_episode(7, BASE).public
    required = applicable_fx(public, "USD", next(i.service_at for i in public.invoices if i.currency == "USD"))
    fx = [r for r in public.fx if r != required]
    fx.append(required.model_copy(update={"source_currency": "KZT", "target_currency": "USD"}))
    bad = public.model_copy(update={"fx": fx})
    for clean in (False, True):
        with pytest.raises(ValueError, match="required FX"):
            validate_accounting(bad, clean=clean)


def test_noop_wrong_date_candidate_is_rejected_after_rounding(monkeypatch):
    from audit_env import generation

    original = generation._derive

    def with_near_equal_previous_rate(history, ids):
        public = original(history, ids)
        # Only October 31 is unused by all clean business events here. At USD
        # 100, 499.999999 converts to 4,999,999.99 minor -> 5,000,000, unchanged.
        fx = [r.model_copy(update={"rate": Decimal("499.999999")}) if r.date.isoformat() == "2026-10-31" else r for r in public.fx]
        return public.model_copy(update={"fx": fx})

    monkeypatch.setattr(generation, "_derive", with_near_equal_previous_rate)
    config = {**BASE, "boundary_cases": False, "currencies": ["USD"], "wrong_fx_dates": 6}
    with pytest.raises(ValueError, match="rounded amount"):
        generate_episode(7, config)
    config["wrong_fx_dates"] = 5
    g = generate_episode(7, config)
    assert len(public_findings(g.public)) == 5
    control = next(i for i in g.public.invoices if i.service_at.day == 1)
    assert all(control.doc_id not in proof for t in g.truth.issues for proof in t.evidence_sets)


@pytest.mark.parametrize("knob", ["wrong_fx_dates", "wrong_fx_rates"])
def test_all_noop_candidates_fail_instead_of_creating_truth(monkeypatch, knob):
    from audit_env import generation

    original = generation._derive

    def tiny_rates(history, ids):
        public = original(history, ids)
        fx = [r.model_copy(update={"rate": Decimal("0.001")}) for r in public.fx]
        amounts = {i.invoice_id: i.total_minor for i in public.invoices}
        payments = {p.payment_id: p.amount_minor for p in public.payments}
        rows = []
        for row in public.ledger:
            source = payments[row.payment_id] if row.payment_id else amounts[row.invoice_id]
            value = int((Decimal(source) * Decimal("0.001")).to_integral_value(rounding=ROUND_HALF_UP))
            rows.append(row.model_copy(update={"debit_minor": value if row.debit_minor else 0,
                                               "credit_minor": value if row.credit_minor else 0}))
        return public.model_copy(update={"fx": fx, "ledger": rows})

    monkeypatch.setattr(generation, "_derive", tiny_rates)
    config = {**BASE, "boundary_cases": False, "currencies": ["USD"]}
    clean = generate_episode(7, config)
    assert public_findings(clean.public) == []
    assert {r.credit_minor for r in clean.public.ledger if r.account == "revenue"} == {10}
    # Wrong-date uses the same rate; wrong-rate posts 9.8 minor -> the same 10.
    with pytest.raises(ValueError, match="rounded amount"):
        generate_episode(7, {**config, knob: 1})


def test_replay_roundtrip_counts_and_reversible_provenance(tmp_path):
    state = random.getstate()
    a, b = generate_episode(7, MIXED), generate_episode(7, MIXED)
    assert a == b and random.getstate() == state
    for name, g in (("a", a), ("b", b)):
        save_generated(tmp_path / name, g)
    files = [p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*") if p.is_file()]
    assert len(files) == 10
    for path in files:
        assert (tmp_path / "a" / path).read_bytes() == (tmp_path / "b" / path).read_bytes()
    assert load_public(tmp_path / "a/public") == a.public
    PublicEpisode.model_validate_json(a.public.model_dump_json())
    rows = {r.row_id: r.model_dump(mode="json") for r in a.clean.ledger}
    for mutation in a.provenance.mutations:
        key, = mutation.object_ids
        assert rows.pop(key, None) == (json.loads(mutation.clean_value) if mutation.clean_value else None)
        if mutation.observed_value:
            rows[key] = json.loads(mutation.observed_value)
    assert rows == {r.row_id: r.model_dump(mode="json") for r in a.public.ledger}
    for mutation in reversed(a.provenance.mutations):
        key, = mutation.object_ids
        assert rows.pop(key, None) == (json.loads(mutation.observed_value) if mutation.observed_value else None)
        if mutation.clean_value:
            rows[key] = json.loads(mutation.clean_value)
    assert rows == {r.row_id: r.model_dump(mode="json") for r in a.clean.ledger}


@pytest.mark.parametrize("seed", [0, 1, 17, 42, 2147483647])
def test_varied_seeds_match_final_evidence(seed):
    g = generate_episode(seed, MIXED)
    assert {(f.type, frozenset(f.affected_ids), f.claimed_amount_minor) for f in public_findings(g.public)} == {
        (t.type, frozenset(t.affected_ids), t.expected_amount_minor) for t in g.truth.issues}


@pytest.mark.parametrize("extra", [
    {"wrong_fx_dates": True}, {"wrong_fx_rates": -1}, {"misplaced_recognitions": 7},
    {"currencies": []}, {"currencies": ["USD", "USD"]}, {"timezone": "Invalid/Zone"},
    {"currencies": ["KZT"], "wrong_fx_dates": 1}, {"wrong_fx_dates": 3, "wrong_fx_rates": 2},
    {"version": "stage06-v1"}, {"misplaced_recognitions": 6, "duplicate_invoices": 6, "wrong_fx_rates": 1},
])
def test_invalid_config_rejected(extra):
    with pytest.raises(ValueError):
        generate_episode(7, {**BASE, **extra})


def test_naive_timestamp_rejected_by_accounting_helpers():
    manifest = generate_episode(7, BASE).public.manifest
    with pytest.raises(ValueError, match="timezone"):
        in_period(datetime(2026, 11, 1), manifest)
    with pytest.raises(ValueError, match="timezone"):
        local_date(datetime(2026, 11, 1), "UTC")


def test_linux_policy_derives_each_individual_family_and_clean_fx_from_public_tools():
    require_linux()
    for extra, count in (({}, 0), ({"duplicate_invoices": 1}, 1), ({"missing_allocations": 1}, 1),
                         ({"partial_allocations": 1}, 1), ({"wrong_fx_dates": 1}, 1),
                         ({"wrong_fx_rates": 1}, 1), ({"misplaced_recognitions": 1}, 1), (MIXED, 6),
                         ({"currencies": ["USD"]}, 0),
                         ({"timezone": "America/New_York"}, 0),
                         ({"currencies": ["JPY"], "timezone": "Asia/Tokyo"}, 0)):
        result = run_isolated_generated(7, {**BASE, **extra})
        private, trace = result["private_result"], result["trajectory"]
        assert private["reason"] == "completed" and private["agent_reaped"]
        assert private["score"]["tp"] == count
        assert private["score"]["fp"] == private["score"]["fn"] == 0
        assert private["score"]["f1"] == 1 and private["score"]["score"] == pytest.approx(0.978)
        assert private["actions"] == 12
        assert all(row["reward"] == 0 and row["delivered"] for row in trace)
        assert trace[-1]["terminated"] and not trace[-1]["truncated"]
        assert "stage07-v1" not in json.dumps(trace)
