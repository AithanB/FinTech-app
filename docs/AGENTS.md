# AGENTS.md — Financial audit RL environment

## Purpose and authority

Build a reproducible simulator in which an auditor investigates a fictional company's records and submits findings with evidence. A separate evaluator grades the findings against hidden ground truth. The deliverable is a working environment, evaluator, baseline policies, trajectories, and evidence that the system behaves correctly. Scripted policies suffice for the demo. Weight training is optional. Any claim that training improved a model requires a controlled comparison on held-out episodes.

These instructions apply throughout this repository. Read the organizer brief (planned location: `docs/task.md`), published corrections, the README, existing schemas and relevant tests before changing a contract. Organizer requirements govern compatibility. The module layout and implementation conventions below are team recommendations.

## Stack and working layout

Use Python 3.11, Pydantic 2 for boundary validation, pytest for tests, and Docker for the offline verification environment. Use standard-library `csv`, `json`, `decimal`, `datetime`, `zoneinfo`, and a local seeded random generator. Keep `tzdata` available on Windows. The official execution path must run on CPU without network access, paid APIs, credentials, or model downloads. All names, documents, accounts, and transactions are synthetic.

| Area | Responsibility |
| --- | --- |
| `audit_env/` | Schemas, event generation, mutations, tools, episode state, matching and scoring. Keep agent-visible response construction separate from private evaluation. |
| `policies/` | Adapters for the organizer policies. The oracle adapter runs on the evaluator side only. |
| `configs/` | Versioned generator settings and public train/dev configurations. |
| `episodes/train/`, `episodes/dev/` | Exported public episode sets. Supply the ordinary agent with records through tools only. |
| `tests/` | Hand-checked cases, contract tests, scoring tests and replay checks. |
| `docs/` | Brief, schema decisions, design notes, measured failures and limitations. |
| `runs/` | Local output. Export required submission trajectories separately if this directory is ignored. |

Respect existing module boundaries. Keep the generator, agent and evaluator independently callable. A trusted runner owns the seed and configuration, starts the environment and policy, enforces time limits, records trajectories and collects evaluator metrics.

## Generation and accounting

One episode covers one company and one reporting period. Suggested scale: 200–2,000 ledger entries, 20–200 documents and 0–12 issues. Generate a coherent hidden event history first. Derive invoices, payments, allocations and balanced ledger postings from it. Check accounting invariants before mutation. Then introduce specific changes and record their causes, affected objects and measurable effects. The final public records must independently support every answer.

| Independently configurable issue family | Evidence needed to distinguish the defect from a valid event |
| --- | --- |
| Duplicate invoice recording | Identify the underlying invoice and repeated recognition. Match the accounting role of each posting. The debit and credit legs of one journal entry are expected. |
| Missing or partial payment allocation | Compare the intended invoice allocation with what the books applied. A customer may legitimately pay only part of an invoice. |
| Incorrect FX date or rate | Establish the applicable date from the accounting policy, look up the directional rate and reproduce the expected rounded amount. |
| Wrong reporting period | Establish the recognition event and its date from accessible documents, then apply the published timezone and period boundary. |

Provide at least two distinct scenarios with interacting errors on related events. For example, misallocate a foreign-currency payment and post its application on the wrong side of the period boundary. Another scenario can duplicate an invoice whose conversion uses the wrong rate. Specify how the amounts and IDs for each finding are derived in combination. Check them against the final records.

Include entirely clean companies and credible distractors such as split payments, refunds and recurring amounts. Vary identifiers, names, row order, amounts, currencies, timezones and error combinations. Never encode issue status in an identifier, ordering convention or filename.

**Hand-check example.** An invoice for 100,000 KZT receives a 70,000 KZT payment explicitly intended for that invoice. Applying the full 70,000 leaves a legitimate 30,000 outstanding. Applying only 50,000 creates a 20,000 allocation discrepancy. If the schema reports the missing allocation, its value is 2,000,000 minor units at exponent 2. Use both variants to evaluate the generator and matcher independently.

## Episode files and value semantics

