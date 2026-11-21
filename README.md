# Financial audit RL environment

## Jury adapter (published checks, 20 November 2026)

Working directory inside the container: `/app`. The trusted jury process imports
`judge_adapter.py`: `generate_episode(seed, config, output_dir)`, `make_env()` and
`score_episode(episode_dir, findings, inspection_steps)`. Full published definitions
are preserved in `docs/fintech-checks.md`. Integration and measured checks are in
`docs/judge-adapter.md`.

`generate_episode` accepts the existing generator fields (`GeneratorConfig`),
creates the six public files directly in `output_dir`, and writes truth,
provenance, history and clean data in its protected `private/` subdirectory.
Existing output directories are rejected. `reset(seed, config)` accepts
`{"mode":"closed", "episode_dir":"...", "team_config":{...}}`; it loads exactly
the supplied public files and `private/truth.json` (or root `truth.json` supplied
by the jury). It does not regenerate or reorder that episode. Without
`episode_dir`, seed and `team_config` select generation. `mode="train"` exposes
the terminal reward; closed mode always transports zero.

Actions use `{"name":"list_records", "args":{"table":"ledger",
"cursor":null,"limit":50}}`. Other names/arguments are `get_record(table,id)`,
`get_document(doc_id)`, `calculator(expression)`, and
`submit(findings={episode_id,findings:[...]})`. Tables are `ledger`, `invoices`,
`payments`, `fx`. Every subsequent observation has `result`, `error` and
`remaining_steps`; errors are null or `{code,message}`. List results are
`{records:[record,...],next_cursor}`; get_record returns the raw record.
Ledger lookup is row_id, invoice/payment lookup is invoice_id/payment_id, FX
lookup is `fx:date:source:target`. Payment documents return `{payment,settlement}`;
invoice documents return the invoice. Calculator results are decimal strings.
Submit only acknowledges structural acceptance, without correctness feedback.

The four issue labels remain `duplicate_invoice`, `payment_allocation`,
`fx_conversion`, `period_cutoff`; canonical objects and exact amount tolerance
zero are documented in `docs/requirements.md` R04 and `docs/schemas.md`.
Unknown string labels are valid unmatched predictions. Invalid submissions
produce return -1 and null private metrics at `score_episode`, with a private log.

`make_env` belongs only in the trusted process. To run an unchanged jury JSONL
policy in the actual Linux jail, call `judge_adapter.run_isolated_policy(program,
seed=..., config=...)`; incoming policy messages use name/args and outgoing
messages carry observation/reward/terminated/truncated/info. No episode path,
seed, configuration, evaluator code or truth is copied into the jail. Its
external 60-second deadline starts before reset, including jail setup and policy
time, and stops a policy that sends nothing. The direct trusted facade checks
the same reset-start deadline on each step; an external supervisor must stop a
nonresponsive policy.

`python -m audit_env.verify --output /tmp/jury-verification` in a freshly built
offline container includes the published D01-D20 and P01-P20 matrix (5 order,
5 ID, 10 combined transformations), tests and the existing 80-run benchmark.
Portable matrix-only command: `python -m audit_env.judge_checks --output
runs/jury-matrix.json`. These are local checks, not jury certification.

The jury release is `audit-rl-env-jury-source.zip` plus
`audit-rl-env-jury.image.tar.gz`, with `jury-SHA256SUMS` and
`jury-source-status.json` in `release/artifacts/`. The new image passed 320 Linux
tests (one Windows-only guard skipped), the 80-run benchmark, both paired
matrices and the three-case demo. Complete evidence is retained under
`evaluator/jury-2026-11-20/verification/`; image identity is recorded in
`release/jury-image-lock.json`. After extracting the source ZIP beside the image:

```powershell
docker load --input ../audit-rl-env-jury.image.tar.gz
$image = (Get-Content release/jury-image-lock.json -Raw | ConvertFrom-Json).image_id
docker run --name audit-jury-final --network none --cpus 2 --memory 4g $image python -m audit_env.verify --output /tmp/jury-verification
docker cp audit-jury-final:/tmp/jury-verification ./verification-results
```

Use an unused container name for another run. The rc1 image and archives below
are historical and predate this adapter. The current source and verified image
have the same runtime code; ZIP text is canonicalized to LF. A full new
clean-checkout rehearsal on another machine has not been performed.

