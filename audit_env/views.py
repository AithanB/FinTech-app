"""Public settlement evidence, calculated solely from final ledger records."""

from .schemas import LedgerRow, Payment, Settlement, SettlementAllocation


def settlement_view(payment: Payment, ledger: list[LedgerRow]) -> Settlement:
    rows = [row for row in ledger if row.payment_id == payment.payment_id]
    received = sum(row.debit_minor - row.credit_minor for row in rows if row.account == "cash")
    applied_rows = [row for row in rows if row.account == "receivables" and row.entry_kind in ("allocation", "refund")]
    invoice_ids = sorted({ref.invoice_id for ref in payment.invoice_refs} | {row.invoice_id for row in applied_rows if row.invoice_id is not None})
    allocations = [SettlementAllocation(
        invoice_id=invoice_id,
        applied_minor=sum(row.credit_minor - row.debit_minor for row in applied_rows if row.invoice_id == invoice_id),
        ledger_row_ids=[row.row_id for row in applied_rows if row.invoice_id == invoice_id],
    ) for invoice_id in invoice_ids]
    applied = sum(item.applied_minor for item in allocations)
    return Settlement(
        evidence_id=f"settlement:{payment.payment_id}", payment_id=payment.payment_id,
        currency="KZT", received_minor=received, applied_minor=applied,
        unapplied_minor=received - applied, allocations=allocations,
        ledger_row_ids=[row.row_id for row in rows],
    )
