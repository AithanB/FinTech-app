# Trusted evaluator material

`stage10/{train,dev}/{episode_id}/` contains truth, provenance, clean records and
latent history for the public train/dev exports. `stage10/paired-checks.json` is
the deterministic twenty-pair rehearsal report. Source seeds/configs are in
`configs/stage10-splits.json`. This is local development material, not jury data.

Load it only in the trusted evaluator via `audit_env.datasets.load_episode` or
the baseline CLI's paired `--episode PUBLIC_PATH --evaluator PRIVATE_PATH` flags.
Ordinary policy programs and observations receive no evaluator files, config
values, seeds or correctness diagnostics. The Linux image denies group/other
access to this tree, and the data-free policy jail mounts none of it.

Reproduce or check with `python -m audit_env.datasets`; stale content is rejected
instead of overwritten. See `docs/stage-10.md` for actual permission probes,
paired-score checks and the distinction between semantic replay and wall time.

`stage11/` retains the complete local offline rehearsal: `results.json` with
eighty policy/episode rows and arithmetic means, `report.md`, separate twenty-pair
checks, pytest logs, a real timeout capture, an intentionally wrong expectation
and all eighty delivery trajectories with separate private results. These files
are evaluator evidence, not policy inputs. They survive the ignored `runs/`
directory. The normal `python -m audit_env.verify` command writes a fresh output
directory and refuses to overwrite previous evidence. See `docs/stage-11.md`.