The historical release candidate **rc1** was prepared for handoff review. Read
`release/INVENTORY.md` for deliverables, `docs/design.md` for architecture and
limits, and `docs/demo.md` for the three-minute walkthrough. The candidate has
two delivery files: `audit-rl-env-rc1-source.zip` and
`audit-rl-env-rc1.image.tar.gz`, with SHA-256 checksums in `SHA256SUMS`.
All company and financial records are synthetic. Project source uses the MIT
license; dependency notices and exact installed versions accompany the release.

## Release verification from a fresh checkout

Place the two delivery files in one directory. Extract the source ZIP there;
it creates `audit-rl-env/`. Open PowerShell in that extracted project root.
Docker with its Linux engine is the only host preparation needed for the
prepared-image path. No Python installation, credentials, GPU or package
downloads are needed at verification time.

Load the supplied image locally and select its immutable identity:

```powershell
docker load --input ../audit-rl-env-rc1.image.tar.gz
$image = (Get-Content release/image-lock.json -Raw | ConvertFrom-Json).image_id
docker image inspect $image
```

Run this single verification command. The named container is retained so the
results can be copied out; use an unused name when repeating it:

```powershell
docker run --name audit-rl-env-rc1-check --network none --cpus 2 --memory 4g $image python -m audit_env.verify --output /tmp/verification
```

The command must exit zero. It runs the full isolation-required test suite,
twenty separate pairs and all eighty policy/episode evaluations, plus a real
timeout and deliberately incorrect expectation control. Copy the evidence out
and run the three-case scripted demo with the same frozen image:

```powershell
docker cp audit-rl-env-rc1-check:/tmp/verification ./verification-results
docker run --rm --network none --cpus 2 --memory 4g $image python -m audit_env.demo
docker rm audit-rl-env-rc1-check
```

Run the prepared image by its locked identity. `release/image-lock.json` records
the tested image digest/ID, platform, source digest and uncompressed image size.
The saved image and source ZIP are separate files; neither is nested into its
own build context. The fresh-checkout evidence and size/checksum record are in
`release/rehearsal/` and the delivery directory. See `docs/stage-12.md` for actual
results and remaining limits. No organizer submission is performed automatically.

For a new development image, build from the pinned base and pinned requirements:

```sh
docker build --platform linux/amd64 -t audit-rl-env:rc1 .
```

Image preparation can use networking. The shipped prepared image is the frozen
offline execution artifact. A rebuild may resolve different Debian packages or
build metadata and needs a new lock and rehearsal; an entirely offline build
would also require the base image, package artifacts and apt inputs locally.
The archived source includes evaluator-only truth for the owner/jury, while
ordinary policies remain in data-free jails with no evaluator file access.

A Python 3.11 project for a reproducible financial audit simulator with synthetic
records, investigation tools and a separate evaluator. Stage 02 provides strict
schemas, file readers, public settlement views and hand-authored fixtures. Stage
03 publishes the matcher and reward; Stage 04 adds a fixture-backed episode and
investigation tools. Stage 05 adds Linux process isolation and an external
deadline supervisor. Stage 06 generates clean KZT companies, duplicate invoices
and missing/partial allocations from seeded event histories. Stage 07 adds
directional FX conversion and local reporting periods. Stage 08 composes the two
interaction scenarios and validates small/large profiles against final evidence.
Stage 09 supplies four baseline adapters, captured public trajectories and
separate evaluator metrics.
Stage 10 adds deterministic replay, complete ID/order transformations and the
public train/dev exports with disjoint rehearsal inputs.
Stage 11 adds one offline verification command and an 80-run local rehearsal
with separate paired checks, resource measurements and retained failure traces.
Stage 12 supplies the licensed release, open JSON Schemas, frozen runtime,
scripted demo and clean-checkout rehearsal, completing [the roadmap](docs/ROADMAP.md).

## Windows setup (cmd.exe)

Open Command Prompt in the repository root. Create the virtual environment only
if it does not already exist:

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
```

Installation needs access to a package index or a prepared local wheel source.
`requirements.in` lists direct dependency ranges; `requirements.txt` pins the
resolved installation, including transitive dependencies. Install from the latter
to reproduce this baseline. Keep `tzdata` installed for Windows timezone support.

Run these Stage 01 checks after activation:

```bat
python -m pip check
python -m audit_env
python -m pytest --version
```

In PowerShell, activation is optional; use the interpreter explicitly:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m audit_env
.\.venv\Scripts\python.exe -m pytest --version
```

