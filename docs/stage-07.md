# Stage 07 — FX conversion and reporting periods

Status: **passed**, verified November 20, 2026. Read the organizer brief, R03–R04,
repository guidance and Stage 06 before implementation. No organizer/local
contract conflict was found. Existing uncommitted Stage 05–06 work was preserved.
The prerequisite Stage 06 suite passed 30 portable tests; the final offline suite
also reran its generated-company integration and the Stage 05 isolation checks.

## Changed files and reading order

1. `configs/stage07-mixed.json` selects six invoices, four currencies, boundary
   controls and six defects across all four families. Each count can be zero.
2. `audit_env/accounting.py` publishes minor-unit conversion, applicable local
   date/rate selection and inclusive-start/exclusive-end membership.
3. `audit_env/generation.py` adds versioned currency/timezone options, foreign
   event derivation, FX rows, clean invariants, two FX variants, cutoff mutation,
   private FX decisions and final-row proof construction. Stage 06 public output
   was compared with its existing export and remains identical.
4. `tests/test_stage07.py` calculates findings from public evidence independently
   of production conversion, membership and settlement helpers, then submits
   them through the real environment and matcher.
5. `policies/generated_demo.py` applies the public rules through existing tools.
   `scripts/build_agent_runtime.py` and `Dockerfile` include read-only public
   IANA timezone data in the restricted Python runtime. The data-free jail and
   evaluator permissions remain covered by the isolation suite.
6. `audit_env/__main__.py` chooses Stage 07 output paths for Stage 07 configs.
   `README.md` and `docs/schemas.md` document commands, options and proof rules.

## Worked input/output and key decisions

USD 100 is 10,000 source minor units. At 500 KZT per USD:

```text
10,000 / 100 × 500 × 100 = 5,000,000 KZT minor = 50,000 KZT
Observed posting:           4,900,000 KZT minor = 49,000 KZT
FX finding:                  100,000 KZT minor =  1,000 KZT
```

Both wrong-date (previous rate 490) and wrong-rate (500 × 0.98) variants exercise
this exact example. The finding targets the recognition journal; its proof has
the source invoice, designated revenue row and required FX row. A KZT invoice
in the same company remains an unaffected control. Both journal legs change,
so balance alone cannot establish correct conversion.

The conversion uses the source exponent, directional rate and target exponent
before rounding once with ROUND_HALF_UP. JPY 100 at 3.2 KZT/JPY gives 32,000 KZT
minor units. USD 123.45 at 150 JPY/USD gives 18,517.5 JPY, rounded to 18,518.
An exact half target minor unit rounds to one, including when source and target
exponents differ. Required missing rates invalidate the company. Mutations that
leave the published rounded amount unchanged are skipped; if the requested
count is impossible, generation raises before export. Tests cover an ineffective
candidate alongside effective ones, and wholly ineffective date/rate candidates.

Invoice FX and recognition use service_at in the manifest timezone; payment FX
uses the payment timestamp in that zone. In the clean USD boundary example,
service is November 1 at 00:30 +05:00, issuance is October 31 at 23:30 +05:00,
and the service instant is October 31 at 19:30 UTC. The November service date
selects rate 500 and November recognition. Selecting the issuance or UTC date
would incorrectly select October 31 and rate 490.

Membership is `[period_start, period_end)`. Services just before the start and
exactly at the end are clean adjacent-period controls. Their documents, rows and
rates remain available through list/get/document tools. A cutoff mutation moves
an original recognition journal across the chosen period boundary in either
direction. Its amount is the final observed revenue leg and its canonical target
is journal_id. The public source document and dated row prove the error against
the common manifest/policy context.

Foreign payment directives are converted before comparison with base-currency
settlement. Missing/partial allocation proofs include the required payment-date
FX key. Split receipts and refunds are converted separately. Private history
records every FX choice's event/journal, variant, required/used dates and rates;
provenance records sequential before/after rows. Tests replay and reverse all
edits, including a journal with both amount and timestamp changes.

## Commands and observed results

Executed from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage06.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage07.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
git diff --check
.\.venv\Scripts\python.exe -m audit_env --generate runs/stage-07/company --seed 7 --generator-config configs/stage07-mixed.json
.\.venv\Scripts\python.exe -m audit_env --fixture runs/stage-07/company/public
docker build -t audit-rl-env:stage07 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage07 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g --mount "type=bind,source=$($PWD.Path)\runs\stage-07\isolated,target=/results" audit-rl-env:stage07 python -m audit_env --isolated-generated --seed 7 --generator-config configs/stage07-mixed.json --trace /results/trajectories.jsonl --private-result /results/private-result.json
```

Stage 07 portable checks: **52 passed, 1 Linux-only test skipped**. Final full
portable suite: **155 passed, 9 Linux-only tests skipped**. Final prepared Linux
image: **163 passed, 1 unsupported-platform guard skipped**, with isolation
required. All supported integration checks ran. `pip check` found no broken
requirements; `git diff --check` passed. An initial sandbox Docker permission
error was resolved through approved engine access; no check remains blocked.

The normal isolated CLI completed with **TP=6, FP=0, FN=0, F1=1, return=0.978**.
Eleven inspections plus submit used 12 actions. All delivered closed rewards
were zero, and the policy was reaped. This run measured evaluator PID 1/UID 0
and policy PID 7/UID/GID 65534; PIDs are specific to that run. The public trace
and private result are retained under ignored `runs/stage-07/isolated/`.

The final mixed manifest has **76 records, 14 documents**: 44 ledger rows,
6 invoices, 8 payments and 18 FX rows. The Linux test also runs a clean company,
every individual mutation switch, a USD-only boundary control, a New York
timezone control and a JPY-only Tokyo control. Each completes with zero FP/FN.
Portable checks cover four timezones, both cutoff directions, both sides of the
exclusive end, missing/directional rates, final public proofs and byte-identical
ten-file exports. A separate generation sweep successfully constructed 240 clean
profiles across 20 seeds, four currencies and three timezones.

## Limits and study checkpoint

This stage retains a small November 2026 development profile. Wrong-date uses
the preceding published date and wrong-rate uses 98% of the applicable rate;
cutoff mutations currently target original recognition journals. Explicit paired
interaction scenarios, payment-application cutoff mutations, large profiles and
the final discovery budget guarantee remain Stage 08. The public-tool policy is
a demo; four complete baseline adapters remain Stage 09. No model training or
release/dataset claims are made. Image preparation used network access; all
reported container acceptance runs disabled networking. Required source/config/
tests/docs are outside ignored run output.

Study checkpoint: **Calculate an FX posting on paper and identify which timestamp
policy chooses. Why would converting to UTC first change the month in this
example?** The policy selects local service_at for invoices and local payment
time for payments. Subtracting five hours moves November 1 00:30 +05:00 to
October 31 19:30 UTC; using that UTC month would violate the local-period rule.

Next stage: **08 — Compose interacting errors and scale generation**.