| File | Required content |
| --- | --- |
| `manifest.json` | `schema_version`, `episode_id`, `base_currency`, `period_start`, `period_end`, timezone, record/document counts and rounding rules. |
| `ledger.csv` | `row_id, timestamp, account, debit_minor, credit_minor, currency, entity_id, invoice_id, payment_id`. |
| `invoices.jsonl` | `doc_id, invoice_id, entity_id, issued_at, due_at, currency, total_minor, line_items`. |
| `payments.jsonl` | `doc_id, payment_id, timestamp, currency, amount_minor, invoice_refs`. |
| `fx.csv` | `date, source_currency, target_currency, rate`. |
| `policy.json` | FX date selection, reporting-period boundaries and rounding policy. |
| Private `truth.json` | For each issue: `issue_id, type, affected_ids, expected_amount_minor, currency` and acceptable complete evidence sets. |
| Private `provenance.json` | Generation history and causal mutations sufficient to reconstruct each declared discrepancy. |

Use one JSON object per JSONL line. Publish the currency exponent mapping. Keep monetary amounts as integers in minor units and FX rates as decimal strings. Parse rates directly with `Decimal`. Convert source minor units to source major units, apply the directional rate, convert to target minor units, then round according to policy. Compare amounts only in a common currency. Use offset-aware ISO-8601 timestamps and apply the policy timezone before assigning periods.

Preserve missing links as explicit nulls. Define a CSV null encoding and decode it consistently. Document how agents can identify evidence in every table, including FX records without a prescribed ID field. If a finding needs a service date, journal grouping or allocation breakdown, expose sufficient facts through a documented schema and the allowed tools. Do not ask the agent to infer those facts from private history.

## Agent interface and isolation

- `reset(seed, config) -> (observation, info)` starts an isolated episode. Return the task, manifest, policy summary and remaining budget. Clear previous cursors, caches, counters, findings and terminal state.
- `step(action) -> (observation, reward, terminated, truncated, info)` implements the JSON-compatible Gymnasium-style contract. Gymnasium inheritance is optional.
- Expose `list_records(table, cursor, limit)` with stable cursors and at most 50 rows, `get_record(table, id)`, `get_document(doc_id)`, `calculator(expression)`, and `submit(findings)`. Make valid document and evidence references discoverable.
- Return only the requested data or bounded result/error and the remaining steps. An unknown ID or action consumes a step. Limit the calculator to decimal arithmetic. Implement a restricted parser with bounded inputs and controlled arithmetic errors.
- Count at most 100 actions including submission. Accept a valid submit as the 100th action if 99 have been used and time remains. Submit ends the episode with `terminated=true`. Exhausting time or steps without submission gives `truncated=true` and an empty final answer. Reject further actions after completion.
- Exploration rewards are zero. In open training mode, return the terminal reward to the policy. In closed runs, retain reward and diagnostics at the evaluator until the run ends. Document the closed-mode placeholder used in the agent transport.
- Run evaluation outside the ordinary agent process. Restrict its file permissions or container mounts so the policy cannot read private files, inspect the evaluator state or modify inputs or scoring. Supply public records through read-only tools. Do not expose shell, SQL, arbitrary filesystem access or internet tools. Check observations, info, exception text, paths, logs and environment variables for leaks. A separate process with shared readable private files fails this requirement.

## Findings, matcher and reward

Validate the entire submission envelope before matching:

```json
{"episode_id":"example","findings":[]}
```

Each finding carries `type, affected_ids, claimed_amount_minor, currency, evidence_ids, explanation`. Allow at most 30 findings, 10 evidence IDs per finding and 1,000 characters per explanation. Use strict validation appropriate to the wire format. Malformed submission ends the episode at −1 and logs the reason privately. A well-formed but incorrect claim goes through matching.

Publish canonical ID rules, amount definitions and tolerances by issue type, evidence-set rules and deterministic tie-breaking. A TP requires the right type, exact canonical affected objects, matching currency, amount within tolerance, and at least one complete acceptable evidence set. Prose supplies a short justification and earns no points by itself. Match predictions to truth one-to-one. Prefer maximum-cardinality matching with stable tie-breaking if several candidates qualify. Every unmatched prediction, including a duplicate, is an FP. Every unmatched truth issue is an FN.