The system `python` may select another version. The project virtual environment
was verified with Python 3.11.9. The smoke check prints:

```text
Python: 3.11.9
Pydantic: 2.14.4
Decimal: 0.3
Timezone: Asia/Almaty
Environment is ready.
```

The Python patch version follows the selected 3.11 runtime. The decimal example
has the independently calculated expected result 0.1 + 0.2 = 0.3.
`pip check` checks installed dependency compatibility; `pytest --version` confirms
the test runner is installed. Run the Stage 02 suite and inspect a fixture with:

```bat
python -m pytest -q
python -m audit_env --fixture tests/fixtures/company-b/public
```

The latter prints public settlement evidence: 7,000,000 received, 5,000,000 applied
and 2,000,000 unapplied, all in KZT minor units. See [the schema guide](docs/schemas.md)
and [the Stage 02 record](docs/stage-02.md).

## Fixture episode demo

Run the Stage 04 fixture episode and write its provisional trajectory:

```bat
python -m audit_env --demo-fixture company-b
```

The printed observations and per-step rewards are what the policy receives in
closed mode. The trusted runner prints the actual score separately. The trace is
written to `tests/fixtures/provisional-trajectory.jsonl` by default; pass
`--trace PATH` to choose another destination. This demonstration keeps the
fixture policy and evaluator in one process. Use the isolated entry point below
for Stage 05 and ordinary policies.

## Isolated fixture episode (Stage 05)

Prepare the image, then run the complete suite with isolation checks required:

```sh
docker build -t audit-rl-env:stage05 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage05 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage05 python -m audit_env --isolated-fixture company-b
```

The last command serves all five tools to a separate unprivileged policy and
prints the trusted score `0.992`. Its default outputs inside the container are
`runs/stage-05/trajectories.jsonl` and `runs/stage-05/private-result.json`; copy them
out before removing a container if needed, or mount a trusted output directory.
The policy receives numeric zero for every closed-mode reward. It derives the
2,000,000-minor-unit finding from public responses, without an expected-answer
file. `--policy PATH` selects a trusted host-side program to copy into the jail;
`--seconds 0.2` is useful with a sleeping policy. The default deadline is 60 seconds.

The trusted supervisor runs as container root, drops the policy to UID/GID 65534
inside a fresh data-free chroot, clears supplementary groups and inherited
environment, and supplies only stdin/stdout JSONL pipes and the immutable Python
runtime/program. There is no `/proc` or evaluator mount in the jail. Seccomp
blocks network, process creation, process inspection and namespace changes.
No Docker socket or privileged container is needed. Start the image as its
default root identity; unsupported platforms fail instead of silently running an
unrestricted policy. See [the Stage 05 record](docs/stage-05.md) for permissions,
protocol, deadline semantics and measured checks.

Windows pytest runs the portable checks and skips Linux integration. Setting
`AUDIT_REQUIRE_ISOLATION=1` makes a missing Linux runtime fail those checks.

## Generated companies (Stage 06)

After activating the Windows virtual environment, export a small mixed company
to a new directory:

```bat
python -m audit_env --generate runs/stage-06/company --seed 6 --generator-config configs/stage06-mixed.json
python -m audit_env --fixture runs/stage-06/company/public
python -m pytest -q tests/test_stage06.py
```

The export has the same six public files as a fixture and a protected private
directory containing truth, row-level provenance, latent history and clean books.
Existing destinations are rejected to prevent stale or overwritten episodes.
Omit `--generator-config` for a clean company. The versioned config independently
sets `duplicate_invoices`, `missing_allocations` and `partial_allocations`.
The latter two are variants of the `payment_allocation` issue family. All amounts
are KZT minor units. Every company includes valid split receipts, recurring
amounts and a linked refund. See [the Stage 06 record](docs/stage-06.md).

Run the generated company through the restricted Linux policy and existing tools:

```sh
docker build -t audit-rl-env:stage06 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage06 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage06 python -m audit_env --isolated-generated --seed 6 --generator-config configs/stage06-mixed.json
```

