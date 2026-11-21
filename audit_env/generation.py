"""Seeded event history, directional FX, balanced books, then causal mutations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path
import random
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from .accounting import applicable_fx, base_amount, convert_minor, in_period, local_date

from .schemas import (
    CURRENCY_EXPONENTS, CalendarDate, Currency, FXRow, ID, Invoice, InvoiceRef, LedgerRow, LineItem, Manifest, Rate,
    Mutation, Payment, Policy, Provenance, PublicEpisode, StrictModel, Timestamp,
    Truth, TruthIssue,
)
from .serialization import save_public, write_json
from .views import settlement_view


class ScenarioConfig(StrictModel):
    count: Annotated[int, Field(ge=1, le=6)] = 1
    variant: Literal["clean", "a_only", "b_only", "both"] = "both"

    def consumes(self, side):
        return self.count if self.variant in (side + "_only", "both") else 0


class GeneratorConfig(StrictModel):
    version: Literal["stage06-v1", "stage07-v1", "stage08-v1"] = "stage06-v1"
    invoice_count: Annotated[int, Field(ge=4, le=100)] = 6
    duplicate_invoices: Annotated[int, Field(ge=0)] = 0
    missing_allocations: Annotated[int, Field(ge=0)] = 0
    partial_allocations: Annotated[int, Field(ge=0)] = 0
    wrong_fx_dates: Annotated[int, Field(ge=0)] = 0
    wrong_fx_rates: Annotated[int, Field(ge=0)] = 0
    misplaced_recognitions: Annotated[int, Field(ge=0)] = 0
    currencies: Annotated[list[Currency], Field(min_length=1)] = ["KZT"]
    timezone: str = "Asia/Almaty"
    boundary_cases: bool = False
    amount_min_minor: Annotated[int, Field(ge=100)] = 10_000_000
    amount_max_minor: Annotated[int, Field(ge=100)] = 20_000_000
    partial_shortfall_minor: Annotated[int, Field(gt=0)] = 2_000_000
    misplaced_applications: Annotated[int, Field(ge=0)] = 0
    boundary_scenario: ScenarioConfig | None = None
    duplicate_fx_scenario: ScenarioConfig | None = None
    size_profile: Literal["tiny", "small", "large"] = "tiny"
    fx_profile: Literal["daily", "flat"] = "daily"

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError("unknown timezone") from exc
        return value

    @model_validator(mode="after")
    def possible(self):
        if self.amount_max_minor < self.amount_min_minor:
            raise ValueError("amount range reversed")
        if self.duplicate_invoices > self.invoice_count:
            raise ValueError("too many duplicate targets")
        if self.missing_allocations + self.partial_allocations > self.invoice_count:
            raise ValueError("too many allocation targets; refunded receipts are protected")
        if (self.duplicate_invoices + self.missing_allocations + self.partial_allocations
                + self.wrong_fx_dates + self.wrong_fx_rates + self.misplaced_recognitions + self.misplaced_applications) > 12:
            raise ValueError("at most 12 issues")
        if len(set(self.currencies)) != len(self.currencies):
            raise ValueError("currencies must be distinct")
        foreign_count = sum(self.currencies[(i // 2 if self.version == "stage08-v1" else i) % len(self.currencies)] != "KZT" for i in range(self.invoice_count))
        if self.wrong_fx_dates + self.wrong_fx_rates > foreign_count:
            raise ValueError("too few foreign recognition targets")
        if self.misplaced_recognitions > self.invoice_count:
            raise ValueError("too many period targets")
        if self.version == "stage06-v1" and (self.currencies != ["KZT"] or self.timezone != "Asia/Almaty"
                or self.boundary_cases or self.wrong_fx_dates or self.wrong_fx_rates or self.misplaced_recognitions):
            raise ValueError("FX, timezone and period options require stage07-v1")
        if self.version != "stage08-v1" and (self.misplaced_applications or self.boundary_scenario
                or self.duplicate_fx_scenario or self.size_profile != "tiny" or self.fx_profile != "daily"):
            raise ValueError("composition and size options require stage08-v1")
        if self.version == "stage08-v1":
            if self.invoice_count > 99:
                raise ValueError("at most 99 invoices within the 200-document limit")
            for scenario, a_count, b_count in (
                (self.boundary_scenario, self.partial_allocations, self.misplaced_applications),
                (self.duplicate_fx_scenario, self.duplicate_invoices, self.wrong_fx_rates),
            ):
                if scenario and (scenario.consumes("a") > a_count or scenario.consumes("b") > b_count):
                    raise ValueError("scenario must consume the configured family counts")
        return self


class SaleEvent(StrictModel):
    event_id: ID
    invoice_id: ID
    doc_id: ID
    entity_id: ID
    timestamp: Timestamp
    currency: Currency = "KZT"
    amount_minor: Annotated[int, Field(gt=0)]
    description: str


class CashEvent(StrictModel):
    event_id: ID
    payment_id: ID
    doc_id: ID
    invoice_id: ID
    timestamp: Timestamp
    currency: Currency = "KZT"
    amount_minor: Annotated[int, Field(gt=0)]
    transaction_kind: Literal["receipt", "refund"]
    original_payment_id: ID | None


class FXDecision(StrictModel):
    event_id: ID
    journal_id: ID
    variant: Literal["date", "rate"]
    required_date: CalendarDate
    used_date: CalendarDate
    required_rate: Rate
    used_rate: Rate


class History(StrictModel):
    version: Literal["stage06-v1", "stage07-v1", "stage08-v1"]
    seed: int
    config: GeneratorConfig
    sales: list[SaleEvent]
    cash_events: list[CashEvent]
    fx_decisions: list[FXDecision] = []


class GeneratedEpisode(StrictModel):
    public: PublicEpisode
    clean: PublicEpisode
    truth: Truth
    provenance: Provenance
    history: History


def _rng(seed, stream):
    digest = hashlib.sha256(f"stage06-v1:{seed}:{stream}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


class _IDs:
    def __init__(self, rng):
        self.rng = rng
        self.used = set()

    def new(self, kind):
        while True:
            value = f"{kind}-{self.rng.getrandbits(96):024x}"
            if value not in self.used:
                self.used.add(value)
                return value


def _history(seed, config, ids):
    rng = _rng(seed, "business")
    start = datetime(2026, 11, 1, 9, tzinfo=ZoneInfo(config.timezone))
    sales, cash = [], []
    recurring_amount = rng.randint(config.amount_min_minor, config.amount_max_minor)
    entity = ids.new("entity")
    for index in range(config.invoice_count):
        # Distinct documents with a recurring amount are valid business events.
        amount = recurring_amount if index < 2 else rng.randint(config.amount_min_minor, config.amount_max_minor)
        when = start + timedelta(days=index % 15, hours=rng.randrange(3))
        if config.boundary_cases and index < 4:
            boundary = start.replace(hour=0)
            when = [boundary + timedelta(minutes=30), boundary.replace(month=12) - timedelta(microseconds=1),
                    boundary.replace(month=12), boundary - timedelta(microseconds=1)][index]
        sale = SaleEvent(
            event_id=ids.new("event"), invoice_id=ids.new("inv"), doc_id=ids.new("doc"),
            entity_id=entity if index < 2 else ids.new("entity"), timestamp=when,
            amount_minor=amount, currency=config.currencies[index % len(config.currencies)],
            description=f"Synthetic service {rng.randrange(1000, 9999)}",
        )
        sales.append(sale)
        received = amount * 70 // 100  # A legitimate partial receipt, not a defect.
        portions = [received // 2, received - received // 2] if index == 0 else [received]
        for number, portion in enumerate(portions):
            cash.append(CashEvent(
                event_id=ids.new("event"), payment_id=ids.new("pay"), doc_id=ids.new("doc"),
                invoice_id=sale.invoice_id, timestamp=when + timedelta(days=2, hours=number),
                amount_minor=portion, currency=sale.currency, transaction_kind="receipt", original_payment_id=None,
            ))
        if index == 2:
            original = cash[-1]
            cash.append(CashEvent(
                event_id=ids.new("event"), payment_id=ids.new("pay"), doc_id=ids.new("doc"),
                invoice_id=sale.invoice_id, timestamp=when + timedelta(days=4),
                amount_minor=received // 4, transaction_kind="refund",
                currency=sale.currency,
                original_payment_id=original.payment_id,
            ))
    return History(version=config.version, seed=seed, config=config, sales=sales, cash_events=cash)


def _derive(history, ids):
    invoices, payments, ledger = [], [], []
    sequence = defaultdict(int)
    entities = {sale.invoice_id: sale.entity_id for sale in history.sales}
    config = history.config
    # Keep the legacy public episode identity stable for existing stage06-v1
    # configs. New options are versioned and included in stage07-v1 identity.
    excluded = {"misplaced_applications", "boundary_scenario", "duplicate_fx_scenario", "size_profile", "fx_profile"} if config.version != "stage08-v1" else set()
    if config.version == "stage06-v1":
        excluded |= {"wrong_fx_dates", "wrong_fx_rates", "misplaced_recognitions", "currencies", "timezone", "boundary_cases"}
    identity_config = config.model_dump_json(exclude=excluded)
    start = datetime(2026, 11, 1, tzinfo=ZoneInfo(config.timezone))
    # Required local event dates plus an adjacent published date for wrong-date
    # candidates. Rates are directional target-major/source-major decimal values.
    keys = {(local_date(e.timestamp, config.timezone) - timedelta(days=offset), e.currency)
            for e in [*history.sales, *history.cash_events] if e.currency != "KZT" for offset in (0, 1)}
    rates = {"USD": (Decimal("500"), Decimal("10")), "EUR": (Decimal("550"), Decimal("11")),
             "JPY": (Decimal("3.2"), Decimal("0.01"))}
    if config.version == "stage08-v1":
        rates = {currency: (base, Decimal(0) if config.fx_profile == "flat" else change / 10)
                 for currency, (base, change) in rates.items()}
    fx = [FXRow(date=date, source_currency=currency, target_currency="KZT",
                rate=rates[currency][0] + rates[currency][1] * (date - start.date()).days)
          for date, currency in sorted(keys)]
    fx_index = {(r.date, r.source_currency): r.rate for r in fx}

    def amount(event):
        rate = fx_index[(local_date(event.timestamp, config.timezone), event.currency)] if event.currency != "KZT" else "1"
        return convert_minor(event.amount_minor, event.currency, "KZT", rate)

    def journal(invoice_id, payment_id, when, kind, amount, debit, credit):
        sequence[invoice_id] += 1
        journal_id = ids.new("journal")
        for account, dr, cr in ((debit, amount, 0), (credit, 0, amount)):
            ledger.append(LedgerRow(
                row_id=ids.new("row"), journal_id=journal_id, timestamp=when,
                account=account, debit_minor=dr, credit_minor=cr, currency="KZT",
                entity_id=entities[invoice_id], invoice_id=invoice_id,
                payment_id=payment_id, entry_kind=kind, posting_sequence=sequence[invoice_id],
            ))

    for sale in history.sales:
        first_line = sale.amount_minor // 2
        invoices.append(Invoice(
            doc_id=sale.doc_id, invoice_id=sale.invoice_id, entity_id=sale.entity_id,
            issued_at=sale.timestamp if config.version == "stage06-v1" else sale.timestamp - timedelta(hours=1),
            due_at=sale.timestamp + timedelta(days=30), service_at=sale.timestamp,
            currency=sale.currency, total_minor=sale.amount_minor,
            line_items=[LineItem(description=sale.description, amount_minor=first_line),
                        LineItem(description="Synthetic support", amount_minor=sale.amount_minor - first_line)],
        ))
        journal(sale.invoice_id, None, sale.timestamp, "recognition", amount(sale), "receivables", "revenue")
    for event in history.cash_events:
        payments.append(Payment(
            doc_id=event.doc_id, payment_id=event.payment_id, timestamp=event.timestamp,
            currency=event.currency, amount_minor=event.amount_minor,
            invoice_refs=[InvoiceRef(invoice_id=event.invoice_id, amount_minor=event.amount_minor)],
            transaction_kind=event.transaction_kind, original_payment_id=event.original_payment_id,
        ))
        if event.transaction_kind == "receipt":
            journal(event.invoice_id, event.payment_id, event.timestamp, "receipt", amount(event), "cash", "unapplied_receipts")
            journal(event.invoice_id, event.payment_id, event.timestamp, "allocation", amount(event), "unapplied_receipts", "receivables")
        else:
            # Reverse the application, then refund cash. The refund's own
            # settlement is signed negative; the original receipt stays intact.
            journal(event.invoice_id, event.payment_id, event.timestamp, "refund", amount(event), "receivables", "unapplied_receipts")
            journal(event.invoice_id, event.payment_id, event.timestamp, "refund", amount(event), "unapplied_receipts", "cash")
    return PublicEpisode(
        manifest=Manifest(
            schema_version="1.0",
            episode_id=_IDs(_rng(history.seed, "episode:" + identity_config)).new("ep"),
            base_currency="KZT",
            period_start=start, period_end=start.replace(month=12), timezone=config.timezone,
            record_count=len(ledger) + len(invoices) + len(payments) + len(fx),
            document_count=len(invoices) + len(payments), currency_exponents=CURRENCY_EXPONENTS,
            rounding="ROUND_HALF_UP",
        ),
        policy=Policy(
            fx_direction="target_major_per_source_major", invoice_fx_date="local_service_date",
            payment_fx_date="local_payment_date", period_boundary="start_inclusive_end_exclusive",
            recognition="service_at", rounding="ROUND_HALF_UP",
        ), ledger=ledger, invoices=invoices, payments=payments, fx=fx,
    )


def validate_accounting(episode, *, clean=False):
    """Trusted checks independent of mutation selection; no truth input."""
    PublicEpisode.model_validate(episode.model_dump())
    # Missing rates are invalid input, even for a mutated company; never truth.
    for invoice in episode.invoices:
        applicable_fx(episode, invoice.currency, invoice.service_at)
    for payment in episode.payments:
        applicable_fx(episode, payment.currency, payment.timestamp)
    journals = defaultdict(list)
    for row in episode.ledger:
        journals[row.journal_id].append(row)
    for rows in journals.values():
        if len(rows) != 2 or sum(r.debit_minor for r in rows) != sum(r.credit_minor for r in rows):
            raise ValueError("unbalanced journal")
        if any((r.debit_minor > 0) == (r.credit_minor > 0) for r in rows):
            raise ValueError("posting must have one positive leg")
        if len({(r.invoice_id, r.payment_id, r.currency, r.timestamp, r.entry_kind, r.posting_sequence) for r in rows}) != 1:
            raise ValueError("incoherent journal")
    if not clean:
        return
    for invoice in episode.invoices:
        recognition = [r for r in episode.ledger if r.invoice_id == invoice.invoice_id and r.entry_kind == "recognition" and r.account == "revenue"]
        if len(recognition) != 1 or recognition[0].credit_minor != base_amount(episode, invoice.total_minor, invoice.currency, invoice.service_at):
            raise ValueError("recognition does not match invoice")
        if in_period(recognition[0].timestamp, episode.manifest) != in_period(invoice.service_at, episode.manifest):
            raise ValueError("recognition in wrong reporting period")
        balance = sum(r.debit_minor - r.credit_minor for r in episode.ledger if r.invoice_id == invoice.invoice_id and r.account == "receivables")
        if balance < 0:
            raise ValueError("receipt exceeds receivable")
    by_id = {p.payment_id: p for p in episode.payments}
    refunds = defaultdict(int)
    for payment in episode.payments:
        sign = -1 if payment.transaction_kind == "refund" else 1
        view = settlement_view(payment, episode.ledger)
        if view.received_minor != sign * base_amount(episode, payment.amount_minor, payment.currency, payment.timestamp) or view.unapplied_minor != 0:
            raise ValueError("cash or allocation invariant failed")
        intended = {ref.invoice_id: sign * base_amount(episode, ref.amount_minor, payment.currency, payment.timestamp) for ref in payment.invoice_refs}
        if {a.invoice_id: a.applied_minor for a in view.allocations} != intended:
            raise ValueError("directed application mismatch")
        if sign == -1:
            original = by_id[payment.original_payment_id]
            if original.transaction_kind != "receipt" or payment.timestamp < original.timestamp or payment.invoice_refs[0].invoice_id != original.invoice_refs[0].invoice_id:
                raise ValueError("invalid refund reference")
            refunds[original.payment_id] += payment.amount_minor
            if refunds[original.payment_id] > original.amount_minor:
                raise ValueError("refund exceeds original receipt")


def generate_episode(seed: int, config: GeneratorConfig | dict | None = None) -> GeneratedEpisode:
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    config = config if isinstance(config, GeneratorConfig) else GeneratorConfig.model_validate({} if config is None else config)
    if config.version == "stage08-v1":
        from .composition import generate_composed

        return generate_composed(seed, config)
    ids = _IDs(_rng(seed, "identifiers"))
    history = _history(seed, config, ids)
    clean = _derive(history, ids)
    validate_accounting(clean, clean=True)  # Mandatory gate BEFORE any mutation.
    ledger = list(clean.ledger)
    mutations, issues = [], []
    rng = _rng(seed, "mutations")
    refunded = {p.original_payment_id for p in clean.payments if p.transaction_kind == "refund"}
    candidates = [p for p in clean.payments if p.transaction_kind == "receipt" and p.payment_id not in refunded]
    rng.shuffle(candidates)
    # Reserve eligible partial targets first. Missing applications can use any
    # remaining receipt, so selection must not reject a feasible combination.
    intended = {p.payment_id: base_amount(clean, p.invoice_refs[0].amount_minor, p.currency, p.timestamp) for p in candidates}
    partial_candidates = [p for p in candidates if intended[p.payment_id] > config.partial_shortfall_minor]
    if len(partial_candidates) < config.partial_allocations:
        raise ValueError("partial shortfall must leave a positive application")
    partial = partial_candidates[:config.partial_allocations]
    missing = [p for p in candidates if p not in partial][:config.missing_allocations]
    selected = [(p, 0) for p in missing] + [(p, intended[p.payment_id] - config.partial_shortfall_minor) for p in partial]
    event_by_payment = {event.payment_id: event.event_id for event in history.cash_events}
    for payment, applied in selected:
        original_rows = [r for r in ledger if r.payment_id == payment.payment_id and r.entry_kind == "allocation"]
        for row in original_rows:
            ledger.remove(row)
            updated = row.model_copy(update={"debit_minor": applied if row.debit_minor else 0, "credit_minor": applied if row.credit_minor else 0}) if applied else None
            if updated:
                ledger.append(updated)
            mutations.append(Mutation(
                event_id=event_by_payment[payment.payment_id], object_ids=[row.row_id],
                operation="replace" if updated else "remove", field="ledger_row",
                clean_value=row.model_dump_json(), observed_value=updated.model_dump_json() if updated else None,
            ))
        # Reconstruct the claim against FINAL public ledger, not the requested knob.
        actual = settlement_view(payment, ledger).allocations[0].applied_minor
        required_fx = applicable_fx(clean, payment.currency, payment.timestamp)
        issues.append(TruthIssue(
            issue_id=ids.new("issue"), type="payment_allocation",
            affected_ids=[payment.payment_id, payment.invoice_refs[0].invoice_id],
            expected_amount_minor=abs(intended[payment.payment_id] - actual),
            currency="KZT", evidence_sets=[[payment.doc_id, f"settlement:{payment.payment_id}",
                                           *([required_fx.evidence_id] if required_fx else [])]],
        ))
    sales_by_invoice = {s.invoice_id: s for s in history.sales}
    for invoice in rng.sample(clean.invoices, config.duplicate_invoices):
        originals = [r for r in clean.ledger if r.invoice_id == invoice.invoice_id and r.entry_kind == "recognition"]
        journal_id = ids.new("journal")
        sequence = max(r.posting_sequence for r in ledger if r.invoice_id == invoice.invoice_id) + 1
        when = max(r.timestamp for r in ledger if r.invoice_id == invoice.invoice_id) + timedelta(minutes=1)
        if config.version == "stage07-v1":
            when = originals[0].timestamp  # Sequence identifies the extra; do not create an undeclared cutoff.
        extra = [r.model_copy(update={"row_id": ids.new("row"), "journal_id": journal_id, "posting_sequence": sequence, "timestamp": when}) for r in originals]
        ledger.extend(extra)
        for row in extra:
            mutations.append(Mutation(
                event_id=sales_by_invoice[invoice.invoice_id].event_id, object_ids=[row.row_id],
                operation="insert", field="ledger_row", clean_value=None, observed_value=row.model_dump_json(),
            ))
        revenue = [r for r in ledger if r.invoice_id == invoice.invoice_id and r.entry_kind == "recognition" and r.account == "revenue"]
        ordered = sorted(revenue, key=lambda r: r.posting_sequence)
        issues.append(TruthIssue(
            issue_id=ids.new("issue"), type="duplicate_invoice", affected_ids=[invoice.invoice_id],
            expected_amount_minor=sum(r.credit_minor for r in ordered[1:]), currency="KZT",
            evidence_sets=[[invoice.doc_id, *[r.row_id for r in ordered]]],
        ))
    # FX mutations target distinct original recognition journals. Evaluate every
    # candidate AFTER final rounding, skipping ones that would publish no change.
    foreign = [i for i in clean.invoices if i.currency != "KZT"]
    rng.shuffle(foreign)
    used_fx, fx_targets, fx_decisions = set(), [], []

    def replace_journal(original, updates, event_id):
        for row in list(ledger):
            if row.journal_id != original.journal_id:
                continue
            updated = row.model_copy(update=updates(row))
            ledger[ledger.index(row)] = updated
            mutations.append(Mutation(event_id=event_id, object_ids=[row.row_id], operation="replace",
                                      field="ledger_row", clean_value=row.model_dump_json(),
                                      observed_value=updated.model_dump_json()))

    for variant, count in (("date", config.wrong_fx_dates), ("rate", config.wrong_fx_rates)):
        if not count:
            continue
        eligible = []
        for invoice in foreign:
            if invoice.invoice_id in used_fx:
                continue
            required = applicable_fx(clean, invoice.currency, invoice.service_at)
            wrong_rate = required.rate * Decimal("0.98")
            if variant == "date":
                wrong_rate = next(r.rate for r in clean.fx if r.source_currency == invoice.currency
                                  and r.date == required.date - timedelta(days=1))
            posted = convert_minor(invoice.total_minor, invoice.currency, "KZT", wrong_rate)
            expected = base_amount(clean, invoice.total_minor, invoice.currency, invoice.service_at)
            if posted > 0 and posted != expected:
                eligible.append((invoice, posted, required, wrong_rate))
        if len(eligible) < count:
            raise ValueError("too few FX mutations change the published rounded amount")
        for invoice, posted, required, wrong_rate in eligible[:count]:
            original = next(r for r in clean.ledger if r.invoice_id == invoice.invoice_id
                            and r.entry_kind == "recognition" and r.account == "revenue")
            replace_journal(original, lambda r: {"debit_minor": posted if r.debit_minor else 0,
                                                "credit_minor": posted if r.credit_minor else 0},
                            sales_by_invoice[invoice.invoice_id].event_id)
            used_fx.add(invoice.invoice_id)
            fx_targets.append((invoice, original.journal_id))
            fx_decisions.append(FXDecision(
                event_id=sales_by_invoice[invoice.invoice_id].event_id, journal_id=original.journal_id,
                variant=variant, required_date=required.date,
                used_date=required.date - timedelta(days=1) if variant == "date" else required.date,
                required_rate=required.rate, used_rate=wrong_rate,
            ))

    period_targets = []
    for invoice in rng.sample(clean.invoices, config.misplaced_recognitions):
        original = next(r for r in clean.ledger if r.invoice_id == invoice.invoice_id
                        and r.entry_kind == "recognition" and r.account == "revenue")
        # Move across the selected reporting period, retaining both sides' data.
        when = clean.manifest.period_end if in_period(invoice.service_at, clean.manifest) else clean.manifest.period_start
        replace_journal(original, lambda r: {"timestamp": when}, sales_by_invoice[invoice.invoice_id].event_id)
        period_targets.append((invoice, original.journal_id))

    # New-family proofs and amounts are derived from FINAL rows after all edits.
    for family, targets in (("fx_conversion", fx_targets), ("period_cutoff", period_targets)):
        for invoice, journal_id in targets:
            row = next(r for r in ledger if r.journal_id == journal_id and r.account == "revenue")
            proof = [invoice.doc_id, row.row_id]
            if family == "fx_conversion":
                required = applicable_fx(clean, invoice.currency, invoice.service_at)
                proof.append(required.evidence_id)
                discrepancy = abs(base_amount(clean, invoice.total_minor, invoice.currency, invoice.service_at) - row.credit_minor)
            else:
                discrepancy = row.credit_minor
            issues.append(TruthIssue(issue_id=ids.new("issue"), type=family, affected_ids=[journal_id],
                                     expected_amount_minor=discrepancy, currency="KZT", evidence_sets=[proof]))
    # Stable seeded permutations hide selection/insertion order, without using
    # the mutation RNG. IDs never contain an issue label or the seed.
    order_rng = _rng(seed, "ordering")
    invoices, payments = list(clean.invoices), list(clean.payments)
    fx = list(clean.fx)
    for table in (ledger, invoices, payments, fx):
        order_rng.shuffle(table)
    manifest = clean.manifest.model_copy(update={"record_count": len(ledger) + len(invoices) + len(payments) + len(fx)})
    public = PublicEpisode(manifest=manifest, policy=clean.policy, ledger=ledger, invoices=invoices, payments=payments, fx=fx)
    validate_accounting(public)
    history = history.model_copy(update={"fx_decisions": fx_decisions})
    return GeneratedEpisode(
        public=public, clean=clean, history=history,
        truth=Truth(episode_id=manifest.episode_id, issues=issues),
        provenance=Provenance(episode_id=manifest.episode_id,
                              event_ids=[s.event_id for s in history.sales] + [e.event_id for e in history.cash_events], mutations=mutations),
    )


def save_generated(directory: Path, episode: GeneratedEpisode):
    """Trusted export: standard public files and owner-only evaluator material."""
    directory = Path(directory)
    # A new destination prevents stale output from a different configuration.
    directory.mkdir(parents=True, exist_ok=False)
    save_public(directory / "public", episode.public)
    private = directory / "private"
    private.mkdir(mode=0o700)
    for name, model in (("truth", episode.truth), ("provenance", episode.provenance), ("history", episode.history), ("clean", episode.clean)):
        path = private / f"{name}.json"
        write_json(path, model)
        path.chmod(0o600)
    for path in (directory / "public").iterdir():
        path.chmod(0o444)
