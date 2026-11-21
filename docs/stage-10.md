# Stage 10 — Replay, paired transformations and dataset splits

Status: **passed**. This stage delivers replay,
benign transformations, exactly ten train plus ten dev exports, twenty separate
rehearsal inputs and a reproducible paired-check report. The 80 policy runs and
consolidated `audit_env.verify` entry point remain Stage 11. Existing work from
earlier stages was preserved; no organizer-contract conflict was found.

## Changed files and reading order

1. `audit_env/transformations.py`: `stage10-transform-v1`, complete bijective
   ID map, recursive reference rewriting, description changes and independent
   per-table permutations. `remap_ids` also handles actions, tool results and
   materialized public summaries. Provenance's embedded ledger-row JSON is
   parsed, rewritten and reserialized, rather than treated as prose.
2. `audit_env/replay.py`: `stage10-replay-v1`, exact semantic action replay,
   captured response verification, oracle remapping and equal-cost paired checks.
3. `configs/stage10-splits.json` and `audit_env/datasets.py`: frozen input plan,
   export/check CLI, trusted loader, causal-history/reference validation and
   deterministic report generation.
4. `episodes/split-manifest.json`, `episodes/train/`, `episodes/dev/`, and
   separate `evaluator/stage10/`: delivered public files, evaluator material and
   `paired-checks.json`. The plan itself supplies the twenty rehearsal inputs.
5. `tests/test_stage10.py`: independent fixture calculation, inverse remapping,
   nested settlement/provenance checks, exact replay, dataset integrity, twenty
   pairs and real policy-isolation probes.

Supporting changes: `AuditEnvironment.reset_episode(public, truth, mode=...)`
is a trusted loader, separate from actions and reset's public wire contract.
The baseline and isolated runners accept loaded episodes; ordinary policies
receive the existing public initial observation and tool messages. The baseline
CLI adds paired `--episode` and `--evaluator` paths. `Dockerfile` protects the
evaluator tree and makes public exports read-only. JSON/JSONL serializers now
write explicit LF, matching CSV, so Windows-produced artifacts verify byte for
byte inside Linux. The README and schema guide document these choices.

## Identity and ordering rules

Every episode, document, invoice, payment, row, journal, entity, issue and latent
event ID is remapped. References in invoice directives, refund links, affected
objects, every alternative proof, history, FX decisions and causal row snapshots
follow the same map. Null links stay null. The map is one-to-one over its complete
domain and rejects collisions, omitted IDs and inconsistent derived IDs.

FX evidence keys remain `fx:date:source:target`, because they identify unchanged
economic rate keys. They are fixed points of the bijection. Settlement evidence
becomes `settlement:<new payment ID>`. Public settlement summaries are recomputed
from transformed payments and ledger rows; tests compare every nested allocation
and ledger reference against the mapped original. Sorting in a recomputed
summary may change when IDs or input rows change; membership and values agree.

Public and clean ledger/invoice/payment/FX tables are permuted with local seeded
RNGs. Posting sequence remains unchanged because it identifies original versus
extra recognition, rather than storage order. Dates, timezone policy, currencies,
rates, amounts and accounting roles remain unchanged. Synthetic business names
live in invoice line descriptions and latent sale descriptions; these are
changed consistently without introducing a new record schema or label hints.

Matching diagnostics are sorted by issue ID. Remapping IDs can therefore reorder
the diagnostic list; the paired checker sorts mapped pairs by the new IDs before
comparison. This first surfaced as a failed checker comparison on the 12-issue
mixed profile. Its TP/FP/FN, score and actual matched pairs already agreed. The
checker was corrected without changing the scorer or removing the fixture.

## Worked input and output

The hand-authored `company-b` fixture supplies an independent expectation:
7,000,000 directed to `inv-264`, only 5,000,000 applied by `pay-627`, so the
allocation discrepancy is **2,000,000 KZT minor units**. A test explicitly maps
`pay-627` to `payment-renamed` and consequently maps the evidence key to
`settlement:payment-renamed`. The invoice and payment document IDs also change.

Reconciliation submits the same amount and currency with the remapped affected
pair and complete document/settlement proof. Both episodes use four inspections
and one submit. With TP=1, FP=0, FN=0, both returns are **0.992**:
`2*1 - 1 - .002*4`. A mapping that changes only the payment but leaves the old
settlement evidence is rejected. This works because identity changes preserve
the accounting relationships from which the discrepancy is computed.

## Split contents and privacy

Version `stage10-splits-v1` freezes 40 unique seeds and full normalized configs:

- Train: seeds 10001–10010, invoice counts 36–45, three clean, four single,
  three interacting episodes.
- Dev: seeds 20001–20010, invoice counts 46–55, two clean, five single,
  three interacting episodes.
- Rehearsal: seeds 30001–30020, five clean, ten single and five interacting
  episodes. Invoice counts are 60–78, then 99 in the last mixed case.

All seeds and normalized parameter mixes are disjoint across all three groups.
Amounts, currency ordering, timezones, company size and issue combinations vary.
Each public split covers all four families and both scenarios. Mixed cases have
12 issues; the upper rehearsal case reaches 200 documents. These are local
rehearsal inputs, not jury cases or claims about hidden evaluation coverage.

Each public episode directory contains only the six public files. Its opaque
episode ID carries no explicit issue category. `episodes/split-manifest.json`
records split membership, source seed, config index, actual counts, public path
and semantic SHA-256. Public seeds/configs are available to the owner for
reproduction, while ordinary policies receive neither their files nor values.

