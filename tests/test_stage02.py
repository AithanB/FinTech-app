import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from audit_env.schemas import (
    ACTION_ADAPTER, CalculatorReply, DocumentReply, FXRow, Invoice,
    LedgerRow, ListReply, Manifest, Payment, Provenance, PublicEpisode,
    RecordReply, Submission, SubmitReply, Truth,
)
from audit_env.serialization import load_public, read_csv, read_json, save_public, write_json
from audit_env.views import settlement_view

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name,applied,outstanding,missing", [
    ("company-a", 7000000, 3000000, 0),
    ("company-b", 5000000, 5000000, 2000000),
])
def test_independent_accounting_and_proof(name, applied, outstanding, missing):
    episode = load_public(FIXTURES / name / "public")
    payment = episode.payments[0]
    view = settlement_view(payment, episode.ledger)
    assert episode.invoices[0].total_minor == 10000000
    assert payment.amount_minor == 7000000
    assert view.received_minor == 7000000
    assert view.applied_minor == applied
    assert view.unapplied_minor == missing
    assert view.allocations[0].applied_minor == applied
    assert payment.invoice_refs[0].amount_minor - view.applied_minor == missing
    # Compute outstanding directly from public receivables, independent of view.
    assert sum(row.debit_minor - row.credit_minor for row in episode.ledger if row.account == "receivables") == outstanding
    journals = defaultdict(int)
    for row in episode.ledger:
        journals[row.journal_id] += row.debit_minor - row.credit_minor
    assert all(balance == 0 for balance in journals.values())
    private = FIXTURES / name / "private"
    truth = read_json(private / "truth.json", Truth)
    submission = read_json(private / "expected_submission.json", Submission)
    provenance = read_json(private / "provenance.json", Provenance)
    assert len(truth.issues) == len(submission.findings) == (1 if missing else 0)
    assert len(provenance.mutations) == (2 if missing else 0)
    if missing:
        issue, finding = truth.issues[0], submission.findings[0]
        assert issue.expected_amount_minor == finding.claimed_amount_minor == 2000000
        assert set(issue.affected_ids) == {payment.payment_id, "inv-264"}
        assert issue.evidence_sets == [[payment.doc_id, view.evidence_id]]
        assert finding.evidence_ids == issue.evidence_sets[0]


@pytest.mark.parametrize("name", ["company-a", "company-b"])
def test_public_roundtrip(tmp_path, name):
    original = load_public(FIXTURES / name / "public")
    save_public(tmp_path, original)
    assert load_public(tmp_path) == original
    assert PublicEpisode.model_validate_json(original.model_dump_json()) == original
    assert original.ledger[0].payment_id is None
    assert original.ledger[2].invoice_id is None
    assert original.ledger[0].timestamp.isoformat() == "2026-11-03T09:00:00+05:00"
    assert original.fx[0].rate == Decimal("500.00")
    assert "500.00" in (tmp_path / "fx.csv").read_text()
    assert "null" in (tmp_path / "ledger.csv").read_text()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["fx.csv", "invoices.jsonl", "ledger.csv", "manifest.json", "payments.jsonl", "policy.json"]


def test_wholly_missing_application_visible():
    episode = load_public(FIXTURES / "company-a/public")
    ledger = [row for row in episode.ledger if row.entry_kind != "allocation"]
    view = settlement_view(episode.payments[0], ledger)
    assert view.applied_minor == 0
    assert view.unapplied_minor == 7000000
    assert view.allocations[0].invoice_id == "inv-264"
    assert view.allocations[0].ledger_row_ids == []
    assert view.evidence_id == "settlement:pay-627"


@pytest.mark.parametrize("value", [True, False, 1.0, "100", -1])
def test_reject_non_minor_amounts(value):
    data = load_public(FIXTURES / "company-a/public").payments[0].model_dump(mode="json")
    data["amount_minor"] = value
    with pytest.raises(ValidationError):
        Payment.model_validate(data)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "0", "-1", "invalid", 500, 500.0, True])
def test_reject_rates(value):
    with pytest.raises(ValidationError):
        FXRow.model_validate({"date":"2026-11-03", "source_currency":"USD", "target_currency":"KZT", "rate":value})


@pytest.mark.parametrize("model,field,record", [
    (LedgerRow,"timestamp","ledger"), (Invoice,"issued_at","invoices"),
    (Invoice,"due_at","invoices"), (Invoice,"service_at","invoices"),
    (Payment,"timestamp","payments"),
])
def test_reject_naive_timestamps(model, field, record):
    episode = load_public(FIXTURES / "company-a/public")
    data = getattr(episode,record)[0].model_dump(mode="json")
    data[field] = "2026-11-03T09:00:00"
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(data))


