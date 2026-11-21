"""Dependency-free ordinary policy adapters; inputs are public messages only.

run_policy(name, initial, act, seed=0) starts fresh episode-local state. ``act``
accepts a JSON action and returns its observation result, or raises EpisodeEnded
when the episode closes. The same adapter is used by tests and the jailed wire.
"""

import json
import random
import sys
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from zoneinfo import ZoneInfo

ORDINARY_POLICIES = ("random", "reconciliation", "mass_accusation")


class EpisodeEnded(Exception):
    """A terminal response stops policy computation immediately."""


def read_table(act, name):
    rows, cursor = [], None
    while True:
        page = act({"type": "list_records", "table": name, "cursor": cursor, "limit": 50})
        rows.extend(item["record"] for item in page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            return rows


def reconcile(initial, act):
    def table(name):
        return read_table(act, name)

    invoices, payments, ledger = table("invoices"), table("payments"), table("ledger")
    manifest = initial["manifest"]
    zone = ZoneInfo(manifest["timezone"])
    fx = table("fx") if any(d["currency"] != "KZT" for d in invoices + payments) else []


    def converted(amount, currency, timestamp):
        if currency == "KZT":
            return amount, []
        date = datetime.fromisoformat(timestamp).astimezone(zone).date().isoformat()
        row = next(r for r in fx if r["date"] == date and r["source_currency"] == currency and r["target_currency"] == "KZT")
        with localcontext() as context:
            context.prec = 80
            result = Decimal(amount) / Decimal(10) ** manifest["currency_exponents"][currency]
            result *= Decimal(row["rate"]) * Decimal(10) ** manifest["currency_exponents"]["KZT"]
            return int(result.to_integral_value(rounding=ROUND_HALF_UP)), [f"fx:{date}:{currency}:KZT"]


    def belongs(timestamp):
        value = datetime.fromisoformat(timestamp).astimezone(zone)
        return datetime.fromisoformat(manifest["period_start"]).astimezone(zone) <= value < datetime.fromisoformat(manifest["period_end"]).astimezone(zone)


    findings = []
    for invoice in invoices:
        rows = sorted((r for r in ledger if r["invoice_id"] == invoice["invoice_id"] and r["entry_kind"] == "recognition" and r["account"] == "revenue"), key=lambda r: r["posting_sequence"])
        if len(rows) > 1:
            findings.append({
                "type": "duplicate_invoice", "affected_ids": [invoice["invoice_id"]],
                "claimed_amount_minor": sum(r["credit_minor"] for r in rows[1:]), "currency": "KZT",
                "evidence_ids": [invoice["doc_id"], *[r["row_id"] for r in rows]],
                "explanation": "Distinct journals repeat revenue recognition for the same invoice.",
            })
        for row in rows:
            expected, evidence = converted(invoice["total_minor"], invoice["currency"], invoice["service_at"])
            if evidence and row["credit_minor"] != expected:
                findings.append({
                    "type": "fx_conversion", "affected_ids": [row["journal_id"]],
                    "claimed_amount_minor": abs(expected - row["credit_minor"]), "currency": "KZT",
                    "evidence_ids": [invoice["doc_id"], row["row_id"], *evidence],
                    "explanation": "Service-date directional FX differs from the posted revenue.",
                })
            if belongs(row["timestamp"]) != belongs(invoice["service_at"]):
                findings.append({
                    "type": "period_cutoff", "affected_ids": [row["journal_id"]],
                    "claimed_amount_minor": row["credit_minor"], "currency": "KZT",
                    "evidence_ids": [invoice["doc_id"], row["row_id"]],
                    "explanation": "Recognition and service fall on different sides of the local period.",
                })
    for payment in payments:
        if payment["transaction_kind"] == "refund":
            continue
        rows = [r for r in ledger if r["payment_id"] == payment["payment_id"]
                and r["entry_kind"] == "allocation" and r["account"] == "receivables"]
        for row in rows:
            if belongs(row["timestamp"]) != belongs(payment["timestamp"]):
                findings.append({
                    "type": "period_cutoff", "affected_ids": [row["journal_id"]],
                    "claimed_amount_minor": abs(row["credit_minor"] - row["debit_minor"]), "currency": "KZT",
                    "evidence_ids": [payment["doc_id"], row["row_id"]],
                    "explanation": "Application and payment fall on different sides of the local period.",
                })
        # Preserve the tiny tutorial's inspection sequence. At larger sizes first
        # reconcile listed rows, then request only the settlements needed for proof.
        settlement = None
        if manifest["document_count"] < 20:
            settlement = act({"type": "get_document", "doc_id": payment["doc_id"]})["settlement"]
        for ref in payment["invoice_refs"]:
            applied = sum(r["credit_minor"] - r["debit_minor"] for r in rows if r["invoice_id"] == ref["invoice_id"])
            intended, evidence = converted(ref["amount_minor"], payment["currency"], payment["timestamp"])
            difference = intended - applied
            if difference:
                if settlement is None:
                    settlement = act({"type": "get_document", "doc_id": payment["doc_id"]})["settlement"]
                findings.append({
                    "type": "payment_allocation", "affected_ids": [payment["payment_id"], ref["invoice_id"]],
                    "claimed_amount_minor": abs(difference), "currency": "KZT",
                    "evidence_ids": [payment["doc_id"], settlement["evidence_id"], *evidence],
                    "explanation": "The intended application differs from the public settlement.",
                })
    submit(initial, act, findings)


def submit(initial, act, findings):
    act({"type": "submit", "findings": {
        "episode_id": initial["manifest"]["episode_id"], "findings": findings,
    }})


def accuse(record, issue_type):
    """Deliberately unsupported, but structurally valid, public-ID accusation."""
    invoice = "invoice_id" in record
    target = record["invoice_id"] if invoice else record["payment_id"]
    if issue_type == "payment_allocation":
        refs = record.get("invoice_refs", [])
        if not refs:
            return None
        affected = [target, refs[0]["invoice_id"]]
    else:
        affected = [target]
    return {
        "type": issue_type, "affected_ids": affected,
        "claimed_amount_minor": record.get("total_minor", record.get("amount_minor", 0)),
        "currency": record["currency"], "evidence_ids": [record["doc_id"]],
        "explanation": "Accuse every available object without reconciling its evidence.",
    }


def mass_accusation(initial, act):
    findings = []
    for name, types in (("invoices", ("duplicate_invoice", "fx_conversion", "period_cutoff")),
                        ("payments", ("payment_allocation",))):
        for record in read_table(act, name):
            for kind in types:
                finding = accuse(record, kind)
                if finding is not None:
                    findings.append(finding)
                if len(findings) == 30:
                    return submit(initial, act, findings)
    submit(initial, act, findings)


def random_explorer(initial, act, seed):
    rng = random.Random(seed)  # Policy seed is independent of the company seed.
    cursors, seen = {}, []
    for _ in range(20):
        table = rng.choice(("invoices", "payments", "ledger", "fx"))
        if seen and rng.random() < .4:
            name, record_id, record = rng.choice(seen)
            if "doc_id" in record and rng.random() < .5:
                act({"type": "get_document", "doc_id": record["doc_id"]})
            else:
                act({"type": "get_record", "table": name, "id": record_id})
        else:
            page = act({"type": "list_records", "table": table,
                        "cursor": cursors.get(table), "limit": rng.randint(1, 50)})
            cursors[table] = page["next_cursor"]
            seen.extend((table, item["id"], item["record"]) for item in page["rows"])
    candidates = [record for name, _, record in seen if name in ("invoices", "payments")]
    rng.shuffle(candidates)
    findings = []
    for record in candidates[:rng.randint(0, 5)]:
        kind = rng.choice(("duplicate_invoice", "fx_conversion", "period_cutoff")) if "invoice_id" in record else "payment_allocation"
        finding = accuse(record, kind)
        if finding is not None:
            findings.append(finding)
    submit(initial, act, findings)


def run_policy(name, initial, act, *, seed=0):
    """Common adapter. No caches, findings or RNG state survive a call."""
    if name not in ORDINARY_POLICIES:
        raise ValueError("unknown ordinary policy")
    try:
        if name == "random":
            random_explorer(initial, act, seed)
        elif name == "reconciliation":
            reconcile(initial, act)
        else:
            mass_accusation(initial, act)
    except EpisodeEnded:
        pass


def wire_main(name, seed=0):
    initial = json.loads(sys.stdin.readline())["observation"]

    def act(action):
        print(json.dumps(action, allow_nan=False), flush=True)
        response = json.loads(sys.stdin.readline())
        if response["terminated"] or response["truncated"]:
            raise EpisodeEnded
        return response["observation"]["result"]

    run_policy(name, initial, act, seed=seed)
