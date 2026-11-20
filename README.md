# Financial audit RL environment

A Python 3.11 project for a reproducible financial audit simulator with synthetic
records, investigation tools and a separate evaluator. Stage 02 provides strict
schemas, file readers, public settlement views and hand-authored fixtures. Stage
03 publishes the matcher and reward; Stage 04 adds a fixture-backed episode and
investigation tools. Later generator, isolation and evaluation work follows
[the roadmap](docs/ROADMAP.md).

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
fixture policy and evaluator in one process. Process isolation and deadline
enforcement are Stage 05 work.

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
current Dockerfile does not prepare a wheel bundle for that purpose. Freeze the
tested image digest at release as required by R01.

Container build and offline execution remain unverified on this checkout: the
Docker client is installed, but its Linux engine was unavailable to the agent
during Stage 01 and the Stage 02 retry. The owner reports successful Docker
execution. See [the Stage 01 record](docs/stage-01.md) for the original commands
and results. Once accessible, run the suite in the prepared image with:

```sh
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:dev python -m pytest -q
```

The complete system verification entry point, `python -m audit_env.verify`, is
planned for Stage 11 and is not available yet.

## Project documents

Read [the organizer brief](docs/task.md), [requirements](docs/requirements.md),
[repository guidance](docs/AGENTS.md), and [the roadmap](docs/ROADMAP.md).
