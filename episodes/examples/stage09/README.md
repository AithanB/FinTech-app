# Stage 09 delivery captures

These ten JSONL files are actual local acceptance captures from the prepared
Linux image, running without network access. They are examples, separate from
the train/dev splits planned in Stage 10.

- `company-a/{random,reconciliation,mass_accusation,oracle}/trajectories.jsonl`:
  the same hand-authored clean fixture for all four policies.
- `company-b/{random,reconciliation,mass_accusation,oracle}/trajectories.jsonl`:
  the same hand-authored faulty fixture for all four policies.
- `large-mixed/reconciliation/trajectories.jsonl`: company seed 7091 with
  `configs/stage08-large-mixed.json`; 12 supported findings in 22 actions.
- `timeout/trajectories.jsonl`: sleeping test policy, 0.2-second deadline,
  zero actions, terminal timeout event explicitly marked undelivered.

Random policy seed is 0. Policy version is stage09-v1. Generation seeds and
configs are trusted reproduction inputs; they are not sent to ordinary policies.
The oracle alone uses private truth in the evaluator. Its submitted actions are
included, while its observations follow the same public schema as other runs.

Every trace starts with public reset metadata and then records action/response
snapshots. All closed rewards are zero. Only `delivered=true` rows represent
completed response delivery. The null-action timeout event is a supervisor event,
not a submission or additional action. Evaluator metrics and matching diagnostics
remain under ignored `runs/stage-09/isolated/` and are excluded from this export.

Reproduce with `python -m audit_env.baselines` in the prepared image; commands
and measured results are in `docs/stage-09.md`. The timeout comes from
`tests/test_stage09.py::test_linux_timeout_capture_and_fresh_adapter`.
