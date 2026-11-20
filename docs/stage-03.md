# Stage 03 execution record

Date: 20 November 2026. Status: **passed** for Stage 03 acceptance locally.

Read the repository guidance, organizer brief, requirements R04/R06, roadmap,
schemas guide, Stage 02 record, schemas, both hand-authored company fixtures and
the existing tests. Stage 02 prerequisite check passed before changes: 42 tests
passed. Existing uncommitted Stage 02 files were preserved.

## Deliverables and reading order

1. `audit_env/scoring.py`: strict submission validation, compatibility graph,
   deterministic maximum matching, private diagnostics and common reward.
2. `tests/test_stage03.py`: independent cases for exact matching, evidence,
   duplicates, ambiguity, limits, empty cases and score cost.
3. This record: published matching decisions, hand calculation, commands and
   study checkpoint.

Validation uses the Stage 02 `Submission` model and verifies the episode ID.
Malformed submissions return a private score result of −1 with a bounded error
code. A structurally valid claim with unknown evidence or objects remains a
prediction, but cannot match. Predictions are retained individually; therefore
a copied correct finding can earn only one TP and all additional copies are FP.

Compatibility requires exact type, exact unordered affected-ID set, exact
minor-unit amount, exact currency, supplied evidence IDs that all exist in the
public evidence-ID set, and at least one complete truth proof contained in the
supplied evidence. Explanations are validated for size but do not affect grading.
Tolerance is exactly zero after the schema's prescribed posting rounding.

The matcher first computes maximum cardinality, then chooses the lexicographically
smallest sorted list of `(issue_id, submission_index)` pairs among all such
matchings. It tests each candidate edge by asking whether the remaining graph
can still reach the maximum size. This avoids greedy edge choices that would
discard a true positive. The `ScoreResult` diagnostics are trusted-runner data;
closed-mode transport must not expose them to the policy.

## Worked calculation

Company B has one 2,000,000-minor-unit allocation truth. Submitting its complete
expected finding twice produces TP=1, FP=1, FN=0. Thus precision = 1/2, recall
= 1, and F1 = 2/3. At 20 pre-submit actions, R06 gives:

```text
clip(2 × 2/3 − 1 − 0.002 × 20, −1, 1)
= 1/3 − 0.04
= 0.2933333333333333
```

A perfect finding set scores 0.96 after 20 inspections and 0.90 after 50.
Silence on empty truth has F1=1; an accusation on empty truth has F1=0. Both
empty sets use the explicit F1=1 convention. A fully wrong answer bottoms at
−1 after reward clipping.

## Verification actually executed

Prerequisite check before implementation:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result: **42 passed**.

Stage 03 checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_stage03.py
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

The first Stage 03 run exposed only an over-rounded test expectation: the exact
duplicate reward is 0.293333…, not 0.293. The independent formula was retained
and the assertion now compares to `1/3 − 0.04`. Final Stage 03 suite result:
**8 passed**. Final full suite result: **50 passed**. `git diff --check` exited 0;
Git repeated the pre-existing CRLF-to-LF normalization warning for
`audit_env/__main__.py`. Docker is not part of this stage's acceptance and
remains unverified as recorded in Stage 02.

## Study checkpoint

Before running the scorer: one correct prediction gives P=R=F1=1 and, with no
pre-submit actions, score 1. A correct prediction plus its duplicate gives TP=1, FP=1,
FN=0, P=0.5, R=1, F1=2/3 and at 20 actions score 0.293333…. The duplicate
still exists because matching normalizes IDs only within each finding; it never
deduplicates the submitted prediction list. Maximum one-to-one matching consumes
the single truth once, leaving the second prediction as a false positive.

Question: if two predictions and two truths are all mutually compatible, which
pair list wins the tie, and how does the implementation preserve maximum
cardinality before applying that tie rule?

Next stage: **04 — Deliver a complete episode using a fixture**. Stage 04 will
connect this scorer to reset/step, tool actions and terminal reward transport.
