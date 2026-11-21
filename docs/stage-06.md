# Stage 06 — Clean companies, duplicates and allocations

Status: **passed**, verified on November 20, 2026, including the final offline
Linux image and normal generated-episode CLI. Prerequisites 02–05 passed 73 portable
tests; their seven Linux integration cases were also rerun successfully in the
first Stage 06 offline image. The organizer brief and R02–R04 govern this work;
no organizer clarification or contract conflict was found in the checkout.
Existing uncommitted Stage 05 files were preserved and extended where needed.

## Outcome and reading order

1. `configs/stage06-mixed.json` is a small worked configuration, with six
   invoices of 100,000 KZT, one duplicate, one missing application and one partial
   application. Omitting the config creates a clean company with varied amounts.
2. `audit_env/generation.py` contains the separate `stage06-v1` generator config,
   private sale/cash event models, document/journal derivation, clean accounting
   gate, mutations and public/private export.
3. `tests/test_stage06.py` independently checks the public amounts, balance,
   distractors, provenance reconstruction, reference integrity, replay and runner.
4. `audit_env/environment.py` adds trusted `reset(seed, {generator: config})`.
   `audit_env/isolation.py` adds `run_isolated_generated` using the existing jail,
   message allowlists and deadline. Generated records stay in evaluator memory.
5. `policies/generated_demo.py` exercises the first two issue families through
   public tools. `audit_env/__main__.py` exposes export and isolated execution.
   `docs/schemas.md` and `README.md` document storage and the supported commands.

## Generation and accounting

Independent local RNG streams control business amounts/descriptions, opaque IDs,
mutation selection and table order. They never touch Python's global RNG. The
episode ID also incorporates the complete versioned config, so variants cannot
silently share one episode ID. Business object IDs remain stable across the
clean/faulty variants when the business configuration stays the same.

The generator first records all sales, partial receipts, invoice directives and
refunds as latent events. It then derives invoice/payment documents and two-leg
KZT journals. Recognition debits receivables and credits revenue. A receipt
debits cash and credits unapplied receipts, then an allocation debits unapplied
receipts and credits receivables. A refund reverses the allocation, then the cash
receipt, and references its original payment in the public document.

Before mutation, validation checks schema counts and links, one positive side
per posting, equal debit/credit totals and coherent metadata per journal, invoice
line totals, one recognition per invoice, nonnegative receivables, complete
directed applications, cash totals and refund chronology/limits. No truth input
is needed for this clean gate.

Each clean company has a legitimate 70% receipt pattern. One invoice has two
split receipts; two invoices have the same amount and entity with different
documents/dates; another receipt has a quarter-amount refund. Clean controls
remain in faulty companies. The current allocation mutations protect the
refunded receipt pair and choose distinct ordinary payments for missing versus
partial applications. Duplicate and allocation counts are independently
configurable; duplicate and allocation findings may concern the same invoice.
The required FX/period interacting scenarios are Stage 08 work.

Missing application removes both allocation legs. Partial application reduces
both by the configured shortfall. A duplicate adds the full recognition journal
with new IDs and a later posting sequence/timestamp. All three preserve balance.
Duplicate amounts count only extra revenue, never both balancing legs. Proofs
use the final payment directive plus settlement, or the invoice plus original
and extra revenue rows. Each proof has two or three IDs.

Exports contain the six standard public files and four private JSON files:
truth, provenance, latent history and clean books. History records seed/config;
they never enter the policy channel. Provenance stores complete before/after
row JSON in the existing string fields and links to the causing history event.
The tests reconstruct every final row and then undo all changes exactly.
Linux exports use private directory 0700, private files 0600 and public files
0444. Windows export modes do not establish a Linux-style isolation boundary;
ordinary policies run only through the restricted Linux runner.

## Worked input/output

An independent fixed-amount check uses seed 0, amount_min_minor and
amount_max_minor both 10,000,000, and partial_allocations=1. The generated
invoice is 100,000 KZT; its payment directs 70,000. Only 50,000 is applied.
The missing allocation is 20,000 KZT = **2,000,000 minor units**. Receivables
are 50,000: 30,000 legitimately unpaid plus the 20,000 application defect.
This test asserts the fixed numbers directly against public rows.

