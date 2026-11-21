# ROADMAP — Financial audit RL environment

**For the coding assistant.** The command `Execute stage 04 from the ROADMAP` means implement and verify stage 04 in the current repository, explain it to the owner, and stop at its acceptance boundary. Integers with or without a leading zero refer to the same stage. Stage numbers below are stable references for this English edition.

## How to execute one stage

1. Read AGENTS.md, docs/task.md (organizer brief), docs/requirements.md (R01–R07) and the requested stage. Inspect git status, relevant source, fixtures and tests. Existing code may already satisfy part of the stage. Preserve unrelated work. Organizer clarifications supersede local choices. Record any conflict and its resolution.
2. Check prerequisites with the smallest relevant test or artifact. Repair a minor in-scope prerequisite if necessary. If an entire earlier stage is missing, identify its number and the missing output before implementing dependent behavior.
3. State the observable outcome and one hand-calculated expectation before editing. Implement only the requested behavior and tests. Use the actual module layout and public entry points. Keep the expected result independent of the code under test. Keep an existing failing fixture as evidence while diagnosing the cause.
4. Run the named scenarios through pytest and the normal entry point. Record actual commands, results and any blocked check. Re-running a completed stage should verify existing behavior without duplicate files or needless rewrites.
5. Finish with a brief study note: changed files and reading order, one worked input/output, why the key decision works, the study question below, and the next stage number. Report status as **passed**, **partial** or **blocked**. A stage passes only when its deliverables and acceptance tests have been verified. Allow the owner to request the next stage. Commit, push, publish or submit only under the owner's repository workflow.

## Execution map

| Stage | Outcome | Prerequisites |
| --- | --- | --- |
| 01 | Establish the executable baseline | None |
| 02 | Define schemas and author independent fixtures | 01 |
| 03 | Implement the matcher and common reward | 02 |
| 04 | Deliver a complete episode using a fixture | 02–03 |
| 05 | Enforce the process boundary and deadline | 04 |
| 06 | Generate a clean company, duplicates and allocations | 02–05 |
| 07 | Implement FX conversion and reporting periods | 06 |
| 08 | Compose interacting errors and scale generation | 07 |
| 09 | Connect four policies and capture replayable trajectories | 05–08 |
| 10 | Verify replay, paired transformations and dataset splits | 08–09 |
| 11 | Run the offline evaluation and measure failures | 05–10 |
| 12 | Package, demonstrate and rehearse handoff | 11 |

## Stage 01 — Establish the executable baseline

**Prerequisites and requirements.** None. Read R01 and R07.

**Implementation.** Inspect the checkout, active interpreter, dependency pins and Docker entry point. Reuse the existing audit_env package. Add a minimal CLI smoke check only if missing. Document Windows cmd setup and the prepared Linux runtime.

**Expected outcome.** README setup and one successful import/run with Python 3.11. Document any unavailable tool as unverified.

**Acceptance tests.** Run python -m pip check, python -m audit_env and python -m pytest --version. Build the image and repeat the smoke check with networking disabled when Docker is available. Empty test discovery is not a passing suite.

**Study checkpoint.** Where do dependencies come from during an offline run? Demonstrate the distinction between build and run.

## Stage 02 — Define schemas and author independent fixtures

**Prerequisites and requirements.** 01. Read R02–R06.

**Implementation.** Implement strict public/private Pydantic models, CSV/JSONL readers and serializers. Write a tiny clean company by hand and a second copy with one missing allocation. Add a public per-payment settlement view with stable evidence ID. Publish one example request and reply for every action.

**Expected outcome.** Schemas and fixtures under tests/fixtures, with a worked calculation and complete expected finding written independently of generator code.

**Acceptance tests.** Round-trip null links, timezone offsets, rates and minor units. Reject Boolean amounts, NaN rates and naive timestamps. For an invoice of 100,000 KZT paid 70,000, expect 30,000 outstanding. If only 50,000 is applied, expect 2,000,000 minor units missing. Verify both cases from public evidence.

**Study checkpoint.** Open the fixture and trace doc_id, invoice_id and payment_id. Which one identifies the evidence and which pair identifies the affected objects?

## Stage 03 — Implement the matcher and common reward

**Prerequisites and requirements.** 02. Read R04 and R06.

**Implementation.** Write pure validation, matching and scoring functions. Generate compatibility edges, then find a deterministic maximum one-to-one matching. Keep repeated predictions. Grading uses only submitted fields and permitted evidence sets. Publish tie and tolerance rules beside the code.

**Expected outcome.** A scorer callable with hand-authored truth, a submission and an inspection count. Private diagnostics explain TP/FP/FN.

**Acceptance tests.** One truth + two copies of the right finding gives (1,1,0) and F1=2/3. One wrong currency yields (0,1,1). Two inspections off a perfect answer cost 0.004. Check 20 versus 50 inspections (0.96 vs 0.90), empty cases, unrelated/partial/alternative proofs, guessed IDs, changed prose and ambiguous edges where greedy matching loses a TP. Exercise 30/31, 10/11 and 1000/1001 limits.