The Stage 06 demo policy derives three supported findings through public tools.
With ten inspections its true score is `0.98`; closed wire rewards remain `0`.
Outputs default to `runs/stage-06/trajectories.jsonl` and `private-result.json`
inside the container. `--trace` and `--private-result` select other destinations.
Generated records and truth remain in trusted memory during this run, without
agent mounts. The trusted API is
`reset(seed=6, config={"generator": generator_config, "mode": "closed"})`;
seed/config are never part of observations. The four adapters are described below.

## FX and reporting periods (Stage 07)

The versioned Stage 07 config supports KZT/USD/EUR (exponent 2) and JPY (0),
an IANA timezone, and clean events on both sides of the reporting boundary.
`wrong_fx_dates`, `wrong_fx_rates` and `misplaced_recognitions` independently
enable the two new families; the existing duplicate/allocation switches still
work. Set every issue count to zero for a clean FX/boundary control. FX options
require `version: "stage07-v1"`; omitting a config retains the Stage 06 KZT profile.

```bat
python -m audit_env --generate runs/stage-07/company --seed 7 --generator-config configs/stage07-mixed.json
python -m audit_env --fixture runs/stage-07/company/public
python -m pytest -q tests/test_stage07.py
```

Use a fresh export directory if the example already exists. Invoice conversion
uses the local service date; payment conversion uses the local payment date.
Source minor units become source major units, then target major/minor units,
with one `ROUND_HALF_UP` rounding. USD 100 at 500 KZT/USD is 5,000,000 KZT minor
units; posting 4,900,000 creates a 100,000-minor-unit discrepancy. Missing rates
invalidate a company. FX mutations that leave the rounded posting unchanged
are skipped, and insufficient effective candidates reject the configuration.

Period membership uses the manifest timezone and `[start, end)`. November 1
00:30 +05:00 is in November despite being October in UTC. Adjacent-period
documents, ledger rows and FX rates remain accessible through the same tools.

```sh
docker build -t audit-rl-env:stage07 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage07 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage07 python -m audit_env --isolated-generated --seed 7 --generator-config configs/stage07-mixed.json
```

The restricted demo derives all six mixed-profile findings from public tools,
with F1=1 and true return **0.978** (11 inspections plus submit). Closed wire
rewards remain zero. Outputs default to `runs/stage-07/trajectories.jsonl` and
`private-result.json`. The agent runtime includes read-only public IANA timezone
data. See [the Stage 07 study note](docs/stage-07.md) for checks and limitations.

## Interactions and size profiles (Stage 08)

`stage08-v1` adds two explicit scenarios. `boundary_scenario` combines a foreign
underapplication (A) with a late application journal (B). `duplicate_fx_scenario`
combines duplicate recognition (A) with a wrong rate on the extra journal (B).
Each takes `count` and `variant`: `clean`, `a_only`, `b_only` or `both`. Scenario
errors consume the existing family counts, rather than adding hidden issues.
Boundary B consumes the new `misplaced_applications` count. The full count and
proof rules are in [the schema guide](docs/schemas.md).

The six `configs/stage08-*.json` files include two tiny worked scenarios and
small/large clean/mixed profiles. Mixed profiles contain exactly 12 issues.
The small profile has 224–226 ledger rows and 74 documents; the large profile
has 584–586 rows and 194 documents. Both meet the suggested size ranges.

```bat
python -m audit_env --generate runs/stage-08/large-company --seed 8 --generator-config configs/stage08-large-mixed.json
python -m pytest -q tests/test_stage08.py
```

Export uses a new directory. The trusted CLI prints actual counts and the public
evidence discovery bound, including submit. Generation independently reconstructs
all final defects before export and rejects incorrect amounts, missing/unsupported
truth, incomplete proofs, impossible counts and oversized discovery plans.

Use the trusted Python API for a controlled four-way comparison:

```python
import json
from pathlib import Path
from audit_env.composition import scenario_variants

config = json.loads(Path("configs/stage08-duplicate-fx.json").read_text())
variants = scenario_variants(8, config, "duplicate_fx")  # Or "boundary".
for name, episode in variants.items():
    print(name, [(t.type, t.expected_amount_minor) for t in episode.truth.issues])
```

The clean source books match across those variants. In the duplicate example,
original recognition is 50,000 KZT and extra recognition is 49,000. Duplicate
amount is **49,000 KZT**, FX amount **1,000 KZT**, with different canonical
targets. Those two findings measure different defects and do not establish a
50,000 KZT financial loss. See [the Stage 08 study note](docs/stage-08.md).

