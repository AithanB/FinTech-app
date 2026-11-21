# Release candidate inventory

The current jury delivery adds `judge_adapter.py`, `docs/fintech-checks.md`,
`docs/judge-adapter.md`, `tests/test_judge_adapter.py` and the full successful
offline results in `evaluator/jury-2026-11-20/verification/`. The delivery files
are `audit-rl-env-jury-source.zip`, `audit-rl-env-jury.image.tar.gz`,
`jury-SHA256SUMS`, and `jury-source-status.json` under `release/artifacts/`.
The current image is locked in `release/jury-image-lock.json`; it includes the
new jury entry points. The rc1 delivery described below is historical evidence.

The candidate is the source/evidence ZIP plus the saved prepared image in
`release/artifacts/`. `SHA256SUMS` there identifies those delivery files. A hash
inventory inside the ZIP, `release/payload-manifest.json`, covers every payload
file except itself. Generated archives and image exports are excluded from
their own payload/build context. The release is assembled from the source snapshot.
For external handoff, put the ZIP, compressed saved image, `SHA256SUMS` and
`sizes.json` together. Extract the ZIP beside the image as the README describes.
`release/artifacts/` is their location in the development workspace; the large
delivery files are deliberately not embedded inside the source ZIP.

## Organizer deliverables

- Licensed sources: root `LICENSE`, `THIRD_PARTY_NOTICES.md`, `release/licenses/`.
- Pinned application dependencies: `requirements.txt`; installed runtime and
  builder packages: `release/dependency-lock.json`; base digest: `Dockerfile`;
  prepared image reference and sizes: `release/image-lock.json`.
- Generator and accounting: `audit_env/generation.py`, `composition.py`,
  `accounting.py`, `validation.py`; versioned settings: `configs/`.
- Environment and trusted transport: `audit_env/environment.py`, `wire.py`,
  `isolation.py`, `scripts/agent_bootstrap.py`, `build_agent_runtime.py`.
- Public schemas and tools: `audit_env/schemas.py`, `docs/schemas.md`,
  `release/schemas/*.schema.json`. Private truth schemas are separately named.
- Open matcher, normalization, exact amount tolerance, tie-breaking and common
  reward: `audit_env/scoring.py`, `docs/schemas.md`.
- Exactly ten public train and ten dev companies: `episodes/train/`,
  `episodes/dev/`, `episodes/split-manifest.json`. Evaluator counterparts:
  `evaluator/stage10/{train,dev}/`. The policy jail sees none of these paths.
- Four adapters: `policies/baselines.py`, `policies/oracle.py`,
  `audit_env/baselines.py`. Oracle alone receives evaluator truth.
- Environment/matcher/reward/attack/isolation tests: `tests/test_stage02.py`
  through `test_stage12.py`; hand-authored fixtures: `tests/fixtures/`.
- Delivered trajectories: `episodes/examples/stage09/`, all eighty
  `evaluator/stage11/trajectories/*/*/trajectories.jsonl`, separate private
  results, `evaluator/stage12/demo/` and fresh rehearsal evidence in
  `release/rehearsal/`. None depend on ignored `runs/`.
- Design, measured failures and limits: `docs/design.md`, `docs/stage-11.md`,
  `evaluator/stage11/report.md`, `docs/stage-12.md`.
- Single verification command and image preparation: release section of
  `README.md`, `audit_env/verify.py`.
- Scripted supported/clean/failed-accusation demo: `python -m audit_env.demo`,
  retained cases in `evaluator/stage12/demo/`, walkthrough `docs/demo.md`.

## Rubric evidence and limits

- Contract/isolation (25): full offline isolation-required test suite and three
  genuinely jailed demo policies; lifecycle, deadline, protocol and permission
  probes. Local checks do not claim the organizers' exact 20 hidden checks.
- Data/truth (25): pre-mutation invariants, causal replay and independent public
  proof reconstruction; all four families, two interactions and clean distractors.
  The independent 7M-minus-5M fixture anchors allocation semantics.
- Reward reliability (25): maximum one-to-one matching, valid/invalid attacks,
  duplicates, empty clean answers, exact evidence and cost tests; one false
  accusation is rejected by the same evaluator in the release demo.
- Reproducibility/generalization (15): twenty separate paired checks, stable
  replay, disjoint public/rehearsal inputs. No claim of jury coverage or general
  accounting ability follows from these fixed scripted cases.
- Engineering/explanation (10): one command, frozen versions/configs, all
  trajectories, trace-supported failures and honest limits; final rehearsal
  records in `release/rehearsal/` and study note `docs/stage-12.md`.

The candidate is prepared for review and submission through the announced
organizer channel. No upload, publication, push or submission is performed by
this stage. A fresh checkout plus an already prepared image is tested; a clean
physical machine and a fully offline image build are separate, unverified claims.
