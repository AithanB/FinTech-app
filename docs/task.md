# FinTech: RL Environments for Fine-Tuning Financial Audit Models

> Build a reproducible simulator for an AI auditor: synthetic company documents, investigation tools, hidden financial errors, and a reward function.

**Format:** Online, teams of 2–4 people

**Dates:** November 19–22, 2026

**Finalists:** Top 7 FinTech teams

---

## 01 // Challenge Overview

The agent examines records, selects actions, and submits findings with evidence. The environment evaluates the outcome. You need to build an environment for potential model fine-tuning—not a payment app, a chatbot, or a single audit report.

In RL, a policy learns from rewards over repeated interactions. The environment provides these interactions, but does not update model weights itself. An RL interface, recorded trajectories, and quality evaluation are required.

Weight training is optional, earns no points on its own, and must not depend on paid APIs or GPUs. You cannot claim model improvement without a controlled comparison on held-out data.

## 02 // What Makes It Hard

* **Four error types.** At least four independently configurable types: duplicate invoices; missed or partial payment allocation; incorrect date or conversion rate; accounting period cutoff error.
* **Interacting errors.** Two scenarios, for example a partial payment in another currency right on a period boundary.
* **Clean cases.** Clean companies and plausible, valid distractors: split payments, refunds, legitimate recurring amounts.

First create a consistent hidden company history, then documents and errors with a recorded causal change. The ground truth must describe a real discrepancy and available evidence, not a random suspicious row. You must not require an unavailable fact. Vary names, IDs, ordering, amounts, currencies, time zones, and error combinations. Complexity should require evidence analysis and defeat simple shortcuts, without making the task unsolvable.

## 03 // Episode & Data Format

An episode is one company and one reporting period. Suggested size: 200–2,000 ledger entries, 20–200 documents, 0–12 errors.

* **manifest.json.** Defines `schema_version`, `episode_id`, `base_currency`, `period_start`/`end`, `timezone`, entry/document counts, and rounding rules.
* **Value formats.** Timestamps in ISO-8601 with offset; money as integer minor units with currency exponent; FX rates as decimal strings. Different currencies cannot be compared without conversion.

**Open records:**

* `ledger.csv`: `row_id`, `timestamp`, `account`, `debit_minor`, `credit_minor`, `currency`, `entity_id`, `invoice_id`, `payment_id`.
* `invoices.jsonl`: `doc_id`, `invoice_id`, `entity_id`, `issued_at`, `due_at`, `currency`, `total_minor`, `line_items`.
* `payments.jsonl`: `doc_id`, `payment_id`, `timestamp`, `currency`, `amount_minor`, `invoice_refs`.
* `fx.csv`: `date`, `source_currency`, `target_currency`, `rate`.
* `policy.json`: FX rate date selection, period boundaries, and rounding.

Missing links must be explicit `null` values, not guessed associations.

**Closed evaluator files.** `truth.json` contains `issue_id`, `type`, `affected_ids`, `expected_amount_minor`, `currency`, and valid evidence sets; `provenance.json` contains the generation history and applied changes. The agent does not see these files or the `seed`. The evaluator runs outside the agent process; records are read-only via a narrow tool interface. Ground truth must not leak through observations, paths, errors, debug info, or reward explanations during a closed run.

## 04 // Observations, Actions, Termination

* **Reset.** `reset(seed, config)` returns `(observation, info)`. First observation: task, manifest, brief policy, and remaining budget.
* **Step.** `step(action)` returns `(observation, reward, terminated, truncated, info)`. This is a Gymnasium-style JSON-compatible contract; inheriting from a Python `Env` is optional.
* **Reproducibility.** Identical `seed`, `config`, version, and actions must reproduce records, transitions, and rewards. `reset` isolates episode state.
* **Actions.** `list_records(table, cursor, limit)`; `get_record(table, id)`; `get_document(doc_id)`; `calculator(expression)`; `submit(findings)`. Page size is at most 50 rows, with stable cursors.
* **Calculator.** Allows only arithmetic and decimal numbers—no code and no files.
* **Errors.** An unknown ID or action returns a bounded error and consumes a step.
* **Observation.** Contains only requested records, result/error, and remaining steps. No free shell, SQL, filesystem, or internet.
* **Termination.** Maximum 100 steps, including submission. `submit` ends the episode with `terminated=true`. Step or time limit yields `truncated=true` and an empty final answer.
* **Intermediate reward.** Zero reward for exploration. Only in open training mode is the terminal reward returned to the policy; during evaluation, reward and diagnostics stay with the evaluator until the end of the run. No correctness hints are given along the way.

## 05 // Findings & Reward

`submit` accepts `findings.json`: `{episode_id, findings:[{type, affected_ids, claimed_amount_minor, currency, evidence_ids, explanation}]}`. `explanation` is a short justification, not a hidden chain of thought.

* **Limits.** At most 30 findings, 10 evidence IDs, and 1,000 characters of explanation per finding.
* **Invalid structure.** Ends the episode with a reward of `-1` and an error in the evaluator log.
* **Matching.** One-to-one with ground truth. A TP requires the right `type`, canonical `affected_ids`, amount within an explicitly stated tolerance, `currency`, and at least one complete valid set of evidence. Unmatched and duplicate findings are FP; missed ground-truth errors are FN. Duplicates earn no points.
* **Evidence.** The generator must provide accessible records sufficient to verify the finding.
* **Open code.** Publish the code for normalization, tolerances, and tie-breaking on ambiguous matches.
* **Metrics.** Precision $P = \text{TP}/(\text{TP}+\text{FP})$, recall $R = \text{TP}/(\text{TP}+\text{FN})$, $\text{F1} = 2\text{TP}/(2\text{TP}+\text{FP}+\text{FN})$. When the denominator is zero, $P$ or $R$ equals `0`. If both ground truth and findings are empty, $\text{F1} = 1$; if ground truth is empty but findings are non-empty, $\text{F1} = 0$.

