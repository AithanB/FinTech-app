"""Stage 08 business variation and explicit interacting mutation plans."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .accounting import applicable_fx, base_amount, convert_minor, in_period
from .generation import (
    CashEvent, FXDecision, GeneratedEpisode, GeneratorConfig, History, SaleEvent,
    _IDs, _derive, _rng, validate_accounting,
)
from .schemas import Mutation, Provenance, PublicEpisode, Truth, TruthIssue
from .validation import validate_final_evidence
from .views import settlement_view


COUNTS = ("duplicate_invoices", "missing_allocations", "partial_allocations", "wrong_fx_dates",
          "wrong_fx_rates", "misplaced_recognitions", "misplaced_applications")


def _history(seed, config, ids):
    rng = _rng(seed, "stage08:business")
    zone = ZoneInfo(config.timezone)
    start = datetime(2026, 11, 1, tzinfo=zone)
    sales, cash = [], []
    split_index, refund_index = rng.sample(range(config.invoice_count), 2)
    recurring = rng.randint(config.amount_min_minor, config.amount_max_minor)
    recurring_entity = ids.new("entity")
    names = [f"{a} {b}" for a in ("Aspen", "Cedar", "Lumen", "Maple", "Orion", "Willow")
             for b in ("Studio", "Works", "Labs", "Services")]
    for index in range(config.invoice_count):
        currency = config.currencies[(index // 2) % len(config.currencies)]
        amount = recurring if index < 2 else rng.randint(config.amount_min_minor, config.amount_max_minor)
        when = start + timedelta(days=rng.randrange(24), hours=rng.randrange(9, 18), minutes=rng.randrange(60))
        if config.boundary_cases and index < 4:
            when = [start + timedelta(minutes=30), start.replace(month=12) - timedelta(microseconds=1),
                    start.replace(month=12), start - timedelta(microseconds=1)][index]
        sale = SaleEvent(event_id=ids.new("event"), invoice_id=ids.new("inv"), doc_id=ids.new("doc"),
                         entity_id=recurring_entity if index < 2 else ids.new("entity"),
                         timestamp=when, currency=currency, amount_minor=amount,
                         description=f"{rng.choice(names)}: {rng.choice(['support', 'design', 'maintenance', 'consulting'])}")
        sales.append(sale)
        # Foreign receipts remain below face value despite daily FX variation.
        fraction = rng.choice((30, 50, 70, 100) if currency == "KZT" else (30, 50, 70))
        received = amount * fraction // 100
        first = max(1, received * rng.randrange(25, 76) // 100)
        portions = [first, received - first] if index == split_index else [received]
        for number, portion in enumerate(portions):
            cash.append(CashEvent(event_id=ids.new("event"), payment_id=ids.new("pay"), doc_id=ids.new("doc"),
                                  invoice_id=sale.invoice_id, timestamp=when + timedelta(days=2, hours=number),
                                  currency=currency, amount_minor=portion, transaction_kind="receipt", original_payment_id=None))
        if index == refund_index:
            original = cash[-1]
            cash.append(CashEvent(event_id=ids.new("event"), payment_id=ids.new("pay"), doc_id=ids.new("doc"),
                                  invoice_id=sale.invoice_id, timestamp=when + timedelta(days=4), currency=currency,
                                  amount_minor=max(1, received // 4), transaction_kind="refund", original_payment_id=original.payment_id))

    # Target selection is independent of enabled sides, preserving the same
    # clean business and boundary controls across all four paired variants.
    select = _rng(seed, "stage08:scenario_targets")
    refunded = {p.original_payment_id for p in cash if p.transaction_kind == "refund"}
    sales_by_id = {s.invoice_id: s for s in sales}
    eligible = [p for p in cash if p.currency != "KZT" and p.transaction_kind == "receipt"
                and p.payment_id not in refunded and start <= sales_by_id[p.invoice_id].timestamp < start.replace(month=12) - timedelta(days=2)]
    select.shuffle(eligible)
    boundary, used_invoices = [], set()
    for payment in eligible:
        if config.boundary_scenario is None or len(boundary) == config.boundary_scenario.count:
            break
        if payment.invoice_id not in used_invoices:
            boundary.append(payment.payment_id)
            used_invoices.add(payment.invoice_id)
    if config.boundary_scenario and len(boundary) != config.boundary_scenario.count:
        raise ValueError("too few distinct foreign non-refunded boundary targets")
    # Boundary payment is a legitimate ordinary partial receipt on November 30.
    cash = [p.model_copy(update={"timestamp": start.replace(month=12) - timedelta(minutes=30)})
            if p.payment_id in boundary else p for p in cash]
    foreign = [s.invoice_id for s in sales if s.currency != "KZT" and s.invoice_id not in used_invoices]
    select.shuffle(foreign)
    duplicates = foreign[:config.duplicate_fx_scenario.count] if config.duplicate_fx_scenario else []
    if config.duplicate_fx_scenario and len(duplicates) != config.duplicate_fx_scenario.count:
        raise ValueError("too few distinct foreign duplicate/FX targets")
    history = History(version=config.version, seed=seed, config=config, sales=sales, cash_events=cash)
    return history, boundary, duplicates


def generate_composed(seed, config):
    ids = _IDs(_rng(seed, "stage08:identifiers"))
    history, boundary_ids, duplicate_ids = _history(seed, config, ids)
    clean = _derive(history, ids)
    validate_accounting(clean, clean=True)
    ledger, mutations, targets, fx_decisions = list(clean.ledger), [], [], []
    rng = _rng(seed, "stage08:mutations")
    sale_events = {s.invoice_id: s for s in history.sales}
    cash_events = {p.payment_id: p for p in history.cash_events}
    invoices = {i.invoice_id: i for i in clean.invoices}
    payments = {p.payment_id: p for p in clean.payments}
    reserved_invoices = set(duplicate_ids) | {payments[p].invoice_refs[0].invoice_id for p in boundary_ids}
    refunded = {p.original_payment_id for p in clean.payments if p.transaction_kind == "refund"}

    def rows(journal_id):
        return [r for r in ledger if r.journal_id == journal_id]

    def recognition(invoice_id):
        return min((r for r in ledger if r.invoice_id == invoice_id and r.entry_kind == "recognition"
                    and r.account == "revenue"), key=lambda r: r.posting_sequence)

    def application(payment_id):
        return next(r for r in ledger if r.payment_id == payment_id and r.account == "receivables"
                    and r.entry_kind == "allocation")

    def replace(journal_id, event_id, transform):
        for row in rows(journal_id):
            updated = transform(row)
            index = ledger.index(row)
            if updated is None:
                ledger.pop(index)
            else:
                ledger[index] = updated
            mutations.append(Mutation(event_id=event_id, object_ids=[row.row_id], operation="replace" if updated else "remove",
                                      field="ledger_row", clean_value=row.model_dump_json(),
                                      observed_value=updated.model_dump_json() if updated else None))

    def change_amount(journal_id, event_id, amount):
        replace(journal_id, event_id, lambda r: r.model_copy(update={"debit_minor": amount if r.debit_minor else 0,
                                                                  "credit_minor": amount if r.credit_minor else 0}) if amount else None)

    def partial(payment, missing=False):
        expected = base_amount(clean, payment.invoice_refs[0].amount_minor, payment.currency, payment.timestamp)
        actual = 0 if missing else expected - config.partial_shortfall_minor
        if actual <= 0 and not missing:
            raise ValueError("partial shortfall must leave a positive application")
        change_amount(application(payment.payment_id).journal_id, cash_events[payment.payment_id].event_id, actual)
        targets.append(("payment_allocation", payment.payment_id))

    def cutoff(row, document, event_id):
        timestamp = document.service_at if hasattr(document, "service_at") else document.timestamp
        when = clean.manifest.period_end if in_period(timestamp, clean.manifest) else clean.manifest.period_start
        replace(row.journal_id, event_id, lambda r: r.model_copy(update={"timestamp": when}))
        targets.append(("period_cutoff", row.journal_id))

    def duplicate(invoice):
        original = recognition(invoice.invoice_id)
        journal_id = ids.new("journal")
        sequence = max(r.posting_sequence for r in ledger if r.invoice_id == invoice.invoice_id) + 1
        for row in rows(original.journal_id):
            extra = row.model_copy(update={"row_id": ids.new("row"), "journal_id": journal_id, "posting_sequence": sequence})
            ledger.append(extra)
            mutations.append(Mutation(event_id=sale_events[invoice.invoice_id].event_id, object_ids=[extra.row_id],
                                      operation="insert", field="ledger_row", clean_value=None, observed_value=extra.model_dump_json()))
        targets.append(("duplicate_invoice", invoice.invoice_id))
        return journal_id

    def fx_candidate(invoice, variant):
        required = applicable_fx(clean, invoice.currency, invoice.service_at)
        rate = required.rate * Decimal("0.98") if variant == "rate" else next(
            r.rate for r in clean.fx if r.source_currency == invoice.currency and r.date == required.date - timedelta(days=1))
        amount = convert_minor(invoice.total_minor, invoice.currency, "KZT", rate)
        if not amount or amount == base_amount(clean, invoice.total_minor, invoice.currency, invoice.service_at):
            return None
        return required, rate, amount

    def wrong_fx(invoice, journal_id, variant, candidate):
        required, rate, amount = candidate
        event_id = sale_events[invoice.invoice_id].event_id
        change_amount(journal_id, event_id, amount)
        fx_decisions.append(FXDecision(event_id=event_id, journal_id=journal_id, variant=variant,
                                       required_date=required.date, used_date=required.date if variant == "rate" else required.date - timedelta(days=1),
                                       required_rate=required.rate, used_rate=rate))
        targets.append(("fx_conversion", journal_id))

    for payment_id in boundary_ids:
        payment = payments[payment_id]
        if config.boundary_scenario.consumes("a"):
            partial(payment)
        if config.boundary_scenario.consumes("b"):
            cutoff(application(payment_id), payment, cash_events[payment_id].event_id)
    for invoice_id in duplicate_ids:
        invoice = invoices[invoice_id]
        journal_id = duplicate(invoice) if config.duplicate_fx_scenario.consumes("a") else recognition(invoice_id).journal_id
        if config.duplicate_fx_scenario.consumes("b"):
            candidate = fx_candidate(invoice, "rate")
            if candidate is None:
                raise ValueError("scenario FX mutation leaves the rounded amount unchanged")
            wrong_fx(invoice, journal_id, "rate", candidate)

    def remaining(field, scenario=None, side="a"):
        return getattr(config, field) - (scenario.consumes(side) if scenario else 0)

    def choose(candidates, count, error):
        candidates = list(candidates)
        rng.shuffle(candidates)
        if len(candidates) < count:
            raise ValueError(error)
        return candidates[:count]

    ordinary_payments = [p for p in clean.payments if p.transaction_kind == "receipt" and p.payment_id not in refunded
                         and p.invoice_refs[0].invoice_id not in reserved_invoices]
    partial_count = remaining("partial_allocations", config.boundary_scenario)
    partial_targets = choose((p for p in ordinary_payments if base_amount(clean, p.amount_minor, p.currency, p.timestamp) > config.partial_shortfall_minor),
                             partial_count, "too few eligible partial allocation targets")
    for payment in partial_targets:
        partial(payment)
    missing_targets = choose((p for p in ordinary_payments if p not in partial_targets), config.missing_allocations,
                             "too few distinct missing allocation targets")
    for payment in missing_targets:
        partial(payment, missing=True)
    late_targets = choose((p for p in ordinary_payments if p not in missing_targets),
                          remaining("misplaced_applications", config.boundary_scenario, "b"), "too few application cutoff targets")
    for payment in late_targets:
        cutoff(application(payment.payment_id), payment, cash_events[payment.payment_id].event_id)
    ordinary_invoices = [i for i in clean.invoices if i.invoice_id not in reserved_invoices]
    for invoice in choose(ordinary_invoices, remaining("duplicate_invoices", config.duplicate_fx_scenario), "too few duplicate targets"):
        duplicate(invoice)
    used_fx = set()
    for variant, count in (("date", config.wrong_fx_dates), ("rate", remaining("wrong_fx_rates", config.duplicate_fx_scenario, "b"))):
        if not count:
            continue
        candidates = [(i, fx_candidate(i, variant)) for i in ordinary_invoices if i.currency != "KZT" and i.invoice_id not in used_fx]
        for invoice, candidate in choose((c for c in candidates if c[1] is not None), count, "too few effective rounded FX targets"):
            wrong_fx(invoice, recognition(invoice.invoice_id).journal_id, variant, candidate)
            used_fx.add(invoice.invoice_id)
    for invoice in choose(ordinary_invoices, config.misplaced_recognitions, "too few recognition cutoff targets"):
        cutoff(recognition(invoice.invoice_id), invoice, sale_events[invoice.invoice_id].event_id)

    # Compute every declared amount/proof only after the last mutation. The
    # separate audit below reconstructs all defects without this target plan.
    issues = []
    journals = defaultdict(list)
    for row in ledger:
        journals[row.journal_id].append(row)
    for kind, target in targets:
        if kind == "payment_allocation":
            payment = payments[target]
            ref = payment.invoice_refs[0]
            observed = settlement_view(payment, ledger).allocations[0].applied_minor
            amount = abs(base_amount(clean, ref.amount_minor, payment.currency, payment.timestamp) - observed)
            affected = [payment.payment_id, ref.invoice_id]
            rate = applicable_fx(clean, payment.currency, payment.timestamp)
            proof = [payment.doc_id, f"settlement:{payment.payment_id}", *([rate.evidence_id] if rate else [])]
        elif kind == "duplicate_invoice":
            invoice = invoices[target]
            revenue = sorted((r for r in ledger if r.invoice_id == target and r.entry_kind == "recognition"
                              and r.account == "revenue"), key=lambda r: r.posting_sequence)
            amount, affected = sum(r.credit_minor for r in revenue[1:]), [target]
            proof = [invoice.doc_id, *[r.row_id for r in revenue]]
        else:
            row = next(r for r in journals[target] if r.account in ("revenue", "receivables") and r.credit_minor)
            document = payments[row.payment_id] if row.payment_id else invoices[row.invoice_id]
            affected, amount, proof = [target], row.credit_minor, [document.doc_id, row.row_id]
            if kind == "fx_conversion":
                rate = applicable_fx(clean, document.currency, document.service_at)
                amount = abs(base_amount(clean, document.total_minor, document.currency, document.service_at) - row.credit_minor)
                proof.append(rate.evidence_id)
        issues.append(TruthIssue(issue_id=ids.new("issue"), type=kind, affected_ids=affected,
                                 expected_amount_minor=amount, currency="KZT", evidence_sets=[proof]))
    ordering = _rng(seed, "stage08:ordering")
    invoice_list, payment_list, fx_list = list(clean.invoices), list(clean.payments), list(clean.fx)
    for table in (ledger, invoice_list, payment_list, fx_list):
        ordering.shuffle(table)
    manifest = clean.manifest.model_copy(update={"record_count": len(ledger) + len(invoice_list) + len(payment_list) + len(fx_list)})
    public = PublicEpisode(manifest=manifest, policy=clean.policy, ledger=ledger, invoices=invoice_list, payments=payment_list, fx=fx_list)
    validate_accounting(public)
    if config.size_profile != "tiny" and not (200 <= len(ledger) <= 2000 and 20 <= manifest.document_count <= 200):
        raise ValueError("actual post-mutation size outside 200–2000 ledger rows / 20–200 documents")
    truth = Truth(episode_id=manifest.episode_id, issues=issues)
    validate_final_evidence(public, truth, {
        "duplicate_invoice": config.duplicate_invoices,
        "payment_allocation": config.missing_allocations + config.partial_allocations,
        "fx_conversion": config.wrong_fx_dates + config.wrong_fx_rates,
        "period_cutoff": config.misplaced_recognitions + config.misplaced_applications,
    })
    return GeneratedEpisode(public=public, clean=clean, truth=truth,
                            history=history.model_copy(update={"fx_decisions": fx_decisions}),
                            provenance=Provenance(episode_id=manifest.episode_id,
                                event_ids=[s.event_id for s in history.sales] + [p.event_id for p in history.cash_events], mutations=mutations))


def scenario_variants(seed, config, scenario):
    """Controlled four-way ablation of one scenario, with identical clean books."""
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if scenario not in ("boundary", "duplicate_fx"):
        raise ValueError("unknown interaction scenario")
    config = config if isinstance(config, GeneratorConfig) else GeneratorConfig.model_validate(config)
    source = config.boundary_scenario if scenario == "boundary" else config.duplicate_fx_scenario
    count = source.count if source else 1
    result = {}
    for variant in ("clean", "a_only", "b_only", "both"):
        values = config.model_dump(mode="json")
        values.update({name: 0 for name in COUNTS})
        values.update(version="stage08-v1", boundary_scenario=None, duplicate_fx_scenario=None)
        values[scenario + "_scenario"] = {"count": count, "variant": variant}
        a, b = ("partial_allocations", "misplaced_applications") if scenario == "boundary" else ("duplicate_invoices", "wrong_fx_rates")
        values[a] = count if variant in ("a_only", "both") else 0
        values[b] = count if variant in ("b_only", "both") else 0
        result[variant] = generate_composed(seed, GeneratorConfig.model_validate(values))
    return result
