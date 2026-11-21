# Stage 09 — Four policies and replayable trajectories

Status: **passed**. Scope ends at four adapters, delivery captures and separate
metrics. Stage 10 owns full replay, ID/order transformations and dataset splits;
Stage 11 owns the 20-episode benchmark and consolidated verification command.
Existing uncommitted work from stages 05–08 was preserved.

## Reading order and implementation

1. `policies/baselines.py`: the three ordinary adapters and public-only
   `run_policy(name, initial, act, seed=0)` interface. Every invocation creates
   fresh local tables, findings and RNG state. `act(action)` returns the public
   observation result; terminal replies raise `EpisodeEnded`. Reconciliation
   retains the arithmetic already verified by the Stage 08 demo.
2. `policies/oracle.py`: evaluator-only adapter using the same initial/act
   interface plus trusted truth. It submits one complete accepted evidence set
   for each issue through the real environment and common scorer.
3. `audit_env/baselines.py`: common `run_baseline` runner, policy bundling,
   metrics, file export and `python -m audit_env.baselines` entry point. Ordinary
   runs use the existing Linux jail. Only ordinary source and the independent
   explorer seed are copied into its program; no company seed, configuration,
   truth, provenance, oracle code or answer file is supplied.
4. `audit_env/isolation.py`: accepts a trusted program bundle, snapshots action
   and full wire response at dispatch/delivery, retains empty `info`, and labels
   step exhaustion separately from successful submission. Existing time and
   privilege boundaries stay authoritative.
5. `tests/test_stage09.py`, the retained captures in
   `episodes/examples/stage09/`, and the README usage section.

The fixed-seed random adapter performs 20 exploratory calls, choosing public
tables, pages, records and documents, then submits up to five unverified
accusations drawn from observed objects. Its local RNG never touches global
random state. This intentionally weak baseline is reproducible for a fixed
policy seed and identical tool responses.

Mass accusation enumerates invoice duplicate/FX/cutoff allegations followed by
payment-allocation allegations until it reaches the 30-finding cap or runs out
of objects. It uses observed IDs and schema-valid fields without establishing
the full proof. It is distinct from the separate 31-finding malformed test.

Reconciliation joins explicit invoice/payment references to posting roles,
distinguishes journals from debit/credit legs, computes directional FX with
Decimal and local dates, compares local reporting periods, and requests public
settlements for discrepancies. Tiny tutorials retain the settlement inspection
sequence; larger companies open only discrepant payment settlements. Valid
partial receipts, recurring amounts and documented refunds remain clean.

The oracle has no inspection requirement and therefore achieves return 1 at
zero inspections. This is an achievable score bound, not evidence of agent
capability. A separate test performs two inspections before the same oracle
submission and obtains 0.996 from the common scorer, proving its cost is real.

## Worked input and output

For `company-b`, the payment list returns `pay-627`, document `doc-492`, with
an explicit directive of **7,000,000** minor units to `inv-264`. The ledger
contains an allocation of **5,000,000**. Opening `doc-492` returns the payment
and `settlement:pay-627`, whose allocation confirms that amount. Thus:

```text
missing allocation = 7,000,000 - 5,000,000 = 2,000,000 KZT minor units
affected IDs       = [pay-627, inv-264]
evidence IDs       = [doc-492, settlement:pay-627]
type               = payment_allocation
currency           = KZT
```

The document response alone contains the directive and settlement needed for
this proof; the list makes the document ID discoverable. Reconciliation also
lists invoices and ledger, for four inspections in total, then submits. With
TP=1, FP=0, FN=0, F1=1, the score is `2*1 - 1 - .002*4 = .992`.
Silence on these faulty books gives −1. On the clean copy, no gap remains and
the same inspection plan submits an empty answer for .992. Four unsupported
mass accusations instead yield FP=4 and −1. All policy-visible rewards are 0.

## Capture and metric semantics

The JSONL header contains initial public observation, policy name and policy
version `stage09-v1`. Each event contains episode_id, step (starting at 1),
action, observation, reward, terminated, truncated, info and delivered. These
are delivery snapshots, not observations reconstructed from final records.
Tests mutate policy-side response objects and verify captured history survives.
Fixture actions also reproduce their captured full messages through fresh tools.

`delivered=false` retains the supervisor's response attempt when the pipe cannot
complete before the deadline. A timeout between actions produces an additional
event with `action=null`, the next event index, `terminated=false`,
`truncated=true`, error `TIME_LIMIT`, and unchanged remaining budget. It is not
a submit action or a policy receipt. Only delivered rows describe messages the
policy received; undelivered rows explain the supervisor's final decision.

