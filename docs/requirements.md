# Financial audit simulator — requirements v1.0

Implementation contract for a solo developer. Status: specified, pending implementation and verification. **Brief** denotes organizer requirements. **Decision** denotes project choices accepted for implementation and open to owner review. Published organizer clarifications take precedence. Update the schema/config version and affected fixtures when observable semantics change.

## R01 · Product and execution

**Brief.** Deliver a reproducible RL environment, synthetic companies, investigation tools, hidden errors, an external evaluator, recorded trajectories and quality measurements. A scripted demo suffices. Training is optional and earns no points by itself. Claims that training improves a model require a controlled held-out comparison. Synthetic audit reward does not establish professional audit fitness. Generate all identities and transactions locally. Exclude real financial records, personal data, cards, payments and financial account registration.

**Decision.** Python 3.11, Pydantic 2, pytest, decimal, zoneinfo with tzdata, Git and Docker. Pin exact resolved dependencies and the tested image digest at release. Target the suggested 2 CPU cores, 4 GB RAM, 1 GB solution, 60 seconds/episode and CPU-only offline execution. No external service participates in verification. Record compressed submission and image sizes separately.

## R02 · Episodes, generation and reproducibility

**Brief.** One company and one reporting period per episode. Generate a consistent latent history, derive documents and books, validate them, then introduce causal changes. Preserve the before/after history. Vary names, IDs, order, amounts, currencies, timezones and combinations. Truth must be independently provable from public evidence.

**Decision.** Use calendar months. Default public fixture profile targets 400 ledger rows, 80 invoice/payment documents and 2 issues. Generate within the suggested 200–2,000 rows, 20–200 documents and 0–12 issues for delivered episodes. Tiny unit fixtures are separate. Report actual post-mutation counts. Four independent nonnegative integer counts select the four families. Interaction pairs consume their constituent counts. Reject impossible combinations before emitting an episode. Use local seeded RNG streams, deterministic serialization and opaque IDs. Identical version, seed, config and actions reproduce records, observations, transitions and reward apart from external wall-clock interruption; test deadlines with an injected clock.

## R03 · Records and accounting

| Visibility/file | Required fields or contents |
| --- | --- |
| Public manifest.json | schema_version, episode_id, base_currency, period_start, period_end, timezone, record_count, document_count, currency_exponents, rounding |
| Public ledger.csv | row_id, timestamp, account, debit_minor, credit_minor, currency, entity_id, invoice_id, payment_id |
| Public invoices.jsonl | doc_id, invoice_id, entity_id, issued_at, due_at, currency, total_minor, line_items |
| Public payments.jsonl | doc_id, payment_id, timestamp, currency, amount_minor, invoice_refs |
| Public fx.csv | date, source_currency, target_currency, rate |
| Public policy.json | FX date and direction, period boundaries, recognition and rounding rules |
| Private truth.json | issue_id, type, affected_ids, expected_amount_minor, currency, evidence_sets (list of alternative complete ID lists) |
| Private provenance.json | Latent event IDs, clean values, changed objects and fields, operation and final observed values |

**Decision.** All files UTF-8. CSV null is the reserved token `null`, emitted as JSON null by tools. ISO-8601 timestamps require offsets. Base KZT, supported document currencies KZT/USD/EUR (exponent 2) and JPY (0). Run timezone defaults to Asia/Almaty and varies across generated cases. Membership uses local time in [period_start, period_end). Provide linked evidence on both sides of a boundary. Amounts are integers, excluding booleans. The ledger records base-currency amounts. The FX rate is a finite positive decimal string in target major units per source major unit. Use Decimal, convert exponents, round once per posting amount using ROUND_HALF_UP. Supply the applicable local-date rate for each foreign event. Missing required rates invalidate generation. Same-currency conversion uses identity.

**Decision.** Model sales on credit, cash receipts, unapplied receipts and documented refunds. Each journal balances in base currency. Invoice lines sum to the invoice total. Explicitly support these public extensions: journal_id on ledger rows, service_at on invoices, directed allocation amounts in payment invoice_refs, and entry_kind on postings. Record cash receipt in full, then transfer the allocated amount from unapplied receipts to receivables. An unapplied balance is independently visible even for a wholly missing application. Currency gains/losses, where needed to close receivables, have their own balanced entries. FX date for invoice recognition is local service date, for a payment it is local payment date. Refunds reference the original payment and have a distinct transaction kind. Enumerate all evidence IDs through tools, including a deterministic FX key built from the date and currency pair.