**Study checkpoint.** Calculate the score for one correct finding and one duplicate before running pytest. Explain why a duplicate still exists after ID normalization.

## Stage 04 — Deliver a complete episode using a fixture

**Prerequisites and requirements.** 02–03. Read R05–R06.

**Implementation.** Implement reset/step, all five tools, pagination and episode state. Connect a trusted runner, a fixture policy and the scorer. Build a bounded decimal-expression parser. Make closed-mode terminal reward masking explicit. Keep previous observations immutable. Add one provisional trajectory trace.

**Expected outcome.** Run a small fixture from reset through inspection and submit. Print agent-visible messages and show the score separately in the runner.

**Acceptance tests.** Test 0/1/50 rows and a 51-row table, invalid cursor/limit/ID, bounded arithmetic errors, reset after submit, second submit and snapshot immutability. After 99 inspections submit succeeds at step 100. After 100 inspections without submit expect truncation. A malformed submit terminates at −1 internally. Check the closed agent sees 0.

**Study checkpoint.** Trace a get_document call from request to observation. Identify the exact statement that consumes a step.

## Stage 05 — Enforce the process boundary and deadline

**Prerequisites and requirements.** 04. Read R05–R06.

**Implementation.** Put a restricted agent and trusted evaluator in separate processes. Allowlist public response fields. Give the policy only the message channel and its program. Implement a monotonic deadline outside step and cleanup after timeout. Run permission checks from the actual runtime identity.

**Expected outcome.** A real Linux/container integration path which serves a fixture through the same tools, including closed evaluation. Record the process identities and data ownership.

**Acceptance tests.** Using harmless private sentinel files, verify the agent lacks read/write access, public data cannot be modified, and sentinel values never appear in messages, startup output or errors. A sleeping policy that never calls step is truncated. Use a fake clock for the precise deadline and one short wall-clock integration test for process cleanup. Verify the next episode starts clean.

**Study checkpoint.** Inspect the public trace and private result for the same submission. Which process owns the true reward?

## Stage 06 — Generate a clean company, duplicates and allocations

**Prerequisites and requirements.** 02–05. Read R02–R04.

**Implementation.** Generate latent sales, balanced journals, receipts, invoice allocations and documents from local seeded RNGs. Validate clean invariants before mutation. Add the first two independently configurable mutation families. Write provenance and derive proof sets against final records. Implement valid split receipts, repeated amounts and documented refunds.

**Expected outcome.** A generator configurable for zero issues, a duplicate, a missing allocation, a partial allocation or a mixture. The runner can select generated episodes instead of fixtures.

**Acceptance tests.** Verify ledger equality by journal, line totals, intended vs actual allocations, unique references and manifest counts. A full duplicated balanced journal must pass balance checks yet fail reconciliation. A different invoice with the same amount must stay clean. Recalculate one generated discrepancy manually. Re-run seed/config and compare serialized output.

**Study checkpoint.** Take one invoice through issuance, payment and allocation. Show why balanced books can contain an error.

## Stage 07 — Implement FX conversion and reporting periods

**Prerequisites and requirements.** 06. Read R03–R04.

**Implementation.** Extend the clean generator to the specified currencies and timezones. Add independent mutation switches for wrong FX date/rate and misplaced recognition. Keep evidence from adjacent periods accessible. Reject candidate mutations that leave the published rounded amounts unchanged.

**Expected outcome.** All four individual families work end to end. Each can be disabled independently. A clean FX transaction and a valid month boundary case have empty truth.

**Acceptance tests.** At 500 KZT/USD, USD 100 produces KZT 50,000. Posting 49,000 creates a 100,000-minor-unit discrepancy. Check JPY exponent 0, different source/target exponents and exact half rounding. At +05:00 November 1 00:30 is still October in UTC. Test both sides of the exclusive end, missing rates, and an unaffected control.

**Study checkpoint.** Calculate an FX posting on paper and identify which timestamp policy chooses. Why would converting to UTC first change the month in this example?

## Stage 08 — Compose interacting errors and scale generation

**Prerequisites and requirements.** 07. Read R02–R04.

**Implementation.** Implement both interaction scenarios and preserve public proof after all mutations. Generate clean, A-only, B-only and A+B variants for each scenario. Scale to the recommended episode size and validate actual counts. Vary amounts, names, ordering and business patterns without hidden label hints.

**Expected outcome.** Two configurable interacting scenarios and a generator covering small/large, clean/mixed profiles. A trusted independent validation pass checks the final public evidence against truth.

**Acceptance tests.** For duplicated USD 100 at a required rate of 500, post original 50,000 KZT and extra at 49,000 KZT. Under R04 expect duplicate 49,000 and FX difference 1,000 KZT, anchored to distinct canonical targets. For the boundary scenario verify both amounts from real rows. Check 0 and 12 issues, impossibly small inputs, proof lengths ≤10, and evidence discoverability within 100 actions including submit.

