# Stage 01 execution record

Date: 20 November 2026. Status: **partial** — local acceptance checks passed;
container build and offline execution could not be verified.

## Scope and inspection

Read the organizer brief, repository guidance, roadmap and requirements v1.0,
including R01 and R07. No requirement conflicts were found. The requirements
document became available after the interrupted attempt and was read before
completion. The interruption left no implementation edits to repair.

The existing `audit_env.__main__` already supplies the required minimal smoke
check, so it was reused. Exact dependency versions are present in
`requirements.txt`; `requirements.in` records direct ranges. The Dockerfile uses
Python 3.11 slim, installs the pins at build time and defaults to
`python -m audit_env`. The image digest is deferred to release under R01.

The virtual environment uses Python 3.11.9. The default system `python` resolves
to `C:\Python315\python.exe`, so all local checks below use the virtual environment
explicitly. The expected decimal result was calculated before editing:
0.1 + 0.2 = 0.3.

## Actual verification

Run from the repository root in PowerShell. Each of these exited with code 0:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m audit_env
.\.venv\Scripts\python.exe -m pytest --version
```

Results:

```text
No broken requirements found.

Python: 3.11.9
Pydantic: 2.14.4
Decimal: 0.3
Timezone: Asia/Almaty
Environment is ready.

pytest 9.2.0
```

The Docker client reports version 29.9.3 and context `desktop-linux`.
`docker build -t audit-rl-env:dev .` first encountered a sandbox denial on Docker's
buildx lock outside the workspace. Retrying with approved access reached Docker
and exited with code 1 because `dockerDesktopLinuxEngine` was unavailable:

```text
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
The system cannot find the file specified.
```

No image build completed. The README's network-disabled container commands have
not been executed. Start the Linux Docker engine, then run those build/run checks
to close this gap. Dependency installation into a fresh virtual environment was
also not rehearsed; these local results use the existing environment. No pytest
suite exists yet; runner availability is the Stage 01 check, not a suite pass.

## Study note

Reading order: `README.md` for setup and build/run commands, then
`audit_env/__main__.py` for the existing smoke check, then this verification record.
Only the README and this record were added for Stage 01.

Worked input/output: running `python -m audit_env` adds decimal strings `0.1` and
`0.2`, prints `Decimal: 0.3`, and loads `Asia/Almaty`. Selecting the virtual
environment explicitly makes the command use the checked Python and dependency
installation.

Checkpoint: **Where do dependencies come from during an offline run?** They are
already installed in the prepared image by `docker build`. The later
`docker run --network none ...` uses that image without fetching packages. Build
prepares the runtime; run executes it. This distinction is documented, while the
container demonstration remains unverified until the engine is available.

Next stage: **02 — Define schemas and author independent fixtures**. This
execution stops at Stage 01.