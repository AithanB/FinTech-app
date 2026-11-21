# Stage 05 — Process boundary and deadline

Status: **passed**, verified on November 20, 2026. Stage 04 prerequisite:
`.\.venv\Scripts\python.exe -m pytest -q tests/test_stage04.py` passed 11 tests.
The organizer brief and R05–R06 govern this implementation; no requirement
conflict or organizer correction was found in the checkout. Work stops before
Stage 06 generation.

## Observable result and reading order

A separate ordinary policy can inspect the fixture through the existing five
tools and submit a supported finding. The evaluator owns all records, truth,
scoring and timing. A policy that never calls a tool still times out and is
killed and reaped. Closed messages carry zero rewards.

Read the changed files in this order:

1. `policies/fixture_agent.py`: the small public-data-only policy and JSONL
   request/reply loop. It never opens the expected-submission fixture.
2. `audit_env/wire.py`: strict initial/response allowlists, including nested
   public record schemas, enumerated errors and empty info.
3. `audit_env/isolation.py`: nonblocking pipe transport, monotonic deadline,
   privileged launch, identity drop, cleanup and private metrics.
4. `scripts/build_agent_runtime.py`, `scripts/agent_bootstrap.py`, `Dockerfile`:
   immutable runtime preparation, chroot layout and syscall restrictions.
5. `audit_env/environment.py`: trusted `truncate`, which scores an empty answer
   without consuming an action. `audit_env/__main__.py` exposes the isolated demo.
6. `tests/test_stage05.py`: independent deadline expectations, hostile policies,
   actual-identity permission checks and wall-clock cleanup tests. `README.md`
   documents the supported invocation.

## Worked input/output

The hand-authored company-b payment directs 7,000,000 KZT minor units to an
invoice. Its public settlement proves only 5,000,000 were applied. The policy
calls list_records, get_record, get_document and calculator, then submits:

```json
{"type":"submit","findings":{"episode_id":"ep-431","findings":[{"type":"payment_allocation","affected_ids":["pay-627","inv-264"],"claimed_amount_minor":2000000,"currency":"KZT","evidence_ids":["doc-492","settlement:pay-627"],"explanation":"The directed payment exceeds its recorded application."}]}}
```

The public terminal message is:

```json
{"observation":{"result":{"accepted":true},"remaining_steps":95},"reward":0.0,"terminated":true,"truncated":false,"info":{}}
```

The independently calculated discrepancy is 7,000,000 − 5,000,000 = 2,000,000.
One TP, no FP/FN gives F1=1. Four inspections cost 0.008, so the evaluator score
is 0.992. In the separate clean fixture the same calculation gives zero missing
allocation and the policy submits an empty answer. It also earns 0.992 at four
inspections. Open mode returns the actual terminal score and is covered by the
Linux integration test; the CLI intentionally demonstrates closed mode.

## Process identity and data ownership

The measured CLI run had evaluator PID 1, UID 0; agent PID 7, UID/GID 65534.
PIDs vary between runs. The policy itself asserts its real/effective UID,
GID and empty supplementary groups before attempting forbidden accesses.
Private results also record identities, ownership, cleanup and elapsed time.

The evaluator owns `/app` (mode 0700), public fixture files (0444), private
fixture files (0600) and the policy copy (0444). The policy's filesystem root
contains only its program, bootstrap, Python standard library, interpreter and
required shared libraries. Files/directories belong to root; the agent cannot
write them. There is no private/public dataset mount, `/proc`, host environment,
working directory or inherited evaluator descriptor in that root. The policy
receives JSON records through tools only. stdin/stdout are pipes; stderr goes
to `/dev/null` outside the jail and is never echoed into observations.

Before exec the trusted launcher creates a session, enters the chroot, clears
groups, drops UID/GID, limits address space to 256 MiB, disables core/file writes,
limits descriptors and sets no-new-privileges. The interpreter then loads the
trusted seccomp bootstrap before executing the policy. The filter forbids
network sockets, process creation/exec, session/group changes, process inspection
and namespace operations. Failure to prepare the sandbox stops execution; there
is no unrestricted fallback. The default outer container needs no privileged
flag, Docker socket or evaluator write mount for the agent. Its invocation
disables networking for the entire evaluator as well.

This is why a second process alone is insufficient: an ordinary child could
otherwise open the evaluator's files. Here both filesystem visibility and the
actual runtime identity deny access, and the child cannot reach the parent
through `/proc`, process-memory syscalls, signals or inherited file handles.

