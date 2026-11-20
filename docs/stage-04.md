# Stage 04 execution record

Date: 20 November 2026. Status: **passed** for Stage 04 acceptance locally.

Read repository guidance, the organizer brief, requirements R05–R06, the Stage
04 roadmap entry, schemas, Stage 02–03 records, fixtures and existing tests. The
Stage 03 scorer was present and the Stage 02 fixture/schema suite was available.
Existing uncommitted work was preserved.

## Deliverables and reading order

1. `audit_env/environment.py`: fixture reset, five tools, cursor pagination,
   bounded Decimal parser, action budget, terminal scoring and reward masking.
2. `audit_env/runner.py`: trusted fixture runner and scripted demonstration.
3. `audit_env/__main__.py`: `--demo-fixture` command that prints agent-visible
   observations and prints evaluator score separately.
4. `tests/test_stage04.py`: lifecycle, tool, limit and fixture-run checks.
5. `tests/fixtures/provisional-trajectory.jsonl`: initial observation metadata
   followed by the five observed action/response events from the fixture run.
6. `README.md`: demo instructions and the Stage 05 isolation boundary.

The five tools are `list_records`, `get_record`, `get_document`, `calculator` and
`submit`. Lists retain fixture order, return no more than 50 rows and use
table-scoped `table:index` cursors. Payment documents include the public
settlement view derived from the final ledger. All tool responses contain only
the requested public result or a short error code and remaining budget.

Every attempted active action consumes one step. Submit is action 100 when 99
actions preceded it and receives the score for 99 pre-submit actions. A 100th
non-submit action truncates with empty findings and includes all 100 actions in
the reward cost. Malformed submission terminates at private score −1. Closed
mode sends numeric reward 0 for terminal results; the trusted runner reads the
score separately. A later call after completion returns `EPISODE_CLOSED` without
changing the score or action count. Reset clears the counter, terminal flag,
submission and evaluator result.

The calculator supports decimal literals, parentheses, unary signs, addition,
subtraction, multiplication and division. It limits expressions to 256
characters, nesting to 16, arithmetic precision to 34 digits, and result scale
to a bounded exponent. Unsupported tokens, division by zero, excessive sizes and
decimal arithmetic errors return `CALCULATOR_ERROR` without exception details.

Previous observations are detached snapshots: responses are newly serialized,
so a caller changing one returned dictionary cannot alter episode records or a
later response. The fixture policy and evaluator still run in one trusted Python
process in this stage. Stage 05 must establish a real process boundary and
deadline enforcement; Stage 04 does not claim isolation.

## Worked episode

The company B payment document directs 7,000,000 minor units to invoice
`inv-264`. Its public settlement shows 5,000,000 applied, leaving 2,000,000
unapplied. The demo calculates `(70000 - 50000) * 100 = 2000000`, submits the
fixture's supported finding, and receives closed-mode reward 0. The trusted
runner reports score 0.992 because the answer is perfect (F1=1) after four
pre-submit actions: `2×1 − 1 − 0.002×4 = 0.992`.

## Verification actually executed

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_stage04.py
.\.venv\Scripts\python.exe -m audit_env --demo-fixture company-b
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Stage 04 acceptance suite: **11 passed**. The normal entry point printed five
policy-visible observations with reward 0, then printed `Trusted evaluator
score: 0.992`; it generated `tests/fixtures/provisional-trajectory.jsonl`.
The final full suite passed: **61 passed**. `git diff --check` exited 0 and
repeated the existing CRLF-to-LF normalization warning for `audit_env/__main__.py`.
The early focused run had two expectation mistakes, both corrected from the
contract: the demo costs three pre-submit actions, and silence on clean truth is
a valid perfect answer.

## Study checkpoint

Trace `get_document("doc-492")` as step 3 in the trajectory. `step` increments
`self._steps` before dispatching the action. `_get_document` then finds the
payment by `doc_id`, derives its settlement from public ledger rows, serializes
both into the observation, and returns 97 remaining steps. The settlement proof
shows a 7,000,000 receipt, 5,000,000 applied and 2,000,000 unapplied; the policy
can compare that with the payment's invoice directive.

Question: what changes at action 100 depending on whether the action is submit or
an inspection, and how does closed mode keep the reward from revealing the
score?

Next stage: **05 — Enforce the process boundary and deadline**.