## R04 · Issues and evidence

**Brief.** Four independently configurable families, two interacting scenarios, clean companies, valid split payments, refunds and recurring amounts. An unusual row alone cannot justify truth.

**Decision.** Findings use positive absolute discrepancies in KZT minor units, exact tolerance 0 after prescribed rounding. Canonical affected objects below are stable even when a posting is missing. Restrict one issue of a given family per canonical target in v1. Evidence can include ledger row IDs, doc_ids and FX keys. Generate at least one complete proof of at most 10 IDs. If a proof requires establishing absence, supply a public per-payment settlement summary with an evidence ID, derived from the final ledger including zero allocations. Include this as a documented payment-tool view and test that it reconciles to the books.

| type | Exact affected_ids | Amount and minimum facts needed for proof |
| --- | --- | --- |
| duplicate_invoice | invoice_id | Sum of extra recognition postings on the revenue side. Show invoice and revenue legs from distinct journals for that invoice. Never count the balancing legs twice. |
| payment_allocation | payment_id and invoice_id | Base equivalent of intended application less actual application, in absolute value. Show payment directive, actual application or settlement summary, and applicable FX record if foreign. Support missing and partial application. |
| fx_conversion | journal_id | Absolute difference between required conversion and posted amount on one designated leg. Show source document, policy, required FX row and posted amount. Wrong-date and wrong-rate variants must change the rounded amount. |
| period_cutoff | journal_id | Absolute posted amount on one designated recognition/application leg placed on the wrong side of the boundary. Show source event and dated posting, applying the published zone and policy. |

The manifest and policy are public common context. If a changed posting uses a foreign rate, use the contract-specific event date. For an allocation posted late, derive its intended monetary conversion from payment date. A split payment correctly applied is clean even if the invoice remains partly unpaid.

**Interaction A.** A foreign partial payment is underapplied and the actual application journal is posted in the next period. Score the missing allocation and the amount of the mistimed posting independently. **Interaction B.** An invoice has two recognition journals. Exactly one uses the wrong FX rate. To avoid order-dependent attribution, the duplicate amount is the extra journal's observed revenue amount; identify the extra by a public posting sequence for that invoice, independent of row order and opaque IDs. Postings of any kind carry normal business sequence data. FX error targets the misconverted journal. Issue amounts are per finding and need not sum to a company-wide loss.

## R05 · Environment and tools

**Brief.** JSON-compatible reset(seed, config) returns (observation, info). Initial observation includes task, manifest, policy summary and remaining steps. Reset clears previous state. step(action) returns (observation, reward, terminated, truncated, info). Expose only requested data/result or bounded error plus remaining steps. No shell, SQL, filesystem or internet tool. Public records are read-only.

**Decision.** Actions use an object with type and named arguments at the top level. Results use result or error plus remaining_steps. Public info defaults to an empty object. Use fresh snapshots. The trusted runner supplies seed and config. An invalid reset configuration fails before an episode starts.

| Action | Behavior |
| --- | --- |
| list_records(table,cursor,limit) | Tables ledger, invoices, payments, fx. Null cursor starts a table. Limit integer 1–50 inclusive. Stable order within an episode. Return rows and next_cursor, null at the end. Reject wrong table/cursor/limit with a bounded error. |
| get_record(table,id) | Exact ID lookup in a permitted table. List responses expose usable lookup IDs. |
| get_document(doc_id) | Return invoice or payment with public fields and applicable settlement view. |
| calculator(expression) | Decimal literals, parentheses, unary signs and + − * /. ASCII operators on the wire. Decimal precision 34. Max 256 characters, nesting depth 16. Reject unsupported tokens, overflow and division by zero. |
| submit(findings) | Wire form uses type=submit and findings containing the submission envelope with episode_id and findings array. Validate once and finish. |

Every attempted action in an active episode consumes one step. Unknown actions and IDs yield short error codes. At most 100 actions including submit. An on-time submit at action 100 terminates normally. A 100th inspection truncates with an empty answer. Runner starts a monotonic 60-second deadline upon delivery of initial observation, rejects a submission received at or beyond it and enforces the deadline even for a stalled policy. On timeout return an empty final answer and truncated=true. Valid or malformed submit gives terminated=true. After completion reject further calls with EPISODE_CLOSED without changing score, budget or journal.

## R06 · Access, submission and scoring