```sh
docker build -t audit-rl-env:stage08 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage08 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage08 python -m audit_env --isolated-generated --seed 8 --generator-config configs/stage08-large-mixed.json
```

The large mixed demo uses **22 actions** including submit, returns **0.958**, and
has TP=12, FP=0, FN=0. At larger sizes it reconciles listed rows before opening
only discrepant payment settlements. Default outputs are under `runs/stage-08/`;
closed wire rewards remain zero. The four baseline adapters follow below.

## Four policies and captured trajectories (Stage 09)

Run all four adapters on the same fixture inside the prepared offline image:

```sh
docker build -t audit-rl-env:stage09 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage09 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage09 python -m audit_env.baselines --fixture company-a --output runs/stage-09/company-a
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage09 python -m audit_env.baselines --fixture company-b --output runs/stage-09/company-b
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage09 python -m audit_env.baselines --generator-config configs/stage08-large-mixed.json --seed 7091 --output runs/stage-09/large-mixed
```

Select one with `--baseline random`, `reconciliation`, `mass_accusation` or
`oracle`. `--policy-seed` defaults to 0 and controls only random exploration;
the company seed stays in the evaluator. Each ordinary adapter starts in a
fresh jail and receives only public tool messages. The oracle runs solely in
the trusted evaluator and submits a complete accepted proof without inspections.
The common adapter and accounting rules are in `policies/baselines.py`;
`policies/oracle.py` is excluded from the jailed program.

Each policy produces `trajectories.jsonl` and a separate `private-result.json`
under its output subdirectory. Mount a trusted output directory at `/results`
and use `--output /results/...` to retain files after `--rm`, or copy them out
before removing the container. The CLI prints evaluator-only P/R/F1, return,
inspections, actions and elapsed time. Closed trace rewards remain zero.
`delivered: true` identifies an actual delivered response; an undelivered timeout
event has `action: null`, `truncated: true` and consumes no extra action.

On faulty `company-b`, reconciliation proves a 2,000,000-minor-unit allocation
gap and returns **0.992**, versus **−1** for silence. On clean `company-a`,
reconciliation submits no findings and returns **0.992**; the valid accusation
policy produces four false positives and returns **−1**. On the large mixed
seed 7091, reconciliation finds all 12 issues in **22 actions**, returning
**0.958**, while 30 mass accusations are false positives. Oracle return is
**1** at zero inspections. These are local acceptance runs, not jury results.

Portable checks: `python -m pytest -q tests/test_stage09.py`. Ordinary CLI runs
require Linux isolation; `run_local_policy` is explicitly a trusted test harness.
Retained sample captures are under `episodes/examples/stage09/`, outside ignored
`runs/`. See [the Stage 09 study note](docs/stage-09.md) for the adapter contract,
worked evidence, timeout semantics, exact checks and limitations.

## Replay, paired checks and dataset splits (Stage 10)

The versioned plan is `configs/stage10-splits.json`: ten train inputs, ten dev
inputs and twenty separate rehearsal inputs. All forty seeds and normalized
parameter mixes are distinct. Public episode files are under `episodes/train/`
and `episodes/dev/`, indexed by `episodes/split-manifest.json`. Each split covers
clean books, all four single families and both interacting scenarios.
Evaluator truth, provenance, clean books and history are under the separate
`evaluator/stage10/` tree, excluded from every ordinary policy jail.

After activating the Windows virtual environment, reproduce or check the export:

```bat
python -m audit_env.datasets
python -m audit_env.datasets --check --paired-report evaluator/stage10/paired-checks.json
python -m pytest -q tests/test_stage10.py
```

Export verifies matching existing bytes and rejects stale files instead of
overwriting them. `--check` requires the files to exist. `--root PATH` selects
another export root. JSON/JSONL/CSV output uses UTF-8 and LF on both platforms.
The twenty paired checks regenerate records and replay identical actions,
rename every linked ID, change synthetic business descriptions, permute every
public table, remap oracle proofs, validate causal history and compare equal-cost
scores. The report is deterministic and excludes wall-clock durations. It
contains **20 passing pairs**, including **five clean** and **five interacting**;
oracle return is **0.992** on both sides at four inspections plus submit.

Prepare and check the offline Linux path:

```sh
docker build -t audit-rl-env:stage10 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage10 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage10 python -m audit_env.datasets --check --paired-report evaluator/stage10/paired-checks.json
```

