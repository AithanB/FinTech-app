# Stage 08 — Interacting errors and scale

Status: **passed**, verified November 20, 2026. Organizer brief and R02–R04
reviewed; no contract conflict or organizer clarification was found. Stage 07
prerequisite checks passed 52 portable tests. Existing Stage 05–07 uncommitted
work was preserved; current Stage 06 and 07 public generation was compared with
their existing exports and remains identical.

## Changed files and reading order

1. `configs/stage08-boundary.json` and `stage08-duplicate-fx.json` are the two
   worked scenarios. The other four Stage 08 configs select small/large and
   clean/mixed companies, with zero or twelve issues.
2. `audit_env/generation.py` adds separately versioned Stage 08 config, scenario
   side/count validation, dispatch and flat/daily FX profiles. Legacy IDs and
   semantics remain intact.
3. `audit_env/composition.py` generates varied clean business, reserves scenario
   targets, consumes family counts, records sequential causal row edits and
   derives final amounts/proofs. `scenario_variants` makes controlled four-way
   comparisons on identical clean source books.
4. `audit_env/validation.py` independently reconstructs defects from final public
   facts. It checks truth completeness, targets, amounts, evidence, realized
   family counts and discovery cost, without the mutation plan or production
   conversion/period/settlement helpers. Every Stage 08 return/export passes it.
5. `tests/test_stage08.py` supplies hand calculations, ablations, zero/twelve
   profiles, actual counts, budgeted public discovery, deliberate audit failures,
   replay, provenance reversal and Linux policy runs.
6. `policies/generated_demo.py` adds payment-application cutoff detection and
   selective settlement inspection for larger companies. `audit_env/__main__.py`
   reports trusted validation results and selects Stage 08 output paths.
   `README.md` and `docs/schemas.md` document usage and accounting rules.

## Worked scenarios and why final-row attribution matters

The duplicate example uses seed 8, USD 100 and a required rate of 500 KZT/USD.
The original revenue journal posts 50,000 KZT. The extra journal uses rate 490
and posts 49,000. Final truth is:

- `duplicate_invoice`: **4,900,000 minor units**, affected invoice_id. Proof is
  invoice plus original and extra revenue rows, distinguished by posting_sequence.
- `fx_conversion`: **100,000 minor units**, affected extra journal_id. Proof is
  invoice, extra revenue row and required FX row.

The targets differ, although the findings concern related facts. In A-only,
the duplicate is 50,000 KZT. In B-only, the original is misconverted by 1,000.
In A+B, the duplicate is the extra journal's final observed 49,000, and the FX
difference remains 1,000. The clean variant has empty truth. Both journal legs
are balanced in every variant; counting balancing legs would double the claim.

For the boundary example, seed 8 selects a USD 50 payment directed to its
invoice. The public payment date is November 30, 23:30 +05:00. At 500 KZT/USD,
the intended application is 25,000 KZT. A-only applies 23,000 on time and has
a **200,000-minor-unit allocation discrepancy**. B-only applies all 25,000 at
the exclusive end, December 1 00:00, and has a **2,500,000-minor-unit cutoff**.
The combined variant applies 23,000 late: allocation remains **200,000**, while
cutoff becomes **2,300,000**. The original cash receipt remains 25,000.

Allocation targets payment_id + invoice_id, using the public directive,
settlement and payment-date FX row. Cutoff targets the actual application
journal_id, using payment document and dated receivables row. Its amount comes
from the final underapplied journal, not an earlier full-value snapshot. Moving
the posting does not change which date determines the monetary conversion.

`scenario_variants(8, config, "boundary"|"duplicate_fx")` returns `clean`,
`a_only`, `b_only`, `both`. The clean source ledger, documents and rates are
identical across each four-way set; only episode identity and mutations vary.
All eight variants pass real environment discovery/submission and run through
the restricted Linux policy. Variant names and target plans stay private.

## Scale, variation and independent evidence

At seed 8, small clean/mixed profiles have 224/226 ledger rows and 74 documents.
Large clean/mixed have 584/586 ledger rows and 194 documents. Mixed truth has
two duplicates, three allocation issues, three FX issues and four cutoffs.
The tested 99-invoice variant reaches exactly 200 documents and 604 ledger rows.
Manifest record_count includes all four tables, including FX records. Non-tiny
profiles reject final counts outside 200–2,000 ledger rows and 20–200 documents.
The minimum is checked after mutation: removing an allocation can invalidate
a clean company that had exactly 200 ledger rows.