def test_strict_extras_null_and_counts():
    episode = load_public(FIXTURES / "company-a/public")
    data = episode.model_dump(mode="json")
    data["truth"] = {"issues":[]}
    with pytest.raises(ValidationError):
        PublicEpisode.model_validate(data)
    data.pop("truth")
    data["manifest"]["record_count"] = 0
    with pytest.raises(ValidationError):
        PublicEpisode.model_validate(data)
    payment = episode.payments[0].model_dump(mode="json")
    del payment["original_payment_id"]
    with pytest.raises(ValidationError):
        Payment.model_validate(payment)


@pytest.mark.parametrize("bad", ["True", "7000000.0", "", "NaN"])
def test_csv_does_not_coerce_bad_integers(tmp_path, bad):
    text = (FIXTURES / "company-a/public/ledger.csv").read_text()
    path = tmp_path / "ledger.csv"
    path.write_text(text.replace(",10000000,0,", f",{bad},0,", 1))
    with pytest.raises(ValueError):
        read_csv(path, LedgerRow)


def test_action_examples():
    examples = json.loads((FIXTURES / "action-examples.json").read_text())
    reply_types = [ListReply, RecordReply, DocumentReply, CalculatorReply, SubmitReply]
    assert len(examples) == 5
    for example, reply_type in zip(examples, reply_types):
        request = ACTION_ADAPTER.validate_json(json.dumps(example["request"]))
        assert json.loads(request.model_dump_json()) == example["request"]
        reply = reply_type.model_validate_json(json.dumps(example["reply"]))
        assert json.loads(reply.model_dump_json()) == example["reply"]
    assert examples[3]["reply"]["result"] == "2000000"


@pytest.mark.parametrize("currency,rate", [("JPY","3.25"),("USD","500.00"),("EUR","540.1250")])
def test_fx_keys_and_decimal_strings(currency, rate):
    fx = FXRow.model_validate({"date":"2026-11-03","source_currency":currency,"target_currency":"KZT","rate":rate})
    assert fx.evidence_id == f"fx:2026-11-03:{currency}:KZT"
    assert json.loads(fx.model_dump_json())["rate"] == rate


@pytest.mark.parametrize("field", ["period_start", "period_end"])
def test_manifest_rejects_naive_boundary(field):
    data = load_public(FIXTURES / "company-a/public").manifest.model_dump(mode="json")
    data[field] = "2026-11-01T00:00:00"
    with pytest.raises(ValidationError):
        Manifest.model_validate(data)


@pytest.mark.parametrize("filename,model", [
    ("truth.json", Truth), ("provenance.json", Provenance),
    ("expected_submission.json", Submission),
])
def test_private_roundtrip(tmp_path, filename, model):
    original = read_json(FIXTURES / "company-b/private" / filename, model)
    path = tmp_path / filename
    write_json(path, original)
    assert read_json(path, model) == original


@pytest.mark.parametrize("timestamp", ["2026-11-10T12:30:00-03:30", "2026-11-10T12:30:00Z"])
def test_offset_and_large_integer_roundtrip(timestamp):
    data = load_public(FIXTURES / "company-a/public").payments[0].model_dump(mode="json")
    data["timestamp"] = timestamp
    data["amount_minor"] = 9007199254740993
    payment = Payment.model_validate_json(json.dumps(data))
    restored = Payment.model_validate_json(payment.model_dump_json())
    assert restored.timestamp.isoformat() == timestamp.replace("Z", "+00:00")
    assert restored.amount_minor == 9007199254740993


def test_fx_csv_rejects_nan_and_json_numeric_rate(tmp_path):
    path = tmp_path / "fx.csv"
    path.write_text("date,source_currency,target_currency,rate\n2026-11-03,USD,KZT,NaN\n")
    with pytest.raises(ValidationError):
        read_csv(path, FXRow)
    with pytest.raises(ValidationError):
        FXRow.model_validate_json('{"date":"2026-11-03","source_currency":"USD","target_currency":"KZT","rate":500.0}')


def test_submission_limits_and_unknown_claim_currency():
    original = json.loads((FIXTURES / "company-b/private/expected_submission.json").read_text())
    original["findings"][0]["currency"] = "CHF"
    assert Submission.model_validate(original).findings[0].currency == "CHF"
    for key, value in [("claimed_amount_minor", True), ("explanation", "x" * 1001), ("evidence_ids", ["doc-492"] * 11)]:
        data = json.loads(json.dumps(original))
        data["findings"][0][key] = value
        with pytest.raises(ValidationError):
            Submission.model_validate(data)
    original["findings"] *= 31
    with pytest.raises(ValidationError):
        Submission.model_validate(original)
