# Public episode exports

`train/` and `dev/` each contain exactly ten opaque episode directories with
only the six public record files. `split-manifest.json` records membership,
source seeds, configuration indices, actual sizes and public semantic hashes.
Source configs and the disjoint twenty rehearsal inputs are frozen in
`configs/stage10-splits.json`. The rehearsal set is not exported into train/dev.

Evaluator material is separate under `evaluator/stage10/`. The trusted runner
loads both sides; ordinary policies receive records only through tools inside
the isolated process. They cannot access the source plan, manifest or disk data.
The example captures under `examples/` are distinct from these dataset splits.

Reproduce with `python -m audit_env.datasets`. Verify existing exports and twenty
paired transformations with:

```sh
python -m audit_env.datasets --check --paired-report evaluator/stage10/paired-checks.json
```

See `docs/stage-10.md` for the complete data/isolation/replay checks and limits.
