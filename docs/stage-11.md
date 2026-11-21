# Stage 11 — Offline evaluation and measured failures

Status: **passed**. The single offline entry point completed all eighty policy
runs and twenty separate pairs. Existing Stage 05–10 work was preserved; no
organizer-contract conflict was found. No commit, push or submission was made.

## Changed files and reading order

1. `configs/stage11-expected.json`: independent Stage 02 canary expectation.
2. `audit_env/verify.py`: offline preflight, isolation-required test suite,
   exported-data checks, twenty pairs, actual timeout and negative controls,
   eighty fresh-worker runs, capture replay, arithmetic reconciliation and reports.
3. `tests/test_stage11.py`: deliberate bad expected input through the actual CLI,
   hand-calculated means, corrupted artifacts, missing/duplicate rows, stale
   output protection, failed-suite behavior and Linux worker/timeout checks.
4. `evaluator/stage11/`: retained report, machine-readable results, all eighty
   delivery captures, private results, separate pairs and probe evidence.
5. `README.md` and `docs/schemas.md`: execution and result semantics.

No public contract, generator, matcher, reward or baseline strategy changes are
needed. The fixed inputs are the twenty Stage 10 rehearsal specs: five clean,
ten single-issue and five interacting cases. Seeds and full parameter mixes are
disjoint from public train/dev. These are local inputs, not hidden jury cases.

## Independent input/output expectation

The hand-authored allocation fixture directs 7,000,000 KZT minor units to an
invoice but applies 5,000,000. Reconciliation must claim 2,000,000, with TP=1,
FP=FN=0. Four inspections plus submit give `2*1 - 1 - .002*4 = .992`.
`--expectations` permits a throwaway copy with a deliberately wrong answer.
Both pytest and the normal verifier execute the actual CLI with that copy and
require exit 1. The original fixture remains unchanged and is checked again.

## Measurement and checks

Each ordinary policy runs through the existing Linux jail. Oracle alone stays
trusted-side. A fresh worker for every policy/episode makes Linux RSS high-water
marks specific to that run. Sum of worker and child maxima is a conservative
memory bound, since those peaks need not coincide; child usage includes jail
setup before exec. Elapsed wall time includes worker startup, generation,
validation, jail preparation, policy execution and trace writes. Policy runner
elapsed time is retained separately. Every row must finish within 60 seconds,
100 actions and a 4 GiB RSS upper bound. Docker constrains the entire execution
to two CPUs and 4 GiB; hardware/cgroup metadata records the actual context.

Every saved delivery capture is replayed against its generated episode. The
verifier checks zero closed rewards, terminal flags, inspection/action counts,
private scores, independent reward arithmetic, supported isolation and reaping,
common public input digest, eighty unique combinations and arithmetic summary
means. P/R means include zero precision and recall for empty clean answers.
Paired checks are separate from the benchmark. A sleeping jailed policy proves
timeout, reaping and the null-action event without consuming an action.

Network preflight requires loopback only. The full test suite requires the Linux
isolation runtime and permits only the Windows-specific platform guard to skip.
No external service, credentials, GPU or model download participates in runtime
verification. Image preparation can use networking.

An initial regression test exposed tuple-versus-JSON-array equality in replay
matching diagnostics. The verifier now compares normalized JSON values; the
underlying matcher and retained corrupted-case tests are unchanged.
Review of the first benchmark also exposed a report wording error: an empty
random-policy answer was described as accusations. The narrative now branches
on the actual submission, with tests for both silence and unsupported claims.
The first run is preserved under ignored `runs/stage11-first-run/`; the retained
final evidence was regenerated from the corrected source.

