# Published jury checks: integration

The definitions dated 20 November 2026 are preserved in `fintech-checks.md`.
They take precedence over earlier transport choices in the stage notes.
The native API remains available; `judge_adapter.py` implements the jury API
without selecting actions or changing a policy's strategy.

## Contract and access

Run from `/app` in the newly built Linux image. Import `judge_adapter` only in
the trusted jury process. Its entry points are `generate_episode`, `make_env`,
`score_episode`; README documents arguments, layouts and output shapes.
Generation creates the six public files at the requested root and evaluator
material in `private/`. Loaded jury episodes require only public files and
truth, not clean/history or this project's own transformation algorithm. Root
truth is also accepted. File order and IDs survive reset exactly as supplied.

Ordinary policies run through `run_isolated_policy` in the existing Linux jail,
using unchanged name/args actions and standard transition messages. It shares
the environment, wire allowlists, resource limits and cleanup with the native
runner. The deadline includes reset, jail preparation and policy execution.
Direct `make_env` is a trusted host API, not a sandbox; a nonresponsive policy
requires the external supervisor. No evaluator files are mounted in the jail.

Closed rewards are zero including submission and truncation. Train mode sends
the terminal reward. `score_episode` is evaluator-only, reports six metrics and
return, and returns null metrics with return -1 for invalid structures, logging
the bounded validation code privately. Unknown string issue labels instead
remain well-formed false positives. All four known labels, canonical targets,
evidence rules and zero monetary tolerance retain their published meaning.

## Local coverage

`tests/test_judge_adapter.py` covers reset snapshots, JSON transport, tools and
safe errors, stable pages, terminal immutability, action 100, train/closed mode,
reset-start timing, external file edits without private history, invalid metric
semantics, unknown labels, all twenty numerical reward vectors, captured wire
messages, and Linux-only real jail and sleeping-policy probes. Existing stage
tests additionally cover exact ID/evidence normalization, ambiguous maximum
matching, private sentinels, refunds, accounting and causal replay.

`python -m audit_env.judge_checks --output runs/jury-matrix.json` creates and
independently validates twenty data cases: five clean, three duplicates, three
allocations (missing and partial), two FX, two cutoff, three boundary interaction
and two duplicate/FX interaction cases. It loads source and transformed files
through the actual adapter, checks repeat replay and remapped oracle scores at
equal cost. P01-P05 change order only, P06-P10 IDs only, P11-P20 both. A report
is retained in `evaluator/jury-2026-11-20/matrix.json`. These are local examples,
not the jury's hidden values or a claim of official certification.

The single offline verifier also runs this matrix, writes `jury-matrix.json`,
and retains the existing 80-run policy benchmark and other checks.

## Verification and release status

The local D01-D20/P01-P20 matrix passed. The portable full suite passed 299 tests,
with 22 Linux-only cases skipped. Results are recorded in
`evaluator/jury-2026-11-20/portable-tests.txt`. After the Linux engine became
available, the rebuilt image passed 320 tests with only the Windows-specific
guard skipped. Both new jury isolation tests ran. The complete verifier passed
all 80 policy/episode runs, 20 original pairs, D01-D20/P01-P20, actual timeout
cleanup and incorrect-expectation rejection. Results and trajectories are in
`evaluator/jury-2026-11-20/verification/`. Reconciliation mean F1 was 1 and return
.9689; oracle return was 1. Maximum measured episode wall time was 2.8929 seconds.
The three-case demo returned .992, .992, -1 and is retained in the sibling
`demo/` directory. Dependency inventory and all 14 exported schemas agree with
the verified image; its runtime source digest agrees with the working source.
Run from the repository root with Docker's Linux engine available:

```sh
docker build -t audit-rl-env:jury-checks .
docker run --name audit-jury-check --network none --cpus 2 --memory 4g audit-rl-env:jury-checks python -m audit_env.verify --output /tmp/jury-verification
docker cp audit-jury-check:/tmp/jury-verification ./runs/jury-verification
```

The saved `audit-rl-env-jury.image.tar.gz` was successfully loaded back into
Docker. Its identity and source digest are in `release/jury-image-lock.json`.
The source ZIP is rebuilt with the retained evidence; `jury-source-status.json`
and `jury-SHA256SUMS` identify the new pair of delivery files. ZIP text uses LF;
the image retains original build-context line endings, with identical runtime
code. The rc1 archives, image lock and rehearsal remain historical artifacts.
A new clean-checkout rehearsal on another physical machine is not claimed.