$$\text{Terminal reward} = \text{clip}(2\cdot\text{F1} - 1 - 0.002\cdot\text{inspection\_steps},\ -1,\ 1)$$

Episode return equals this reward. This is the suggested common function; you may add an experimental one, but you must keep the common one and report it separately. Reward depends on fields and evidence, not persuasive text.

Tests must show:

* A complete, accurate answer with evidence beats silence on erroneous books.
* Silence beats false accusations on clean books.
* Duplicates give no advantage.
* Flagging all rows/types performs poorly.
* Saving steps only slightly differentiates equal answers.

Test guessed IDs, unverified evidence, currencies, resubmission, invalid input, and timeout. Reward does not prove suitability for real-world auditing.

## 06 // Closed Environment Evaluation

Teams submit environments. Therefore, the jury evaluates the correctness of the data and evaluator rather than ranking teams solely by their agent's reward. Open `train`/`dev` configs and seeds are separate from closed seeds, new parameter combinations, and benign transformations. Error types are known in advance; mandatory new tasks cannot be added secretly. Hidden seeds alone are not enough against overfitting.

On every environment, the organizers run the same baseline policies:

* Random explorer with a fixed seed.
* Simple reconciliation algorithm.
* "Flag everything" attack.
* An evaluator-only Oracle that submits true findings with evidence. The Oracle tests maximum reward, not agent capability.

All four run on the same 20 hidden episodes, including five clean episodes and five with interacting errors. Another 20 paired checks change ordering and IDs. Versions, seeds, policies, and hardware are identical; ground truth and evidence are checked independently against the records.

## 07 // Minimum Requirements

* Company generator: at least four error types, two interacting error scenarios, clean companies, and distractors.
* Environment with `reset`/`step` contract, actions from Section 04, and a 100-step limit.
* Common matcher and terminal reward from Section 05 with tests for adversarial/attack responses.
* Recorded trajectories without closed ground truth in observations.
* Official evaluation without network access, paid APIs, or GPUs.
* Container instructions and a single verification command.

Optional: weight training and a local model. A scripted policy is sufficient for the mandatory demo.

Suggested standalone limit: Python 3.11, 2 CPU cores, 4 GB RAM, no GPU, 1 GB per solution, 60 seconds per episode, 100 steps.

## 08 // Advice for Participants: Build Step by Step

Do not spend the main timeframe on model training or UI. Move in order:

* First the contract and two error types.
* Then all four types and clean cases.
* Then error combinations, isolation, and attacks.

## 09 // Submission — By November 22, 23:59

November 22, 2026, 23:59 Astana time. The organizers will share the submission form or channel link separately.

What to submit:

* **Source code** — source files with a license and pinned dependencies: generator and environment.
* **README** — container instructions and a single verification command.
* **Matcher and reward** — shared matching and reward code, schemas, and policies.
* **Episodes** — 10 open `train` episodes and 10 `dev` episodes.
* **Tests** — tests for environment, matching, and reward.
* **Baseline policies** — four baseline policy adapters.
* **Trajectories** — `trajectories.jsonl` with `episode_id`, `step`, `action`, `observation`, `reward`, `terminated`, `truncated`. Observations in training trajectories contain no closed ground truth.
* **Design note** — a concise description of how the environment works.
* **Demo** — a demonstration of the environment running; a scripted policy is enough, a local model is optional.

## 10 // Evaluation Criteria — 100 Points

The jury evaluates the correctness of the environment and evaluator, not the team's agent reward. Full check definitions are published before launch; only seeds and values are hidden.

* **Contract and isolation — 25:** $25 \times \text{passed}/20$ fixed checks of `reset`/`step`, schemas, limits, termination, invalid input, and no leaks.
* **Data and ground truth — 25:** $25 \times \text{valid}/20$ closed episodes: accounting balances before injecting an error, stated discrepancy after, and independent sufficiency of evidence. Contradictory or unsolvable data does not count as complexity.
* **Reward reliability — 25:** $25 \times \text{passed}/20$ checks of matching, clean cases, FPs, duplicates, cost, and adversarial answers.
* **Reproducibility and generalization — 15:** $15 \times \text{passed}/20$ paired checks: replaying seed/actions is exact, and shuffling/renaming IDs preserves the Oracle's answer and reward accounting for the new IDs.
* **Engineering and explanation — 10:** five criteria scored `0/1/2`: single-command run, config versions, trajectory logs, measured failure breakdown, honest limitations.

Leaking closed data, writing to the evaluator, real financial data, or a broken core blocks scoring until fixed within a single published window for everyone. Report `P`, `R`, `F1`, return, steps, and agent runtime separately as diagnostics. High Oracle reward alone does not earn points for complexity.

## 11 // Selection & Finals

Following the online stage, the jury will select the top 7 FinTech teams. They will advance to the offline finals in Astana, preliminarily scheduled for November 28–29, 2026. Exact dates, venue, and final tasks will be confirmed separately by the organizers.

## 12 // Important

* All companies, people, accounts, bank records, and money are fictional.
* No bank cards, real payments, personal data, or financial account registrations.
* Official evaluation runs without network access.
* This is a software task, not a professional audit opinion.
* A flashy UI and unproven training improvements earn no points.