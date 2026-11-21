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
separation is enforced by the process/permission boundary in the Stage 05 runner.

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

These are contract examples. Stage 04 implements tools, cursor handling,
arithmetic parsing, episode transitions and transport rewards. The example cursor
`ledger:1` illustrates a continuation token; clients must treat cursors as opaque.
Limits are 50 rows per page, 30 findings, 10 evidence IDs and 1,000 explanation
characters. Unknown IDs/currencies in structurally valid findings are left for
stage 03 matching, rather than rejected as a malformed envelope.

## Generated KZT records (Stage 06)

The public schema remains v1.0. `GeneratorConfig` is separately versioned as
`stage06-v1` in `audit_env/generation.py`; its count fields are strict integers.
The seed and full configuration belong to the evaluator. Episode IDs are opaque
and depend on seed/config; business IDs stay stable between clean and mutated
variants of the same underlying history. Public tables use seeded permutations.

A generated export adds private `history.json` (version, seed, config, sales and
cash events) and `clean.json` (the pre-mutation PublicEpisode) beside truth and
provenance. Every provenance `event_id` resolves to a history event. For
`field="ledger_row"`, `clean_value` and `observed_value` are JSON strings encoding
complete LedgerRows. Insert has a null clean value; remove has a null observed
value; replace has both. `object_ids` identifies the row. This uses the existing
private mutation schema and permits exact reconstruction in both directions.

Receipts direct 70% of the invoice amount, rounded down to a minor unit, and clean
books apply that full directed amount. The first latent sale has two separately
documented receipts whose amounts sum to that 70%; another has a documented
quarter-receipt refund. The original receipt's settlement remains positive. The
refund has its own negative cash and application settlement, and invoice
receivables reopen by that amount. Repeated invoice amounts are clean controls.
Refunded receipt pairs are excluded from allocation mutations at this stage.

A missing allocation removes both journal legs; a partial allocation reduces
both legs by `partial_shortfall_minor`. A duplicate inserts the full balanced
recognition journal with new opaque IDs and a later business posting sequence.
Truth cites the final public payment directive and settlement for allocations,
or the invoice and two revenue rows from distinct journals for duplicates.

## Generated FX and reporting periods (Stage 07)

`stage07-v1` extends the generator configuration without changing the public
v1.0 wire schema. `currencies` cycles through a distinct nonempty selection of
KZT/USD/EUR/JPY; amounts in the generator range are document-currency minor
units. `timezone` is an IANA name, default Asia/Almaty. `boundary_cases=true`
places four clean services just inside the start, just before the end, exactly
at the exclusive end, and just before the start of November 2026. Issuance can
precede the service date; service_at governs recognition and invoice FX.

The ledger and settlement view remain KZT minor units. Payment directives are
in payment-currency minor units and must be converted with their local payment
date before comparison with settlement. The configurable partial shortfall is
always KZT minor units. Foreign allocation proofs add the applicable FX key.
Split receipts and refunds are each converted and rounded separately.

`audit_env/accounting.py` publishes the directional conversion and period rules.
FX rows express target major units per source major unit. Source exponent,
rate and target exponent are applied before one ROUND_HALF_UP rounding. Missing
applicable rates invalidate the company, including when adjacent-period evidence
needs them. No UTC-first date selection or inverse-rate substitution is allowed.

`wrong_fx_dates` uses the preceding published local-date rate;
`wrong_fx_rates` uses 98% of the applicable rate. They select distinct original
recognition journals and modify both legs, preserving balance. Candidates must
produce a positive, different rounded posting; ineffective candidates are skipped
and an unfulfillable count fails before export. `misplaced_recognitions` moves
an original journal across the selected period boundary. In-period services
move to the exclusive end; adjacent services move to the inclusive start.
Counts are strict nonnegative integers, independently disabled at zero, with
at most 12 total issues across all families.

FX and cutoff targets are journal_id. An FX proof includes source doc_id, one
revenue row_id and the required FX key; the amount is the absolute required-minus-
observed difference. A cutoff proof includes source doc_id and revenue row_id;
the amount is that final observed posting. Manifest and policy are common public
context. New-family truth is computed after all row changes. No adjacent rows
or documents are filtered out of list/get tools.

Private history adds event currencies and `fx_decisions` with event/journal,
variant, required/used local dates and decimal rates. Provenance retains sequential
before/after ledger-row JSON, including both legs of FX and timestamp changes.
This supports exact forward replay and reversal even for a row edited twice.
Existing Stage 06 configs retain their public identity and KZT behavior.

