"""Version 1 boundary contracts. Public records never contain evaluator fields."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Union
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter,
    field_serializer, field_validator, model_validator,
)


def aware_timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return value


def calendar_date(value):
    if isinstance(value, str):
        value = date.fromisoformat(value)
    if type(value) is not date:
        raise ValueError("expected calendar date")
    return value


def positive_rate(value):
    if not isinstance(value, (str, Decimal)):
        raise ValueError("rate must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal rate") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("rate must be finite and positive")
    return result


Timestamp = Annotated[datetime, BeforeValidator(aware_timestamp)]
CalendarDate = Annotated[date, BeforeValidator(calendar_date)]
Rate = Annotated[Decimal, BeforeValidator(positive_rate)]
ID = Annotated[str, Field(min_length=1)]
Minor = Annotated[int, Field(ge=0)]
Currency = Literal["KZT", "USD", "EUR", "JPY"]
IssueType = Literal["duplicate_invoice", "payment_allocation", "fx_conversion", "period_cutoff"]
CURRENCY_EXPONENTS = {"KZT": 2, "USD": 2, "EUR": 2, "JPY": 0}


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Manifest(StrictModel):
    schema_version: Literal["1.0"]
    episode_id: ID
    base_currency: Literal["KZT"]
    period_start: Timestamp
    period_end: Timestamp
    timezone: str
    record_count: Minor
    document_count: Minor
    currency_exponents: dict[Currency, Minor]
    rounding: Literal["ROUND_HALF_UP"]

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError("unknown timezone") from exc
        return value

    @model_validator(mode="after")
    def valid_period(self):
        if self.period_end <= self.period_start:
            raise ValueError("period_end must follow period_start")
        if self.currency_exponents != CURRENCY_EXPONENTS:
            raise ValueError("unsupported currency exponents")
        return self


class Policy(StrictModel):
    fx_direction: Literal["target_major_per_source_major"]
    invoice_fx_date: Literal["local_service_date"]
    payment_fx_date: Literal["local_payment_date"]
    period_boundary: Literal["start_inclusive_end_exclusive"]
    recognition: Literal["service_at"]
    rounding: Literal["ROUND_HALF_UP"]


class LedgerRow(StrictModel):
    row_id: ID
    journal_id: ID
    timestamp: Timestamp
    account: ID
    debit_minor: Minor
    credit_minor: Minor
    currency: Literal["KZT"]
    entity_id: ID
    invoice_id: ID | None
    payment_id: ID | None
    entry_kind: Literal["recognition", "receipt", "allocation", "refund", "fx_adjustment"]
    posting_sequence: Annotated[int, Field(ge=1)]


class LineItem(StrictModel):
    description: str
    amount_minor: Minor


class Invoice(StrictModel):
    doc_id: ID
    invoice_id: ID
    entity_id: ID
    issued_at: Timestamp
    due_at: Timestamp
    service_at: Timestamp
    currency: Currency
    total_minor: Minor
    line_items: list[LineItem]

    @model_validator(mode="after")
    def line_total(self):
        if sum(line.amount_minor for line in self.line_items) != self.total_minor:
            raise ValueError("invoice lines must sum to total_minor")
        return self


class InvoiceRef(StrictModel):
    invoice_id: ID
    amount_minor: Minor  # directed amount in the payment currency


class Payment(StrictModel):
    doc_id: ID
    payment_id: ID
    timestamp: Timestamp
    currency: Currency
    amount_minor: Minor
    invoice_refs: list[InvoiceRef]
    transaction_kind: Literal["receipt", "refund"]
    original_payment_id: ID | None

    @model_validator(mode="after")
    def valid_directives(self):
        if sum(ref.amount_minor for ref in self.invoice_refs) > self.amount_minor:
            raise ValueError("directives exceed payment amount")
        if (self.transaction_kind == "refund") != (self.original_payment_id is not None):
            raise ValueError("only refunds must reference the original payment")
        if len({ref.invoice_id for ref in self.invoice_refs}) != len(self.invoice_refs):
            raise ValueError("combine directives for the same invoice")
        return self


class FXRow(StrictModel):
    date: CalendarDate
    source_currency: Currency
    target_currency: Currency
    rate: Rate

    @field_serializer("rate")
    def serialize_rate(self, value):
        return str(value)

    @property
    def evidence_id(self) -> str:
        return f"fx:{self.date.isoformat()}:{self.source_currency}:{self.target_currency}"


class SettlementAllocation(StrictModel):
    invoice_id: ID
    applied_minor: int  # signed base currency; refund reversals are negative
    ledger_row_ids: list[ID]


class Settlement(StrictModel):
    evidence_id: ID
    payment_id: ID
    currency: Literal["KZT"]
    received_minor: int
    applied_minor: int
    unapplied_minor: int
    allocations: list[SettlementAllocation]
    ledger_row_ids: list[ID]


class PublicEpisode(StrictModel):
    manifest: Manifest
    policy: Policy
    ledger: list[LedgerRow]
    invoices: list[Invoice]
    payments: list[Payment]
    fx: list[FXRow]

    @model_validator(mode="after")
    def references_and_counts(self):
        if self.manifest.record_count != sum(map(len, (self.ledger, self.invoices, self.payments, self.fx))):
            raise ValueError("record_count must count all four public tables")
        if self.manifest.document_count != len(self.invoices) + len(self.payments):
            raise ValueError("document_count mismatch")
        invoice_ids = {item.invoice_id for item in self.invoices}
        payment_ids = {item.payment_id for item in self.payments}
        groups = ([row.row_id for row in self.ledger],
                  [item.invoice_id for item in self.invoices],
                  [item.payment_id for item in self.payments],
                  [item.doc_id for item in self.invoices + self.payments],
                  [row.evidence_id for row in self.fx])
        if any(len(ids) != len(set(ids)) for ids in groups):
            raise ValueError("duplicate record/document ID")
        for row in self.ledger:
            if row.invoice_id is not None and row.invoice_id not in invoice_ids:
                raise ValueError("dangling invoice link")
            if row.payment_id is not None and row.payment_id not in payment_ids:
                raise ValueError("dangling payment link")
        for payment in self.payments:
            if any(ref.invoice_id not in invoice_ids for ref in payment.invoice_refs):
                raise ValueError("dangling payment directive")
            if payment.original_payment_id is not None and payment.original_payment_id not in payment_ids:
                raise ValueError("dangling refund link")
        return self


class Finding(StrictModel):
    type: IssueType
    affected_ids: Annotated[list[ID], Field(min_length=1)]
    claimed_amount_minor: Minor
    currency: ID  # unknown/wrong currencies are well-formed claims for the matcher
    evidence_ids: Annotated[list[ID], Field(max_length=10)]
    explanation: Annotated[str, Field(max_length=1000)]


class Submission(StrictModel):
    episode_id: ID
    findings: Annotated[list[Finding], Field(max_length=30)]


class TruthIssue(StrictModel):
    issue_id: ID
    type: IssueType
    affected_ids: Annotated[list[ID], Field(min_length=1)]
    expected_amount_minor: Annotated[int, Field(gt=0)]
    currency: Literal["KZT"]
    evidence_sets: Annotated[list[Annotated[list[ID], Field(min_length=1, max_length=10)]], Field(min_length=1)]


class Truth(StrictModel):
    episode_id: ID
    issues: list[TruthIssue]


class Mutation(StrictModel):
    event_id: ID
    object_ids: list[ID]
    operation: Literal["remove", "replace", "insert"]
    field: ID
    clean_value: int | str | None
    observed_value: int | str | None


class Provenance(StrictModel):
    episode_id: ID
    event_ids: list[ID]
    mutations: list[Mutation]


Table = Literal["ledger", "invoices", "payments", "fx"]


class ListRecords(StrictModel):
    type: Literal["list_records"]
    table: Table
    cursor: ID | None
    limit: Annotated[int, Field(ge=1, le=50)]


class GetRecord(StrictModel):
    type: Literal["get_record"]
    table: Table
    id: ID


class GetDocument(StrictModel):
    type: Literal["get_document"]
    doc_id: ID


class Calculator(StrictModel):
    type: Literal["calculator"]
    expression: Annotated[str, Field(min_length=1, max_length=256)]


class Submit(StrictModel):
    type: Literal["submit"]
    findings: Submission


Action = Annotated[Union[ListRecords, GetRecord, GetDocument, Calculator, Submit], Field(discriminator="type")]
ACTION_ADAPTER = TypeAdapter(Action)


class Record(StrictModel):
    id: ID
    record: LedgerRow | Invoice | Payment | FXRow


class RecordPage(StrictModel):
    rows: list[Record]
    next_cursor: ID | None


class PaymentDocument(StrictModel):
    payment: Payment
    settlement: Settlement


class AcceptedSubmission(StrictModel):
    accepted: Literal[True]


class ListReply(StrictModel):
    result: RecordPage
    remaining_steps: Annotated[int, Field(ge=0, le=100)]


class RecordReply(StrictModel):
    result: Record
    remaining_steps: Annotated[int, Field(ge=0, le=100)]


class DocumentReply(StrictModel):
    result: Invoice | PaymentDocument
    remaining_steps: Annotated[int, Field(ge=0, le=100)]


class CalculatorReply(StrictModel):
    result: str  # decimal string, never a binary float
    remaining_steps: Annotated[int, Field(ge=0, le=100)]


class SubmitReply(StrictModel):
    result: AcceptedSubmission
    remaining_steps: Annotated[int, Field(ge=0, le=100)]


class ErrorReply(StrictModel):
    error: ID
    remaining_steps: Annotated[int, Field(ge=0, le=100)]