The baseline CLI accepts `--episode PUBLIC_DIRECTORY --evaluator PRIVATE_DIRECTORY`
to load an exported episode on the trusted side. Choose both paths for one ID
from the split manifest, such as `episodes/dev/<episode_id>` and
`evaluator/stage10/dev/<episode_id>`. Ordinary policies still receive only the
tool channel. The process-isolation tests exercise exported and transformed
episodes and verify that evaluator material, configs and source files cannot be
read or modified by the policy.

Read [the Stage 10 study note](docs/stage-10.md) for the transformation rules,
worked remapping, verification commands and limits. Stage 11's 80 baseline
evaluations and complete offline verification command are documented below.

## Prepared Linux runtime

Install Docker with a running Linux container engine. Prepare the image while
the base image and pinned packages are available:

```sh
docker build -t audit-rl-env:dev .
```

The Dockerfile uses `python:3.11-slim`, installs `requirements.txt` during build,
and copies the project to `/app`. Its default command runs the smoke check.
After a successful build, run it without networking:

```sh
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:dev
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:dev python -m pip check
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:dev python -m pytest --version
```

Offline execution uses Python, dependencies and source already stored in the
image. It does not download packages at startup. An offline build additionally
needs the base image and all installation artifacts available locally; the
current Dockerfile does not prepare a wheel bundle for that purpose. The tested
release image identity is frozen in `release/image-lock.json` as required by R01.

Container build and offline execution were verified during Stage 05, including
the complete suite and isolated CLI demonstration. The Linux engine was
unavailable during the earlier stages; [the Stage 01 record](docs/stage-01.md)
preserves those historical results. For the default development image, run:

```sh
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:dev python -m pytest -q
```

## Complete offline verification (Stage 11)

Prepare the image with Docker's Linux engine, then run the single verification
command without networking, with two CPUs and 4 GiB RAM:

```sh
docker build -t audit-rl-env:stage11 .
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage11 python -m audit_env.verify
```

To retain the generated report and traces on Windows, create an empty output
directory and bind it into the container. In PowerShell, from this repository:

```powershell
New-Item -ItemType Directory -Path runs/stage-11-review
docker run --rm --network none --cpus 2 --memory 4g --mount "type=bind,source=$($PWD.Path)\runs\stage-11-review,target=/results" audit-rl-env:stage11 python -m audit_env.verify --output /results
```

The command returns zero only after the full isolation-required pytest suite,
train/dev byte checks, twenty paired checks, a real jailed timeout probe, an
incorrect-expectation rejection and all eighty policy/episode runs pass. Every
ordinary policy uses the Linux jail. Oracle runs on the trusted evaluator side.
All four policies use the same twenty frozen rehearsal inputs, including five
clean and five interacting episodes. These are local cases, not jury hidden data.

Output includes `results.json` (every row, arithmetic means, versions, inputs,
hardware and resource measurements), `report.md`, `paired-checks.json`, pytest
logs and all eighty `trajectories/<episode_id>/<policy>/trajectories.jsonl`
captures with separate evaluator results. Reports and seeds are evaluator-only.
An output directory must be empty or new; a failed run cannot overwrite an old
pass. On a failed run after output setup, `failure.json` records the failure.
Default output is a fresh timestamped directory under ignored `runs/stage-11/`.
The retained Stage 11 evidence lives outside that ignored directory in
`evaluator/stage11/`; see [the study note](docs/stage-11.md).

Per-episode memory is a conservative RSS upper bound: sum of fresh-worker
evaluator and policy kernel high-water marks, which may occur at different
times. End-to-end wall time includes worker startup, generation, jail setup and
trace writes; policy elapsed time is also retained separately. Timings and RSS
are measurements, not semantic replay fields. The generator's largest supported
profile reaches 200 documents but remains below the suggested 2,000-ledger-row
upper envelope. These scripted-policy results make no training-improvement claim.

`--expectations PATH` selects the independent hand-calculated canary fixture.
Verification creates a throwaway incorrect copy and checks the real CLI exits
with code 1, then verifies the unchanged original again. Windows can run the
portable pytest suite; the complete verification command requires the prepared
offline Linux image and does not fall back to unrestricted policy execution.

## Project documents

Read [the organizer brief](docs/task.md), [requirements](docs/requirements.md),
[repository guidance](docs/AGENTS.md), and [the roadmap](docs/ROADMAP.md).