## Commands

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
docker build -t audit-rl-env:stage11 .
New-Item -ItemType Directory -Path evaluator/stage11
docker run --rm --network none --cpus 2 --memory 4g --mount "type=bind,source=$($PWD.Path)\evaluator\stage11,target=/results" audit-rl-env:stage11 python -m audit_env.verify --output /results
```

Use an empty/new output directory on reruns. The unmounted single verification
command in the README uses a fresh timestamped output directory inside the image.
Retained evidence belongs outside ignored `runs/`. Stage 12 will rehearse a fresh
checkout and freeze release packaging/image identity; this stage does not claim
that release rehearsal is complete.

## Measured results and limitations

The machine-readable and short human reports are written by the completed
verifier to `evaluator/stage11/results.json` and `evaluator/stage11/report.md`.
They include each individual episode, policy means, maximum measured time/RSS
bound, normalized inputs, versions and trace-supported failures.

Commands above succeeded. The full portable suite initially passed **264 tests**
with **19 Linux-only skips**; after adding the failure-narrative regression,
the targeted portable Stage 11 suite passed **13 tests**, with **2 Linux-only
skips**. The final full offline Linux command passed **284 tests**, with only
**1 Windows-specific platform guard skipped**. All supported isolation checks
ran. Exported train/dev byte checks, twenty pairs, real timeout/reaping and the
wrong-expectation CLI exit **1** all passed. The original canary was unchanged.
`pip check` and `git diff --check` passed.

All **80** distinct policy/episode rows and **80** closed delivery captures were
retained, alongside evaluator-only results. An independent post-run script
recomputed summary means and totals, verified every capture's action count and
zero rewards, checked exact coverage and compared the report's source digest
against the current checkout. These artifacts occupy **9,700,320 bytes**.

Per-policy means over twenty episodes:

- Reconciliation: P/R **.75/.75**, F1 **1**, return **.9689**,
  **15.55 inspections / 16.55 actions**, **1.0552 seconds**;
  total TP/FP/FN **30/0/0**.
- Oracle: P/R **.75/.75**, F1 **1**, return **1**,
  **0 inspections / 1 action**, **.6255 seconds**; total TP/FP/FN **30/0/0**.
- Random: P/R/F1 **0**, return **−1**, **20 inspections / 21 actions**,
  **1.0662 seconds**; total TP/FP/FN **0/66/30**.
- Mass accusation: P/R/F1 **0**, return **−1**, **2 inspections / 3 actions**,
  **1.0456 seconds**; total TP/FP/FN **0/600/30**.

P/R are .75 for perfect reconciliation/oracle because five clean episodes have
undefined P/R recorded as zero. Their clean F1 is one. Maximum episode wall time
was **1.1878 seconds**, and maximum summed RSS upper bound was **82 MiB**.
The CPU was AMD Ryzen 5 5500U under WSL2 Linux, with Docker CPU quota
`200000 100000` (two CPUs), memory limit **4,294,967,296 bytes** and loopback only.
The upper case actually contained **604 ledger rows / 200 documents**.

The generator reaches 200 documents, with roughly 600 ledger rows rather than
the suggested 2,000-row upper envelope. Reconciliation follows known accounting
roles and fixed KZT base-currency conventions. Passing these local cases does
not establish general accounting ability. The policies are fixed scripts;
there is no model weight training or measured training improvement.

## Study checkpoint

Pick the low-return random-policy episode in `report.md` and open its linked
trace. Its empty submission misses an allocation issue; it finishes before the
action limit. Compare this with mass accusation on the same episode: its
document-only claims add false positives and fail complete proof requirements.
Neither failure comes from exhausted steps. The report records actual TP/FP/FN,
submission size, terminal step and evidence completeness.

Specifically, episode `ep-018ca7949630bc2cd9369c11` (rehearsal seed **30007**)
contains one allocation issue. Random submits zero findings at step **21**:
TP=FP=0, FN=1, return **−1**. It missed the issue after using only 21 of the
100 allowed actions. Mass accusation submits **30** unsupported claims
at step **3**, with TP=0, FP=30, FN=1 and no complete truth proof. Its return is
also **−1**. The linked traces in `report.md` support both explanations.

Next stage: **12 — Package, demonstrate and rehearse handoff**.