```text
P      = TP / (TP + FP)
R      = TP / (TP + FN)
F1     = 2*TP / (2*TP + FP + FN)
return = clip(2*F1 - 1 - 0.002*inspection_steps, -1, 1)
```

Use zero for undefined P or R. When both sets are empty F1 is 1. When truth is empty and predictions exist F1 is 0. The episode return equals the terminal reward. Specify inspection-step counting separately from the 100-action budget. A reasonable default is to count pre-submit actions, including invalid inspection attempts. Verify this against organizer checks. Preserve the common reward and report any experimental reward separately.

## Testing and evaluation

Use hand-calculated expected answers. Sharing one erroneous calculation between the generator and its test can give a passing result. For changed behavior, cover the corresponding cases below.

- **Lifecycle and isolation.** Check reset, paging, unknown actions and IDs, malformed input, the last allowed action, timeout, repeated submit and attempts to read hidden state. Verify no truth or seed appears in agent-visible channels.
- **Accounting and evidence.** Check pre-mutation debit/credit balance in the applicable currency representation, document totals and allocations. Reconstruct the post-mutation discrepancy from accessible evidence. Cover all four families, both interaction scenarios and clean distractors.
- **Reward.** Correct supported findings beat silence on faulty books. Silence beats false accusations on clean books. Repeated or indiscriminate claims give no advantage. Check guessed IDs, incomplete or unrelated evidence, amount tolerances, currency mismatches and ambiguous matches. Equal answers give the documented small difference in step cost, subject to clipping.
- **Reproducibility.** Identical version, seed, config and actions reproduce records, observations, transitions and rewards. Use deterministic ordering and a local RNG. Keep wall-clock measurements out of semantic equality checks. In a paired test, permute records and consistently rename IDs and all references. The remapped oracle findings and reward must agree.
- **Baselines.** Supply adapters for a seeded random explorer, simple reconciliation algorithm, flag-everything policy and evaluator-only oracle. Run comparable policies under the same resources. Oracle establishes achievable scoring with correct evidence. Track P, R, F1, return, steps and elapsed time per policy.
- **Closed protocol.** The organizers use the same 20 hidden episodes for all four policies, including five clean episodes and five containing interacting issues, plus 20 paired transformation checks. Separate public train/dev seeds and configurations from hidden evaluation. Exercise fresh parameter combinations of known types. Keep hidden cases out of development decisions.

Log `episode_id, step, action, observation, reward, terminated, truncated` in `trajectories.jsonl`. Capture what the policy actually received. Keep evaluator-only metrics in a separate channel in closed runs.

## Development and verification

Build a complete episode path early: generate a small company, inspect records, submit findings, match and score, then inspect the trajectory. Implement the contract and two issue families first, then all four plus clean cases, then interactions, isolation and adversarial answer tests. Review schema changes across generator, tools, policies, matcher, tests and docs in the same change.

Use the checked-in README commands when available. For the proposed Windows layout, run from the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
```

For the proposed container setup:

```sh
docker build -t audit-rl-env:dev .
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:dev python -m pytest
```

Keep dependency versions pinned and align the README with the actual entry point. Provide one documented verification command covering the completed system. An import check alone only verifies installation. Target the suggested limits of 2 CPU cores, 4 GB RAM, 1 GB solution size and 60 seconds per episode. Distinguish an offline run of a prepared image from an offline build. Report the checks actually executed, observed failures, assumptions and any unverified requirements.

## Submission checklist

- Licensed sources, pinned dependencies, generator, environment, public schemas, accounting policies, matcher and common reward.
- Container instructions and one verification command, tested from a clean checkout.
- Ten public train episodes and ten public dev episodes, baseline adapters, environment/matcher/reward tests and recorded trajectories.
- A short design note covering versioning, isolation, measured failure cases and limitations. Include a working scripted demo.
- Review in rubric order: contract/isolation 25 points, data/truth 25, reward reliability 25, reproducibility/generalization 15, engineering/explanation 10. Hidden-data leaks, write access to the evaluator, real financial data or a broken core can block assessment.
- Online submission deadline in the supplied brief: **22 November 2026, 23:59 Astana time**. Follow the organizers' announced submission channel.