`private-result.json` stores common score diagnostics, submitted answer,
precision/recall/F1, return, inspection_steps, total_actions, reason and elapsed
seconds. Linux runs also retain actual process identities and cleanup results.
Private files are created with mode 0600 on Linux. They are never added to the
policy transport or public sample exports. Traces contain submitted findings,
including oracle actions, but never truth or correctness labels in observations.

Elapsed seconds cover supervised execution and jail setup after environment
reset; oracle time covers its trusted submission after reset. They are run
diagnostics, not comparable isolated-agent CPU measurements. Generation/reset
time is excluded. Systematic resource measurement remains Stage 11.

## Commands and observed results

Executed from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage08.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage09.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
git diff --check
docker build -t audit-rl-env:stage09 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage09 python -m pytest -q
```

The normal entry point was run with a trusted output bind mount:

```powershell
docker run --rm --network none --cpus 2 --memory 4g --mount "type=bind,source=$($PWD.Path)\runs\stage-09\isolated,target=/results" audit-rl-env:stage09 python -m audit_env.baselines --fixture company-a --output /results/company-a
docker run --rm --network none --cpus 2 --memory 4g --mount "type=bind,source=$($PWD.Path)\runs\stage-09\isolated,target=/results" audit-rl-env:stage09 python -m audit_env.baselines --fixture company-b --output /results/company-b
docker run --rm --network none --cpus 2 --memory 4g --mount "type=bind,source=$($PWD.Path)\runs\stage-09\isolated,target=/results" audit-rl-env:stage09 python -m audit_env.baselines --generator-config configs/stage08-large-mixed.json --seed 7091 --output /results/large-mixed
```

Stage 08 prerequisite checks: **52 passed, 1 Linux-only check skipped**.
Final Stage 09 portable checks: **27 passed, 5 Linux-only checks skipped**.
Final full portable suite: **234 passed, 15 Linux-only checks skipped**.
Final prepared Linux suite: **248 passed, 1 unsupported-platform guard skipped**.
`pip check` and `git diff --check` passed. The prepared Linux checks require isolation and exercise all
four adapters on both fixtures and a large mixed episode, plus real sleeping
policy cleanup and a clean subsequent episode. Linux/local action and response
snapshots agree exactly. Tests cover each individual family at company seed
92341 and both large profiles at seed 7091. No private input enters ordinary
adapters. The separate oversized answer terminates internally at −1; the valid
mass attack is scored as FP instead of rejected by schema validation.

Normal CLI large-mixed reconciliation: **TP=12, FP=0, FN=0, F1=1**, **21
inspections + submit = 22 actions**, return **0.958**. Random uses 21 actions,
return −1; mass accusation uses 3 actions, FP=30, return −1; oracle uses one
submit, return 1. Fixture reconciliation uses 5 actions and returns .992 on
both books. Oracle uses one action and returns 1 on both. All delivered closed
wire rewards are zero. Observed isolated policy durations for the large run
were about 0.37–0.43 seconds including jail setup; this is a smoke measurement.

Ten actual Linux captures (438,929 bytes) are retained outside ignored output:
all four policies on each fixture, large-mixed reconciliation, and a real
sleeping-policy timeout. Their JSON, event indices, closed rewards, terminal
flags and absence of private result files were checked. The timeout was retained
by rerunning `tests/test_stage09.py::test_linux_timeout_capture_and_fresh_adapter`
with `--basetemp /results/retained-timeout` and the same trusted bind mount:
**1 passed**. Its final event has action null, delivered false, remaining_steps
100, TIME_LIMIT and truncated true; the evaluator action counter remains zero.
No required Stage 09 check remains blocked.

## Limits and study checkpoint

The random and accusation baselines intentionally do not establish complete
proofs; their failure is expected. Reconciliation assumes the published posting
roles and current four families. It has not demonstrated arbitrary accounting
reasoning, professional audit fitness, or model training improvements. Ordinary
CLI execution requires the prepared root Linux image; the portable local runner
is a trusted test harness with no isolation guarantee. Full transformed replay,
public 10+10 splits, and 20-episode/80-run evaluation remain later stages.

Study checkpoint: **Replay one baseline finding. Which tool responses are
sufficient to prove it? Where does its cost enter the final score?** For the
worked allocation, the payment document's directive and settlement establish
the gap; the payment list discovers its ID. Every pre-submit call, including
extra invoice/ledger lists, costs .002 in the evaluator's final return.

Next stage: **10 — Replay, paired transformations and dataset splits**.
