# Stage 11 local offline rehearsal

Status: passed. These are local rehearsal results, not jury hidden evaluation.

Version: stage11-v1. Tests: 284 passed; 1 platform guard skipped.
80 policy-episode runs; 20 separate transformed pairs; five clean and five interacting rehearsal inputs.

## Policy arithmetic means

Undefined precision/recall are zero, including clean oracle answers. Clean empty-answer F1 is one.

- random: P 0.000000, R 0.000000, F1 0.000000, return -1.000000; 20.00 inspections, 21.00 actions, 1.0662 seconds. Totals TP/FP/FN: 0/66/30.
- reconciliation: P 0.750000, R 0.750000, F1 1.000000, return 0.968900; 15.55 inspections, 16.55 actions, 1.0552 seconds. Totals TP/FP/FN: 30/0/0.
- mass_accusation: P 0.000000, R 0.000000, F1 0.000000, return -1.000000; 2.00 inspections, 3.00 actions, 1.0456 seconds. Totals TP/FP/FN: 0/600/30.
- oracle: P 0.750000, R 0.750000, F1 1.000000, return 1.000000; 0.00 inspections, 1.00 actions, 0.6255 seconds. Totals TP/FP/FN: 30/0/0.

## Resources and limits

Maximum episode wall time: 1.1878 seconds.
Maximum episode RSS upper bound: 82.00 MiB.
Memory is the sum of fresh-worker evaluator and child policy kernel RSS high-water marks; these peaks need not occur simultaneously. It is a conservative bound, not a simultaneous process-tree measurement. The child mark includes jail setup before exec. Wall time includes worker startup, generation, jail preparation, policy and trace writes.
CPU model: AMD Ryzen 5 5500U with Radeon Graphics. Cgroup CPU quota: 200000 100000; memory limit: 4294967296 bytes.
Actual upper rehearsal case: 604 ledger rows / 200 documents. This generator does not reach the suggested 2,000-row upper envelope.
The four policies are fixed scripts; this benchmark does not demonstrate learned-model improvement or general accounting ability.

## Trace-supported failures

- random on ep-018ca7949630bc2cd9369c11: return -1.0, TP/FP/FN 0/0/1, 21 actions, submit at step 21. Submitted an empty answer within budget, so every truth issue was missed. No accusations were made; the low return comes from false negatives, rather than exhausted steps. Trace: [trajectories/ep-018ca7949630bc2cd9369c11/random/trajectories.jsonl](trajectories/ep-018ca7949630bc2cd9369c11/random/trajectories.jsonl).
- mass_accusation on ep-018ca7949630bc2cd9369c11: return -1.0, TP/FP/FN 0/30/1, 3 actions, submit at step 3. Submitted within budget; no supported finding matched. The policy guessed document-only accusations without reconciling accounting relationships. It missed the truth issues and supplied insufficient proof, rather than exhausting steps. Trace: [trajectories/ep-018ca7949630bc2cd9369c11/mass_accusation/trajectories.jsonl](trajectories/ep-018ca7949630bc2cd9369c11/mass_accusation/trajectories.jsonl).

The timeout probe is separate from benchmark rows: a nonresponsive jailed policy was reaped, with a null-action timeout event and zero consumed actions.

Incorrect-expectation control: CLI exit 1; original expectation unchanged: True.

Full per-episode metrics, versions, hardware and source/config digests are in results.json. Paired checks are in paired-checks.json. Delivered closed rewards stay zero in traces; true scores stay in evaluator files.
