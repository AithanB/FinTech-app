"""Trusted final-evidence audit, independent of generator accounting helpers.

No seed, latent history, mutation requests or production settlement/conversion
function participates in reconstruction. This is validation, not a policy adapter.
"""

from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP, localcontext
from math import ceil
from zoneinfo import ZoneInfo

from .schemas import Finding, PublicEpisode


def reconstruct_findings(public):
    PublicEpisode.model_validate(public.model_dump())
    zone = ZoneInfo(public.manifest.timezone)
    start, end = public.manifest.period_start.astimezone(zone), public.manifest.period_end.astimezone(zone)
    rates = {(r.date, r.source_currency, r.target_currency): r for r in public.fx}
    invoice_rows, payment_rows = defaultdict(list), defaultdict(list)
    for row in public.ledger:
        invoice_rows[row.invoice_id].append(row)
        payment_rows[row.payment_id].append(row)

    def belongs(timestamp):
        return start <= timestamp.astimezone(zone) < end

    def converted(amount, currency, timestamp):
        if currency == "KZT":
            return amount, []
        try:
            row = rates[(timestamp.astimezone(zone).date(), currency, "KZT")]
        except KeyError as exc:
            raise ValueError("independent audit: missing directional event-date rate") from exc
        with localcontext() as context:
            context.prec = 80
            source_divisor = 1 if currency == "JPY" else 100
            target = Decimal(amount) / source_divisor * Decimal(str(row.rate)) * 100
            value = int(target.to_integral_value(rounding=ROUND_HALF_UP))
        return value, [row.evidence_id]

    findings = []

    def add(kind, ids, amount, proof):
        if amount <= 0:
            raise ValueError("independent audit: nonpositive discrepancy")
        findings.append(Finding(type=kind, affected_ids=ids, claimed_amount_minor=amount,
                                currency="KZT", evidence_ids=proof, explanation="Supported by final public records."))

    for invoice in public.invoices:
        rows = sorted((r for r in invoice_rows[invoice.invoice_id] if r.entry_kind == "recognition"
                       and r.account == "revenue"), key=lambda r: r.posting_sequence)
        if not rows or len({r.posting_sequence for r in rows}) != len(rows):
            raise ValueError("independent audit: missing or ambiguous recognition sequence")
        if len(rows) > 1:
            add("duplicate_invoice", [invoice.invoice_id], sum(r.credit_minor for r in rows[1:]),
                [invoice.doc_id, *[r.row_id for r in rows]])
        expected, fx = converted(invoice.total_minor, invoice.currency, invoice.service_at)
        for row in rows:
            if row.credit_minor != expected:
                add("fx_conversion", [row.journal_id], abs(row.credit_minor - expected), [invoice.doc_id, row.row_id, *fx])
            if belongs(row.timestamp) != belongs(invoice.service_at):
                add("period_cutoff", [row.journal_id], row.credit_minor, [invoice.doc_id, row.row_id])
    for payment in public.payments:
        if payment.transaction_kind == "refund":
            continue
        rows = payment_rows[payment.payment_id]
        for ref in payment.invoice_refs:
            expected, fx = converted(ref.amount_minor, payment.currency, payment.timestamp)
            applications = [r for r in rows if r.invoice_id == ref.invoice_id and r.entry_kind == "allocation"
                            and r.account == "receivables"]
            actual = sum(r.credit_minor - r.debit_minor for r in applications)
            if actual != expected:
                add("payment_allocation", [payment.payment_id, ref.invoice_id], abs(actual - expected),
                    [payment.doc_id, f"settlement:{payment.payment_id}", *fx])
            for row in applications:
                if belongs(row.timestamp) != belongs(payment.timestamp):
                    add("period_cutoff", [row.journal_id], abs(row.credit_minor - row.debit_minor),
                        [payment.doc_id, row.row_id])
    return findings


def discovery_action_bound(public):
    """List every table at 50/page, open only discrepant settlements, submit.

    Listed rows establish the discrepancy before document inspection; the
    document supplies the public absence/completeness certificate. No truth used.
    """
    pages = sum(max(1, ceil(len(table) / 50)) for table in (public.ledger, public.invoices, public.payments, public.fx))
    payment_ids = {p.payment_id for p in public.payments}
    payments = {next(i for i in f.affected_ids if i in payment_ids)
                for f in reconstruct_findings(public) if f.type == "payment_allocation"}
    return pages + len(payments) + 1


def validate_final_evidence(public, truth, expected_counts=None):
    """Reject unsupported truth, omitted defects, broken proofs or excess budget."""
    findings = reconstruct_findings(public)

    def key(item):
        return item.type, frozenset(item.affected_ids), item.currency

    supported = {key(f): f for f in findings}
    declared = {key(t): t for t in truth.issues}
    if truth.episode_id != public.manifest.episode_id or len(truth.issues) > 12:
        raise ValueError("independent audit: invalid truth envelope")
    if len(supported) != len(findings) or len(declared) != len(truth.issues) or supported.keys() != declared.keys():
        raise ValueError("independent audit: truth targets do not match final public defects")
    available = ({r.row_id for r in public.ledger} | {i.doc_id for i in public.invoices}
                 | {p.doc_id for p in public.payments} | {r.evidence_id for r in public.fx}
                 | {f"settlement:{p.payment_id}" for p in public.payments})
    for target, issue in declared.items():
        finding = supported[target]
        if issue.expected_amount_minor != finding.claimed_amount_minor:
            raise ValueError("independent audit: incorrect discrepancy amount")
        for proof in issue.evidence_sets:
            if not 1 <= len(proof) <= 10 or not set(proof) <= available or not set(finding.evidence_ids) <= set(proof):
                raise ValueError("independent audit: incomplete or inaccessible proof")
    if expected_counts is not None and Counter(t.type for t in truth.issues) != +Counter(expected_counts):
        raise ValueError("independent audit: requested family counts not realized")
    bound = discovery_action_bound(public)
    if bound > 100:
        raise ValueError("independent audit: evidence exceeds the 100-action budget")
    return {"issues": len(findings), "discovery_actions": bound,
            "ledger_rows": len(public.ledger), "documents": public.manifest.document_count}
