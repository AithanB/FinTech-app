# Stage 02 execution record

Date: 20 November 2026. Status: **passed** for Stage 02 acceptance locally.
Docker verification remains unavailable from this agent session.

Read docs/AGENTS.md, task.md, requirements.md (especially R02–R06), ROADMAP.md,
README.md and the existing smoke entry point. No organizer/local contract
conflicts were found. Preserved the existing untracked project documents.

The Stage 01 Python smoke check still passes on Python 3.11.9. Docker was reported to run after its earlier availability issue. In this
session `docker info --format '{{.OSType}}'` exited 1 because the
dockerDesktopLinuxEngine named pipe was not found. Thus the earlier Stage 01
container gap remains unverified by the agent; no container build/run is claimed.
The executable Python baseline needed by Stage 02 is available.

## Deliverables and reading order

1. docs/schemas.md: value formats, IDs, counts, account conventions and calculation.
2. tests/fixtures/company-a/public and company-b/public: hand-authored clean and
   underapplied versions of the same company. Three FX rows also exercise rate
   representations; they do not create foreign invoice/payment issues.
3. audit_env/schemas.py: strict public, private, submission, action and reply
   Pydantic contracts; audit_env/serialization.py: CSV/JSON/JSONL IO.
4. audit_env/views.py: final-ledger per-payment settlement evidence.
5. tests/fixtures/company-b/private: independent truth, complete expected finding
   and the two changed ledger fields belonging to the single allocation defect.
6. tests/fixtures/action-examples.json and tests/test_stage02.py: all five action
   examples and the acceptance suite. README.md documents runnable commands;
   audit_env/__main__.py adds optional public fixture inspection.

The expected arithmetic was stated before implementation: 100,000 − 70,000 =
30,000 KZT outstanding; 70,000 − 50,000 = 20,000 KZT missing application, or
2,000,000 minor units. Expected truth and submission are literal fixture files;
there is no generator or matcher in this stage.

## Verification actually executed

From the repository root, using the existing Python 3.11 virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m audit_env
.\.venv\Scripts\python.exe -m audit_env --fixture tests/fixtures/company-a/public
.\.venv\Scripts\python.exe -m audit_env --fixture tests/fixtures/company-b/public
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Dependency check: no broken requirements. Smoke: expected Decimal 0.3 and
Asia/Almaty. CLI settlements: company A receives/applies 7,000,000/7,000,000 and
leaves 0 unapplied; company B receives/applies 7,000,000/5,000,000 and leaves
2,000,000 unapplied. All commands above exited 0. Final pytest result: **42 passed**.
Git emitted only a CRLF-to-LF normalization warning for the modified entry point.

Tests round-trip both complete public episodes and private models, explicit null
links, timezone offsets including UTC and −03:30, decimal rates with trailing
zeros, JPY exponent and integer amounts beyond binary-float precision. They
reject Boolean/non-integer amounts, nonfinite/nonpositive/numeric-wire rates,
naive timestamps, extras, omitted nullable fields, bad counts and malformed CSV
numbers. They validate all action examples and submission size limits. Accounting
checks derive receivables directly from rows, verify journal balance, compare
directives to settlement and verify the expected private finding. A separate case
removes all application rows and verifies discoverable zero-allocation evidence.

## Study checkpoint

Trace doc-492 → pay-627 → invoice_refs[0].invoice_id = inv-264. The invoice's
document ID is doc-813. doc_id identifies documentary evidence; payment_id and
invoice_id identify the two affected business objects. The settlement evidence
ID is settlement:pay-627. An invoice's unpaid balance alone cannot prove missing
allocation: the payment directive and actual settlement establish the discrepancy.

Next stage: **03 — Implement the matcher and common reward**. Stage 02 stops
before scoring and executable environment actions.