## Composition and size configuration (Stage 08)

Public records and tools retain schema v1.0. Generator version `stage08-v1`
introduces `boundary_scenario` and `duplicate_fx_scenario`. Each is null or
`{count: 1..6, variant: clean|a_only|b_only|both}`. `boundary_scenario` reserves
distinct foreign, non-refunded partial receipts near the exclusive period end.
Its A side consumes `partial_allocations`; its B side consumes the new integer
`misplaced_applications`. The A side reduces both application legs by the base-
currency `partial_shortfall_minor`; B moves those actual legs to period_end.

`duplicate_fx_scenario` reserves other foreign invoices. A consumes
`duplicate_invoices`, B consumes `wrong_fx_rates`. A-only copies a correct
recognition journal; B-only misconverts the original; A+B copies the correct
journal and misconverts only the extra. Required FX always follows service_at.
The extra is identified by posting_sequence, independent of row IDs/order.
Scenario amounts and proofs are built from final rows after every edit.

Counts must cover the requested scenario sides. Remaining counts select ordinary
targets outside reserved scenario invoices. There is at most one issue of a
family per canonical target, and at most 12 issues total. Clean and disabled
sides still reserve the same business controls, so a boundary timestamp or a
foreign invoice alone cannot reveal issue status. The trusted helper
`scenario_variants(seed, config, scenario)` sets unrelated counts to zero and
returns clean/A-only/B-only/A+B companies with identical clean source tables.
Its names/configs stay with the evaluator, outside agent messages.

Late application evidence is payment doc_id plus the actual receivables row_id.
Its canonical affected ID is journal_id and amount is the observed base posting.
The allocation finding instead targets payment_id + invoice_id and compares the
payment-date converted directive with actual application, using a settlement
completeness view and applicable FX key. Timestamp changes do not change the
required monetary conversion date.

`size_profile` is tiny (unit/demo cases), small or large. Non-tiny profiles must
actually contain 200–2,000 ledger rows and 20–200 invoice/payment documents after
mutation. At most 99 invoices are supported in this version: one extra split
receipt and one refund produce 2*N+2 documents. The shipped small/large profiles
use 36/96 invoices respectively. Their mixed variants have 12 issues, including
both scenarios and standalone controls. A too-small final ledger is rejected
even if its clean ledger met the minimum. All four table lengths contribute to
manifest record_count, including adjacent-period FX rows.

Stage 08 varies synthetic business names in descriptions, dates, receipt
fractions, split proportions/positions, refund positions, amounts, currencies,
timezones and record ordering using local seeded streams. The first two latent
sales have the same amount, currency and entity with distinct invoice IDs as
valid recurring controls. `fx_profile` is daily by default; flat uses constant
directional rates for hand calculations (USD 500, EUR 550, JPY 3.2 to KZT).
Daily changes are smaller than in Stage 07 to keep valid late foreign receipts
below face receivables. Flat wrong-date requests with no effective rounded change
are rejected. Stages 06/07 retain their existing public outputs.

`audit_env/validation.py` reconstructs all four families from final public data,
without production conversion/period/settlement helpers or mutation targets.
`validate_final_evidence` rejects omitted/extra targets, incorrect amounts,
inaccessible/incomplete proofs and unrealized family counts. It also bounds a
public discovery plan: list all four tables at 50/page, open only payments whose
listed allocations disagree with their converted directives, then submit.
The bound uses no truth. Tests execute this plan through the real environment.
Every Stage 08 company passes this independent audit before return/export.

## Baseline delivery captures (Stage 09)

`python -m audit_env.baselines` runs `random`, `reconciliation`,
`mass_accusation` and evaluator-only `oracle` through a common runner. Policy
version is `stage09-v1`; record and tool schemas remain v1.0. The random policy
seed is separate from the trusted company seed. Every ordinary episode uses a
fresh program process; the portable adapter also initializes all policy state
within each invocation. Only the oracle receives truth, in the evaluator.

Each policy output directory contains public `trajectories.jsonl` and separate
`private-result.json`. A header `{metadata: {initial_observation, policy,
policy_version}}` precedes the events. Event fields are `episode_id, step,
action, observation, reward, terminated, truncated, info, delivered`. Actions
and complete wire responses are deep-copied during supervision. `delivered`
becomes true only after the complete JSONL response is written to the channel;
it indicates transport completion, not proof of subsequent policy computation.
Public reward is the actual closed placeholder zero; info is empty.