**Brief.** Keep seed, truth and provenance inaccessible to ordinary policies. Run evaluator outside agent process. Prevent leaks in observations, errors, paths, logs, debug info and reward explanations. All inspection rewards are 0. Open training returns terminal reward. In closed evaluation the true reward and diagnostics stay private until the run ends.

**Decision.** Use a separate restricted Linux agent process with its own unprivileged identity and only a JSON message channel to the trusted runner. Enforce private directory permissions, no network, no private mounts or inherited handles, and no evaluator write access. Privileged oracle runs on the trusted side. Closed wire reward is numeric 0 even at termination. Privately compute the true reward.

Submission envelope is {episode_id, findings:[{type, affected_ids, claimed_amount_minor, currency, evidence_ids, explanation}]}. Limit 30 findings, 10 evidence IDs and 1,000 Unicode code points per explanation. Require strings for IDs and explanation and an integer amount. Reject wrong envelope ID, missing/extra fields and invalid types/size with terminal −1 and private error logging. Structurally valid claims about unknown objects, unsupported facts or wrong currency do not match. Explanation is short evidence commentary and earns no score.

Normalize affected IDs as case-sensitive unordered sets, require exact equality. Compare evidence as sets after checking every supplied ID exists. Require at least one complete truth proof as a subset. No prerequisite that evidence was separately opened. Keep each submitted finding as a separate prediction. Build the bipartite graph of compatible pairs. Choose maximum cardinality, breaking ties by lexicographically smallest sorted list of (issue_id, submission_index). Publish the implementation, tolerance and examples. Unmatched predictions including duplicates count FP. Unmatched truths count FN.

P=TP/(TP+FP), R=TP/(TP+FN), F1=2TP/(2TP+FP+FN). Undefined P or R equals 0. Both lists empty gives F1=1. Empty truth with predictions gives F1=0. Score = clip(2×F1−1−0.002×inspection_steps, −1, 1). Count every pre-submit action, including errors. A final inspection causing truncation counts. A timeout adds no action. Return equals terminal score. Score truncation as empty findings; malformed submit always gets −1. Keep the common score separately labeled if an experimental score is added.

## R07 · Measurement, tests and submission

Save trajectories.jsonl with episode_id, step, action, observation, reward, terminated, truncated. Steps start at 1. Store initial observation in run metadata. For timeout between actions, emit a terminal log event with action=null, next event index, no increase to the action counter. Save policy-visible reward in public traces and true metrics separately. Report per-policy P, R, F1, return, steps and wall time, per episode and as arithmetic means. Record actual failures, reproduction inputs, fixes and remaining limitations.

Run four adapters on the same episodes: fixed-seed random explorer, rule-based reconciliation, valid flag-everything up to the cap, evaluator-only oracle with complete evidence. Judges use 20 hidden episodes including five clean and five interacting, plus 20 paired ID/order transformations. Freeze versions, seeds, policies, hardware. Public train/dev and local rehearsal use disjoint config/seed combinations. Include held-out parameter combinations and benign transformations of known types. Preserve remapped oracle answer and reward. Oracle score alone earns no complexity credit. Independently verify accounting and evidence from records.

Delivery includes licensed sources (project choice MIT), pinned dependencies, generator, environment, schemas, policies, published matcher and reward, tests, four adapters, exactly 10 open train and 10 dev episodes, trajectories, design note, measured failure analysis, scripted demo and README with container instructions and one verification command. Project command inside the prepared offline image: python -m audit_env.verify. Return 0 only when required checks pass. Verify the actual delivery path on a clean machine. Report any host preparation separately.

| Jury category | Published weighting |
| --- | --- |
| Contract and isolation | 25 × passed / 20 fixed checks |
| Data and truth | 25 × valid / 20 hidden episodes |
| Reward reliability | 25 × passed / 20 checks |
| Reproducibility and generalization | 15 × passed / 20 pairs |
| Engineering and explanation | 5 criteria × 0/1/2 points: single command, config versions, trajectories, measured failures, honest limits |

Blockers in the brief are private-data leakage, evaluator write access, real financial data and broken core functionality. The organizers specify the common correction window and official checks. Local tests are rehearsals. Online stage November 19–22, 2026, teams of 2–4. Solo here describes the implementation workflow. Submit by November 22 at 23:59 Astana time via the organizer-announced channel. Seven FinTech teams advance. The Astana final is provisionally November 28–29, subject to confirmation.

References supplied by organizers: [Gymnasium Env](https://gymnasium.farama.org/api/env/) and [specification gaming](https://deepmind.google/blog/specification-gaming-the-flip-side-of-ai-ingenuity/).
