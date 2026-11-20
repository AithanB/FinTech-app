# Schema v1.0

Read `audit_env/schemas.py`, then the two `tests/fixtures/company-*/public`
directories. These records are authored by hand, with no company generator.
Each directory is an alternative version of the same episode, not a dataset split.

All models reject extra fields and implicit numeric coercion. Amounts are integer
minor units; booleans, floats and numeric strings are invalid JSON amounts.
KZT/USD/EUR have exponent 2; JPY has exponent 0. Timestamps require explicit
offsets, retained on serialization. FX rates are finite positive decimal strings,
parsed directly as Decimal and serialized back as strings. The wire format never
uses a float for a rate. Python callers can also pass an existing Decimal.

Files are UTF-8; JSONL contains exactly one object per line (blank lines are
invalid). CSV headers follow model field order. CSV integer fields accept only
unsigned decimal digits; nullable links use the reserved token `null`. Empty
cells do not mean null. The literal string `null` cannot be serialized as a link
ID. JSON uses explicit null for missing links; omitting a required nullable field
is an error. Readers preserve row order. `load_public` reads only the six named
public files. Evaluator code loads Truth and Provenance separately. This data
separation is not the process/permission boundary scheduled for stage 05.

`record_count` counts rows across ledger, invoices, payments and FX, excluding
derived settlement views. `document_count` counts invoices plus payments. The
fixture has 6 + 1 + 1 + 3 = 11 records and 2 documents. Public episode validation
checks these counts, lookup uniqueness and linked invoice/payment existence.
The loader requires the complete public episode, including adjacent-period
documents. It does not apply accounting or issue detection rules.

Ledger extensions are `journal_id`, `entry_kind` and `posting_sequence`.
One journal's legs share a sequence; sequence numbers describe business order
independently of file order. Accounts used by settlement are `cash`,
`unapplied_receipts` and `receivables`. Recognition uses `receivables` and
`revenue`. Invoice `service_at` establishes recognition. `line_items` contain
description and amount_minor and must sum to total_minor. Payment `invoice_refs`
contain invoice_id and amount_minor in payment currency. Their sum cannot exceed
the payment. Refund amounts are positive in documents; transaction_kind=refund
requires original_payment_id. Reversing ledger legs carry the accounting sign.

## Lookup and evidence IDs

- Ledger lookup/evidence: row_id. journal_id groups legs and can identify an
  affected object, but is not itself row evidence.
- Invoice lookup: invoice_id. Evidence/document lookup: doc_id.
- Payment lookup: payment_id. Evidence/document lookup: doc_id.
- FX lookup/evidence: `fx:YYYY-MM-DD:SOURCE:TARGET`, derived from its directional
  date/currency key; the CSV retains the organizer's four columns.
- Payment settlement evidence: `settlement:PAYMENT_ID`. Both fixtures use
  `settlement:pay-627`, because it identifies the same public business object.

List results wrap each raw record as `{id, record}` so the lookup key is always
discoverable, including FX. Payment get_document replies contain
`{payment, settlement}`. Invoice replies contain the invoice. Settlement evidence
IDs are discoverable in that view and may prove absent allocations without
requiring nonexistent ledger rows. Manifest/policy are common public context.

## Settlement view

`audit_env/views.py` derives the view from final public rows for a payment,
without truth, provenance or seeds. `received_minor` sums cash debits minus
credits. Per-invoice `applied_minor` sums receivables credits minus debits for
allocation/refund entries; `unapplied_minor = received_minor - applied_minor`.
These amounts use base KZT and are signed so refund reversals work. FX adjustment
entries are not payment applications. Each invoice directive appears even if no
application row exists. The view lists contributing row IDs and always has an
evidence_id. It covers the complete final ledger, including later postings.

This is a factual view, without a correctness flag or private intended history.
Compare it with the payment's public invoice_refs to establish a discrepancy.

## Worked calculation and expected answer

Company A: inv-264 totals 10,000,000 minor units (100,000 KZT). pay-627 directs
7,000,000 (70,000 KZT) to it. Its books apply 7,000,000, leaving 3,000,000
(30,000 KZT) receivable. The independently authored expected submission is empty.

Company B: the same payment directs 7,000,000, but rows row-957 and row-268 apply
5,000,000. Cash remains 7,000,000 and unapplied receipts retain 2,000,000.
Outstanding receivables are now 5,000,000; only 2,000,000 is an allocation error.
Both versions balance by journal. The complete expected finding is in
`tests/fixtures/company-b/private/expected_submission.json`: payment_allocation,
affected_ids `["pay-627", "inv-264"]`, claimed_amount_minor 2000000, currency KZT,
evidence_ids `["doc-492", "settlement:pay-627"]`, plus a short explanation.
Truth and provenance are separate evaluator fixtures. No generator or scorer
was used to calculate this answer.

## Action examples

`tests/fixtures/action-examples.json` publishes one request and reply for each
of list_records, get_record, get_document, calculator and submit. They form a
five-action illustrative sequence on company B, with budgets 99 through 95.
Tests validate all requests and replies against the boundary models. Submit
contains the entire Submission envelope in its findings argument; its reply
acknowledges structural acceptance without giving scoring diagnostics.

These are contract examples. Executable tools, cursor handling, arithmetic parsing,
episode transitions and transport rewards arrive in stage 04. The example cursor
`ledger:1` illustrates a continuation token; clients must treat cursors as opaque.
Limits are 50 rows per page, 30 findings, 10 evidence IDs and 1,000 explanation
characters. Unknown IDs/currencies in structurally valid findings are left for
stage 03 matching, rather than rejected as a malformed envelope.