A timeout between actions is a terminal event with `action=null`, the next log
index, `truncated=true`, `terminated=false`, and the current remaining budget.
It consumes no action. Undelivered response attempts remain explicitly marked
false, including timeout notices that cannot be sent after deadline expiry.
Replay consumers must not treat these events as agent requests or receipts.

Private metrics include precision, recall and F1 inside `score`, plus `return`,
`inspection_steps`, `total_actions`, elapsed seconds, policy version and terminal
reason. A submit counts toward total_actions but not inspection_steps. An
invalid submission still counts as submit; timeout log events do not count as
actions. Matching diagnostics, process identities and submission validation
errors remain in the private result. See `docs/stage-09.md` for worked captures
and measured limitations.

## Replay, transformations and exports (Stage 10)

Public records/tools retain schema v1.0 and generation retains `stage08-v1`.
`stage10-transform-v1` defines a complete bijective ID map and independent
per-table order permutations. All references, including refund links, nested
allocation/proof IDs, latent event references and embedded provenance row JSON,
follow that map. FX evidence date/currency keys are fixed points; settlement
keys derive from remapped payment IDs. Human-readable synthetic descriptions
change consistently. Money, dates, currencies, rates, posting sequence and
accounting policy retain their economic meaning. Materialized settlement views
are recomputed from transformed records.

`stage10-replay-v1` compares initial observations, actions, public responses,
remaining budget, flags, rewards and private results for identical inputs.
Process identities and wall time are excluded. A recorded null-action timeout
is an explicit supervisor event and does not increment the action count.
Cross-pair oracle answers are mapped, and common scores agree at equal actual
inspection cost. Diagnostic matched pairs are compared after sorting by the
remapped issue IDs, following the scorer's existing presentation order.

`stage10-splits-v1` is the strict plan in `configs/stage10-splits.json`: ten train,
ten dev and twenty rehearsal specs, each with a unique seed and normalized
parameter mix. Public exports contain exactly the six record files. The split
manifest records seeds, config indices, paths, actual counts and semantic hashes.
Truth, provenance, history and clean data remain in `evaluator/stage10/` with
restricted Linux access. Ordinary policies receive neither filesystem tree.
`AuditEnvironment.reset_episode` and the exported baseline loader are trusted
host APIs, not additional wire actions or agent-readable path parameters.

All new serialized exports use UTF-8 with LF across Windows/Linux. Export is
idempotent for matching bytes and rejects stale/extra content. The report in
`evaluator/stage10/paired-checks.json` covers twenty disjoint rehearsal pairs,
including five clean and five interacting episodes. Full procedures and measured
limitations are in `docs/stage-10.md`.

## Verification results (Stage 11)

`stage11-v1` adds evaluator-only measurement artifacts, without changing public
records, tools or reward. `results.json` contains eighty distinct
`(episode_id, policy)` rows for the twenty `stage10-splits-v1` rehearsal inputs.
Each row records source seed/config index, public semantic digest, actual record
counts, TP/FP/FN, P/R/F1, return, inspection count, total actions, terminal reason,
end-to-end and policy elapsed seconds, evaluator/policy RSS high-water marks and
their summed upper bound in bytes, plus a relative trajectory path. Ordinary
policies receive none of these evaluator artifacts or configuration files.

`summary` contains per-policy arithmetic means over all twenty episodes, totals
of TP/FP/FN, maximum episode wall time and maximum RSS upper bound. It is not a
pooled or weighted P/R/F1 calculation. Undefined precision/recall equal zero;
both-empty F1 equals one. Measurements include the trusted worker and its single
jailed policy process. The memory sum is a conservative bound, not a claim that
the two process peaks occurred simultaneously. Linux child RSS also includes
pre-exec jail setup. Oracle has no ordinary policy child.

The report records Python/dependency/policy/generator-plan/replay/transformation
versions, source and plan digests, full normalized plan, UTC timestamp, hardware,
CPU/memory cgroup limits and network interfaces. Semantic replay excludes wall
time and process/resource measurements. `paired-checks.json` remains separate
from the eighty rows. A separate timeout trace and incorrect-canary rejection
record supervisor behavior and nonzero CLI failure. The command validates every
retained capture by replay and reconciles counts, score arithmetic, summaries and
exact coverage before writing the passing result artifact last.