Business variation includes synthetic names in descriptions, amounts, service
times, legitimate receipt fractions, split proportions and positions, refund
positions, currencies and timezone. Recurring controls share amount, currency
and entity but have distinct invoices. Ordinary row order and opaque IDs carry
no issue markers. Stable independent RNG streams preserve replay and keep the
same controls across ablations. Both scenario sides consume the configured
family counts; they do not add undeclared errors. Reserved targets prevent
standalone mutations from silently changing the intended scenario.

The final audit is separate from mutation arithmetic. It reads actual public
rows, converts with its own Decimal calculation, compares period membership,
reconstructs all four families, and compares the result with the entire truth.
Tests deliberately change amounts, omit an issue, guess targets, remove proof,
misstate family counts, and alter both balanced legs after truth construction;
the independent pass rejects each case. Proofs have two or three accessible IDs,
and provenance replays and reverses every edit exactly, including edited inserts.

The discovery plan lists every table at 50 rows/page, reconciles explicit links,
opens settlement documents only for discrepant payments, then submits. Tests
execute that plan through the real tools and verify every cited proof was
returned. Seed 8 small clean/mixed costs 10/13 actions; large clean/mixed costs
19/22, including submit. Even the 200-document case fits below 30 actions.
This establishes discoverability, rather than an arbitrary policy's success.

## Commands and observed results

Executed from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage07.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage08.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
git diff --check
.\.venv\Scripts\python.exe -m audit_env --generate runs/stage-08/checked-company --seed 8 --generator-config configs/stage08-large-mixed.json
docker build -t audit-rl-env:stage08 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage08 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g --mount "type=bind,source=$($PWD.Path)\runs\stage-08\isolated,target=/results" audit-rl-env:stage08 python -m audit_env --isolated-generated --seed 8 --generator-config configs/stage08-large-mixed.json --trace /results/trajectories.jsonl --private-result /results/private-result.json
```

Stage 08 portable suite: **52 passed, 1 Linux-only test skipped**. Full portable
suite: **207 passed, 10 Linux-only tests skipped**. Prepared Linux suite:
**216 passed, 1 unsupported-platform guard skipped**, with isolation required.
All supported Linux cases ran, including the eight ablation variants and four
size profiles. `pip check` and `git diff --check` passed. No check remains blocked.
An additional sweep validated all four size/cleanliness profiles over 20 seeds
each: **80 companies**, with no generation or independent-audit failure.

The normal large mixed CLI reported **586 rows / 194 documents**, 12 issues and
a **22-action** discovery bound. The isolated CLI independently found TP=12,
FP=0, FN=0, F1=1 and **return=0.958**: 21 inspections plus submit. All delivered
closed rewards were zero; evaluator UID was 0 and policy UID was 65534, and the
policy was reaped. The retained run took about 0.51 seconds; this is an observed
demo duration, not the later systematic benchmark. Artifacts are under ignored
`runs/stage-08/isolated/`; source/config/tests/docs are persistent deliverables.

## Limits and study checkpoint

The shipped large profile approaches the document limit, not 2,000 ledger rows.
This version supports at most 99 invoices and roughly 600 ledger rows in its
current business model; it validates against the suggested range but does not
claim a 2,000-row stress result. Calendar remains November 2026. The independent
audit covers the current public posting roles and mutation families. Benchmark
measurements, complete baseline adapters, dataset splits and paired ID remapping
remain later stages. Image preparation may use network; reported container runs
use `--network none`. There was no commit, publication, training or submission.

Study checkpoint: **How can both issue amounts be correct without their sum
equaling a total financial loss?** They measure distinct contract defects, which
can overlap economically. In the duplicate example, observed revenue is 99,000
against one legitimate 50,000 invoice, so excess recorded revenue is 49,000 KZT.
The duplicate finding measures that extra 49,000 posting; FX separately measures
its 1,000 conversion shortfall. Their 50,000 sum is not the net overstatement.

Next stage: **09 — Four policies and replayable trajectories**.