The checked-in mixed config with seed 6 selects two halves of a split receipt.
Each directs 35,000 KZT. One applies nothing, giving **3,500,000 minor units**
missing. The other applies 15,000, giving **2,000,000 minor units** underapplied.
The duplicated invoice is 100,000 KZT, giving **10,000,000 minor units** extra
recognition. A different invoice with the same amount is not a duplicate.

For that mixed config the final public manifest reports 44 ledger rows,
6 invoices and 8 payments: **58 records, 14 documents**. Adding the duplicate's
two rows and removing the wholly missing allocation's two rows cancel in the
record count. The partial application changes amounts only.

The restricted demo lists invoices, payments and ledger, then retrieves seven
receipt documents. It independently derives three findings from public facts,
with no expected-answer file, generator package, history or truth in its jail.
Ten inspections and one submission give TP=3, FP=0, FN=0, F1=1 and true score
**1 − 0.002 × 10 = 0.98**. Closed trace rewards remain **0**. The clean run
submits zero findings and earns the same score at the same inspection count.

## Commands and checks

Commands executed from the repository root (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage02.py tests/test_stage03.py tests/test_stage04.py tests/test_stage05.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage06.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m audit_env --generate runs/stage-06/company --seed 6 --generator-config configs/stage06-mixed.json
.\.venv\Scripts\python.exe -m audit_env --fixture runs/stage-06/company/public
docker build -t audit-rl-env:stage06 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage06 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage06 python -m audit_env --isolated-generated --seed 6 --generator-config configs/stage06-mixed.json
```

Portable suite: **103 passed, 8 skipped**. Stage 06 alone: **30 passed**, one
Linux-only test skipped. The first prepared-image run passed **108 tests**, with
one unsupported-platform guard skipped; it preceded two added regression cases.
The final rebuilt image passed **110 tests**, with only the unsupported-platform
guard skipped. All eight Linux integration cases ran with isolation required.
The normal isolated CLI returned **0.98**, with three TP, no FP/FN and 11 actions.
Its public trace has ten inspections followed by submit; all rewards are zero.
`pip check` reported no broken requirements, and `git diff --check` passed.

An additional CLI run mounted the workspace's `runs/stage-06` at `/results` and
selected `/results/trajectories.jsonl` and `/results/private-result.json` to retain
the artifacts after container removal. The measured evaluator was PID 1, UID 0;
the policy was PID 8, UID/GID 65534, and was reaped. PIDs are run-specific.

Independent tests cover clean/duplicate/missing/partial/mixed profiles, balanced
but defective duplicate recognition, legitimate recurring amounts, split receipts,
signed refunds, the 100,000/70,000/50,000 example, final evidence, row-by-row
provenance, byte-identical ten-file exports, unchanged global RNG, new seed/config
variants, reset and hidden-field safety. Invalid strict types/counts, reversed
amount ranges, too-small profiles, excessive issues and impossible partial
applications fail before export. A targeted test keeps partial-eligible receipts
available when five missing applications are also requested.

The final Linux integration uses both clean and mixed generated inputs with the
same restricted policy. It verifies real identities, cleanup, ten inspections,
zero policy-visible rewards and the private score. Stage 05's sentinel and
sleeping-policy tests continue to protect the shared process boundary.

Two exports of identical version/seed/config are compared byte for byte,
including truth, history, clean books and provenance. Existing export destinations
are rejected; repeat verification uses a fresh directory. Generated local runs
live under ignored `runs/stage-06`; source, config, tests and this evidence record
are the persistent stage deliverables.

## Limits and study checkpoint

Stage 06 generates KZT only, in November 2026 and Asia/Almaty. It accepts 4–100
invoices and at most 12 total issues; the default is a small development company,
not the final delivery size profile. FX/period behavior is Stage 07, full scale
and required interaction scenarios Stage 08, and four baseline adapters plus
systematic trajectories Stage 09. The demo is for these two families; it has
not been validated as a general baseline or for every supported size/budget.

The prepared image runs offline, while image/package preparation may use the
network. Release dependency/image freezing and clean-checkout handoff remain
later stages. No model training, public dataset split, commit or submission is
part of this stage.

Study checkpoint: **Take one invoice through issuance, payment and allocation.
Why can balanced books still contain an error?** Recognition, receipt and
application each balance independently. Repeating a complete recognition journal
or omitting/reducing both allocation legs preserves debit/credit equality, while
the documents prove the recorded recognition/application is wrong.

Next stage: **07 — FX conversion and reporting periods**.
