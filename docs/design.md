# Financial audit environment: release design

One episode represents one synthetic company and reporting month. A trusted
generator builds latent sales and cash events, derives coherent documents and
balanced books, then mutates selected postings. Clean data, causal provenance
and truth stay with the evaluator. Public records independently establish all
four issue families and the two interacting scenarios. Integer minor units,
directional Decimal FX rates, explicit currency exponents and timezone policy
make discrepancies reproducible. Supported profiles reach 604 ledger rows and
200 documents; they do not reach the suggested 2,000-row upper envelope.

The trusted runner owns inputs, reset state, the 100-action budget and monotonic
deadline. Ordinary policies run as uid/gid 65534 inside a data-free Linux chroot,
with a seccomp allowlist, bounded pipes, resource limits, no inherited handles
and no network or evaluator mounts. Records arrive only through the five JSON
actions. The calculator uses a restricted decimal parser. Windows is a portable
test harness, not the isolation boundary. The evaluator is trusted; root/kernel
compromise is outside this boundary.

Public closed-mode rewards are zero. After submission, strict validation and
deterministic maximum-cardinality matching grade type, exact canonical objects,
currency, amount and at least one complete evidence set. Duplicates become false
positives. An invalid envelope terminates at -1. The unchanged common reward is
`clip(2*F1 - 1 - .002*inspection_steps, -1, 1)`. Empty clean answers have F1=1;
undefined precision/recall are zero. No prose style earns credit.

Versioned local RNG streams preserve generation and semantic replay. Complete
bijective ID rewriting includes settlement evidence, nested links and embedded
provenance. Benign descriptions and row order vary independently. Twenty paired
checks preserve remapped oracle answers and equal-cost scores. Ten train and ten
dev episodes have seeds and parameter mixes disjoint from twenty local rehearsal
cases. These local cases are not jury hidden evaluation.

Four fixed adapters expose random exploration, public-data reconciliation,
schema-valid mass accusation and a trusted oracle. The Stage 11 report retains
80 episode/policy results, delivered trajectories, separate scores and measured
failures. Reconciliation found all 30 issues with mean return .9689; oracle
returned 1, while the two accusation strategies averaged -1. Five clean episodes
explain perfect policies' .75 mean precision/recall despite F1=1. The random
failure on seed 30007 is silence with a false negative, not a step timeout.

The single `python -m audit_env.verify` command requires offline Linux, runs all
supported tests, validates exports, checks pairs and actual timeout/rejection
controls, then benchmarks the four adapters and reconciles saved artifacts.
Fresh workers yield per-episode RSS high-water marks; their sum is explicitly a
conservative bound. Full inputs, versions, source digest and hardware are logged.
Stage 12 adds a three-case demo, payload digests, exact dependency notices,
immutable image identity and a fresh-checkout rehearsal. See `release/INVENTORY.md`.

Known limits: recognition roles and KZT base currency follow this generator's
published conventions; synthetic month/size coverage is narrow. Record ordering
can change an explorer's path. RSS bounds are not simultaneous process-tree
peaks, and timings depend on the host. Passing oracle checks establishes that
correct supported answers can receive the published reward; it does not
demonstrate agent competence, training improvement or professional audit fitness.