Evaluator-only clean records, truth, history and provenance occupy a separate
directory per episode under `evaluator/stage10/{train,dev}/`. Private files have
mode 0600 and episode directories 0700 in Linux. Docker additionally removes
all group/other access throughout the evaluator tree. A jailed policy has no
mount of either tree and no host paths or inherited handles. Tests attempt read
and write access to actual exported data, configs and a private sentinel, verify
denial and confirm cleanup. Windows local tests do not claim a Unix permission
boundary; ordinary execution uses the prepared Linux jail.

The exporter verifies existing matching files and rejects stale directories,
extra public/private files, changed bytes and overlapping inputs. It does not
silently repair modified data. `--check` verifies existing artifacts. The tests
retain a deliberately corrupted temporary export after verifying rejection.

## Replay and paired report

For every rehearsal input the checker generates the same version/seed/config
twice, compares complete public records, and executes exactly the same action
sequence on both. Initial observations, responses, budget, flags, public rewards,
submitted answer and private score diagnostics agree. Semantic SHA-256 excludes
wall time, process IDs and delivery timing. Tests also cover open terminal
rewards, paging, errors, malformed submit, 100-inspection truncation and explicit
timeout events, plus the retained Stage 09 fixture captures.

Each paired episode receives four actual inspections (ledger list, payment list,
payment document, calculator) plus the oracle submit. Its answer is obtained by
remapping the source action and compared with the transformed truth oracle.
Amounts/proofs are independently reconstructed from final public evidence.
The checker validates causal mutations against clean rows and verifies the final
ledger, then runs public-data reconciliation on every transformed episode.
Clean description/order controls stay clean. The paired report records equal
cost, equal returns, source/repeated replay hashes, transformed public hash and
actual reconciliation action count for each of the twenty pairs.

A timeout between requests is replayed as an explicit supervisor event, without
adding an action. Its undelivered response stays distinguished from an agent
receipt. Replay reproduces this recorded event's semantics; it does not promise
that a wall-clock timeout will recur at exactly the same instant.

## Commands and measured results

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage09.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage10.py
.\.venv\Scripts\python.exe -m audit_env.datasets
.\.venv\Scripts\python.exe -m audit_env.datasets --check --paired-report evaluator/stage10/paired-checks.json
.\.venv\Scripts\python.exe -m pytest -q
docker build -t audit-rl-env:stage10 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage10 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage10 python -m audit_env.datasets --check --paired-report evaluator/stage10/paired-checks.json
```

Stage 09 prerequisite: **27 passed, 5 Linux-only checks skipped**. Stage 10
portable checks: **19 passed, 2 Linux-only checks skipped**. Export/check CLI:
**10 train + 10 dev verified**, **20 paired checks passed**, five clean and five
interacting, return .992 on both sides at equal four-inspection cost.
Full portable suite: **253 passed, 17 Linux-only checks skipped**. Prepared
offline Linux suite, with isolation required: **269 passed, 1 unsupported-platform
guard skipped**. Every supported Linux isolation check ran, including all four
adapters on transformed clean/mixed episodes and actual exported-file probes.
`pip check` and `git diff --check` passed. No required Stage 10 check is blocked.

The normal Linux dataset CLI independently verified the Windows-produced files
and existing paired report byte for byte. A real mixed dev episode was also run
through all four adapters with a trusted output bind mount:

```powershell
docker run --rm --network none --cpus 2 --memory 4g --mount "type=bind,source=$($PWD.Path)\runs\stage-10\isolated,target=/results" audit-rl-env:stage10 python -m audit_env.baselines --episode episodes/dev/ep-e84b40bfab1eef3d6dfb233c --evaluator evaluator/stage10/dev/ep-e84b40bfab1eef3d6dfb233c --output /results/exported-dev
```

Reconciliation found **TP=12, FP=0, FN=0, F1=1**, with **16 inspections + submit
= 17 actions**, return **0.968**. Random gave TP=0, FP=5, FN=12 and return −1;
valid mass accusation gave FP=30, FN=12 and return −1; oracle gave TP=12, no FP
or FN, one submit and return 1. The retained traces under ignored
`runs/stage-10/isolated/exported-dev/` contain delivered public snapshots with
zero closed rewards; evaluator results remain separate. This is a single demo,
not the Stage 11 full benchmark.

All **120 public record files** are present. Actual train sizes are **224–280
ledger rows / 74–92 documents**; dev sizes are **284–340 / 94–112**. Across the
twenty transformed rehearsal cases, public reconciliation required at most
**24 actions**, including submit. The retained report and inputs are
outside ignored `runs/`; no commit, push, publication or submission was performed.

## Limits and study checkpoint

The generator still covers November 2026 and roughly 600 ledger rows at its
current upper profile. Paired checks demonstrate the published issue families,
reference structure and economic invariants. They do not establish general
accounting reasoning. Seeded policy behavior can depend on response order;
wall-clock timing is deliberately excluded from semantic replay. Freeze/release
packaging, fresh-checkout rehearsal and the 80-run benchmark remain later work.

Study checkpoint: **Why should identical actions replay on an identical episode,
while a reasonable explorer may choose a different path on reordered records?**
The unchanged episode preserves stable page order, IDs and arithmetic, so every
request sees the same state. A reordered episode changes which objects appear
on a page and which candidate an explorer selects next. The explorer may follow
a different path while the correctly remapped supported answer and equal-cost
score remain equivalent.

Next stage: **11 — Offline evaluation and measured failures**.