**Study checkpoint.** Explain how the two issue amounts can each be correct without their sum equaling a total financial loss.

## Stage 09 — Connect four policies and capture replayable trajectories

**Prerequisites and requirements.** 05–08. Read R05–R07.

**Implementation.** Implement seeded random exploration, public-data reconciliation, a schema-valid mass-accusation policy and trusted oracle. Let reconciliation join explicit references, compute amounts and cite proof. Support a common adapter. Record each action and returned observation at delivery time. Clear policy memory per episode.

**Expected outcome.** Four runnable policies, JSONL trajectories and separate evaluator metrics. Each ordinary policy can run against an unseen seed with no private inputs.

**Acceptance tests.** Run all four on the same clean and faulty fixtures. Correct evidence beats silence on faulty books. Silence beats accusations on clean books. Valid mass accusations accumulate FP. A separate oversized submission tests −1. Check the oracle maximum at its actual inspection count. Inspect a timeout trace and ensure it can be distinguished from submit. Check a baseline case per family and budget on a large episode.

**Study checkpoint.** Replay one baseline finding. Which tool responses are sufficient to prove it? Where does its cost enter the final score?

## Stage 10 — Verify replay, paired transformations and dataset splits

**Prerequisites and requirements.** 08–09. Read R02 and R07.

**Implementation.** Make a bijective ID remapper and record-order permutation. Update every ID reference including nested allocations, public summaries, evidence sets and provenance. Export ten train and ten dev episodes with disjoint seeds and parameter mixes. Keep evaluator material inaccessible to ordinary policies.

**Expected outcome.** Versioned configs and dataset exports, a split manifest, local rehearsal inputs and an automated paired-check report.

**Acceptance tests.** Repeat identical version/seed/config/actions and compare public records, observations, flags and returns. For 20 transformed pairs verify remapped oracle answers and equal scores at equal cost. Change names and row order in clean controls. Check no dangling links, no duplicated split IDs, exact 10+10 counts and coverage of clean, single and interacting cases.

**Study checkpoint.** Explain why identical actions should replay on an identical episode but a reasonable explorer may take a different path on a reordered episode.

## Stage 11 — Run the offline evaluation and measure failures

**Prerequisites and requirements.** 05–10. Read R01, R06–R07.

**Implementation.** Build python -m audit_env.verify as the single verification entry point. Run local contract, data, reward and replay suites. Benchmark each of the four policies on the same 20 rehearsal episodes, with five clean and five interacting. Keep paired tests separate. Record versions, hardware and split, distinguish local results from the jury's hidden evaluation.

**Expected outcome.** Machine-readable results and a short human report with P/R/F1, return, inspections, total actions and elapsed time. Include per-episode detail, arithmetic means, maximum memory/time and actual failure analysis.

**Acceptance tests.** Check 80 policy-episode results plus 20 pairs. Reconcile summary metrics against individual rows. Exercise the upper size profile, timeouts and no-network startup. Inject a deliberately incorrect expected result in a throwaway test input and verify the command returns nonzero. Restore the original fixture. Show a real limitation even if all required tests pass.

**Study checkpoint.** Pick one low-return episode and explain whether the agent missed an issue, lacked evidence or ran out of steps. Support the explanation with its trace.

## Stage 12 — Package, demonstrate and rehearse handoff

**Prerequisites and requirements.** 11. Read R01 and R07.

**Implementation.** Freeze dependency versions and image digest. Prepare README, license, design note, open schemas and scoring code, train/dev data, four adapters, test suite, trajectories and a scripted demo. Document image preparation and one offline verification command. Ensure release artifacts survive ignored output directories.

**Expected outcome.** A reviewable release candidate and an inventory mapping each organizer deliverable to its actual path. Demo one supported finding, a correct clean response and one failed accusation using the same evaluator.

**Acceptance tests.** Use a fresh checkout and prepared image without network, GPU, credentials or host-only paths. Run the README command, confirm nonzero failure behavior from stage 11, inspect delivered files and report both archive and image sizes. Compare the evidence with the five rubric categories. Record any unverified limitations.

**Study checkpoint.** Walk through one episode in three minutes: source event, mutation, visible evidence, submit, matcher and score. Explain exactly what the oracle demonstrates. Present the release to the owner for submission.

## First prompt

```text
Execute stage 01 from the ROADMAP. Inspect my current checkout first.
Show the commands that worked and finish with the stage's study checkpoint.
```

In Windows cmd, run project commands from the repository root after `.venv\\Scripts\\activate.bat`. In Git Bash use `source .venv/Scripts/activate`. The proposed verification CLI becomes available during stage 11. The organizer deadline is November 22, 2026 at 23:59 Astana time. Prioritize the twelve stages and reserve time for a clean-checkout rehearsal before submission.