## Transport, time and cleanup

Protocol: one UTF-8 JSON object per line, maximum 256 KiB per message. The first
message is `{observation: initial, info: {}}`; subsequent replies carry the five
step fields. The policy writes existing action objects directly. Non-JSON,
nonfinite JSON constants, oversized output and premature EOF become bounded
`POLICY_ERROR` truncations. Untrusted startup output and exception text are
discarded, never echoed into public responses or private failure reasons.
Unknown action objects still follow the environment's step-consuming error path.

A monotonic clock starts when the initial message has been written to the
policy pipe. The initial write has a separate bounded startup deadline. Every
read and write waits on readiness with the remaining episode time; a policy
cannot evade the deadline by sleeping, flooding output or refusing replies.
Action parsing and receipt are checked before step, including buffered actions.
Receipt at the exact deadline is late. An on-time submit is accepted based on
receipt time; bounded trusted tool/scorer work follows receipt.

A timeout scores empty findings, sets truncated=true and adds no action. A
clean company with no inspections therefore still scores 1 at timeout under
the required common reward; the episode is nevertheless recorded as truncated.
Its terminal trace event has action=null and the next event index. Trace rows
carry `delivered=true` only after a complete reply is written to the pipe;
timeout/failure events that cannot be delivered have `delivered=false`. This
means delivery to the transport, not proof that the program consumed the bytes.

Finally, the supervisor kills the policy process group, waits for process exit,
closes pipes and removes the fresh jail, including on exceptions. The syscall
filter prevents the policy from creating descendants or escaping that group.
Each episode gets a new environment, counters, pipes and jail.

## Verification evidence

Commands executed from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_stage04.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
docker build -t audit-rl-env:stage05 .
docker run --rm --network none --cpus 2 --memory 4g -e AUDIT_REQUIRE_ISOLATION=1 audit-rl-env:stage05 python -m pytest -q
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env:stage05 python -m audit_env --isolated-fixture company-b
```

Windows: **73 passed, 7 skipped** (the Linux integration cases); pip reported
no broken requirements. Prepared Linux image: **79 passed, 1 skipped** (the
Windows-only unsupported-platform guard). All seven Linux integration cases
ran with isolation mandatory. The CLI returned trusted score **0.992** and its
trace contains five actions, all with reward **0**.

An additional normal CLI run used a bind mount of the workspace's
`runs/stage-05` to `/results`, with `--trace /results/trajectories.jsonl` and
`--private-result /results/private-result.json`, preserving those two local
artifacts after container removal. They are ignored local outputs. The stage
implementation, tests and this evidence summary are versioned source files.

Tests verify read/write denial for private sentinels and evaluator paths,
read/write denial at raw public dataset paths, immutable runtime/program files,
unchanged sentinel/public content, empty inherited private environment, denied
privilege restoration/network/fork/session/chroot operations, nested allowlist
failures, safe errors/startup output, strict boundary timing with a fake clock,
a real 0.2-second sleeping policy and a subsequent clean episode. The wall-clock
test requires the entire timed run and cleanup to finish within five seconds,
checks that the PID no longer exists, and verifies the next episode's full budget.

The initial Linux run failed three integration tests because the jailed loader
could not locate `libpython3.11.so.1.0`. The fixture and assertions were retained;
an explicit runtime-only LD_LIBRARY_PATH fixed startup without exposing a host
loader cache. The next full offline run passed. Docker initially had no reachable
Linux engine; starting the installed Docker Desktop engine resolved that blocker.

## Limits and checkpoint

This path requires Linux, root for the trusted chroot launcher, and the prepared
image. Windows alone verifies portable contracts only. The launcher is intended
for the single-threaded trusted CLI; do not call its preexec-based spawn from a
multithreaded service. Runtime preparation copies standard-library files and
shared libraries at build time; package/base-image preparation requires network
or a separate local artifact source, while verified execution needs no network.
The image digest and OS packages are not release-frozen yet (Stage 12).

The fixture policy covers only the hand-authored KZT allocation case. Generator,
general baselines, full replay and submission packaging remain later stages.
The jail and syscall tests exercise this threat boundary; they do not establish
protection against unknown kernel vulnerabilities or a malicious trusted runner.

Study question: inspect the public trace and private result for the same
submission. **Which process owns the true reward?** The trusted evaluator owns
truth and computes 0.992; the ordinary policy sees only the closed placeholder 0.

Next stage: **06 — Generate a clean company, duplicates and allocations**.
