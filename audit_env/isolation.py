"""Linux-only jail and deadline supervisor. Never fall back to shared access."""

from __future__ import annotations

import ctypes
import copy
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict

from .environment import AuditEnvironment, FIXTURE_ROOT
from .wire import initial_message, transition_message


MAX_MESSAGE = 256 * 1024
AGENT_UID = 65534
AGENT_GID = 65534
RUNTIME = Path("/opt/agent-runtime")


class PolicyError(Exception):
    """Untrusted process failed or violated the bounded JSONL protocol."""


class Deadline:
    def __init__(self, seconds, clock=time.monotonic):
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("deadline must be positive and finite")
        self.clock = clock
        self.end = clock() + seconds

    def remaining(self):
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise TimeoutError
        return remaining


class PipeChannel:
    """Nonblocking reads AND writes: a policy cannot stall the supervisor."""

    def __init__(self, process):
        self.process = process
        self.buffer = bytearray()
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)

    @staticmethod
    def _wait(stream, event, deadline):
        with selectors.DefaultSelector() as selector:
            selector.register(stream, event)
            if not selector.select(deadline.remaining()):
                raise TimeoutError
        deadline.remaining()

    def send(self, message, deadline):
        payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode() + b"\n"
        if len(payload) > MAX_MESSAGE:
            raise PolicyError
        view = memoryview(payload)
        while view:
            self._wait(self.process.stdin, selectors.EVENT_WRITE, deadline)
            try:
                count = os.write(self.process.stdin.fileno(), view)
            except BrokenPipeError as exc:
                raise PolicyError from exc
            except BlockingIOError:
                continue
            view = view[count:]

    def receive(self, deadline):
        while b"\n" not in self.buffer:
            self._wait(self.process.stdout, selectors.EVENT_READ, deadline)
            chunk = os.read(self.process.stdout.fileno(), 8192)
            if not chunk:
                raise PolicyError
            self.buffer.extend(chunk)
            if len(self.buffer) > MAX_MESSAGE:
                raise PolicyError
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        try:
            value = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise PolicyError from exc
        # Parsing and buffered/prequeued submissions obey the same deadline.
        deadline.remaining()
        return value


def supervise(env, initial, channel, *, seconds=60.0, closed=True, clock=time.monotonic, deadline=None, judge_protocol=False):
    """Own all timing outside step, including a policy that sends nothing."""
    records = []
    reason = "completed"
    # Startup write is independently bounded; episode clock starts at delivery.
    channel.send(initial_message(initial), deadline or Deadline(seconds, clock))
    deadline = deadline or Deadline(seconds, clock)
    while True:
        action = None
        try:
            action = channel.receive(deadline)
            deadline.remaining()
            if judge_protocol:
                from judge_adapter import native_action
                request = native_action(action)
            else:
                request = action
            transition = env.step(request)
            # Authoritative action receipt time is checked above. Tool execution
            # stays trusted and bounded, and is followed by a bounded write.
        except (TimeoutError, PolicyError) as exc:
            reason = "timeout" if isinstance(exc, TimeoutError) else "policy_error"
            action = None
            transition = env.truncate("TIME_LIMIT" if reason == "timeout" else "POLICY_ERROR")
        message = transition_message(request if action is not None else None, transition, closed=closed)
        if judge_protocol:
            from judge_adapter import observation_reply
            message["observation"] = observation_reply(message["observation"], request if action is not None else {})
        records.append({
            "episode_id": initial["manifest"]["episode_id"],
            "step": len(records) + 1, "action": copy.deepcopy(action), "delivered": False,
            **copy.deepcopy(message),
        })
        try:
            channel.send(message, deadline)
            records[-1]["delivered"] = True
        except (TimeoutError, PolicyError) as exc:
            if not (transition[2] or transition[3]):
                reason = "timeout" if isinstance(exc, TimeoutError) else "policy_error"
                transition = env.truncate("TIME_LIMIT" if reason == "timeout" else "POLICY_ERROR")
                final = transition_message(None, transition, closed=closed)
                if judge_protocol:
                    final["observation"] = observation_reply(final["observation"], {})
                records.append({
                    "episode_id": initial["manifest"]["episode_id"], "step": len(records) + 1,
                    "action": None, "delivered": False, **copy.deepcopy(final),
                })
            break
        if transition[2] or transition[3]:
            if transition[3] and reason == "completed":
                reason = "step_limit"
            break
    return records, reason


def _enter_jail(directory):
    """Runs in a fresh single-threaded child before exec; no inherited handles."""
    import resource

    os.setsid()
    os.chroot(directory)
    os.chdir("/")
    os.setgroups([])
    os.setgid(AGENT_GID)
    os.setuid(AGENT_UID)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
    # PR_SET_NO_NEW_PRIVS: even executable file bits cannot restore privilege.
    if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
        os._exit(125)


def run_isolated_fixture(
    fixture="company-b", *, policy_path=None, seconds=60.0, mode="closed",
    fixture_root=FIXTURE_ROOT, runtime=RUNTIME, generator_config=None, seed=None,
    policy_program=None, episode=None, judge_config=None,
):
    """Trusted entry point, supported only as root inside the Linux image."""
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("isolated execution requires the prepared Linux container as root")
    if not (Path(runtime) / "usr/local/bin/python3.11").is_file():
        raise RuntimeError("prepared agent runtime missing")
    # Validate before spawning; no silent unrestricted fallback.
    total_deadline = Deadline(seconds) if judge_config is not None else None
    if mode not in ("closed", "open"):
        raise ValueError("invalid mode")
    env = AuditEnvironment(fixture_root)
    reset_config = {"fixture": fixture, "mode": mode} if generator_config is None else {"generator": generator_config, "mode": mode}
    if episode is not None and generator_config is not None:
        raise ValueError("choose generated configuration or loaded episode")
    if judge_config is not None:
        from judge_adapter import make_env
        adapter = make_env()
        initial, _ = adapter.reset(seed, judge_config)
        env = adapter._env
        mode = "closed" if env._closed else "open"
    else:
        initial, _ = (env.reset(seed=seed, config=reset_config) if episode is None
                      else env.reset_episode(episode.public, episode.truth, mode=mode))
    default_program = "fixture_agent.py" if generator_config is None else "generated_demo.py"
    source = Path(policy_path) if policy_path else Path(__file__).parent.parent / "policies" / default_program
    if policy_path is not None and policy_program is not None:
        raise ValueError("choose a policy path or program")
    program = source.read_bytes() if policy_program is None else policy_program
    started = total_deadline.end - seconds if total_deadline is not None else time.monotonic()
    with tempfile.TemporaryDirectory(prefix="audit-jail-") as workspace:
        jail = Path(workspace) / "root"
        shutil.copytree(runtime, jail)
        (jail / "policy.py").write_bytes(program)
        (jail / "policy.py").chmod(0o444)
        process = subprocess.Popen(
            ["/usr/local/bin/python3.11", "-I", "-S", "-B", "/bootstrap.py"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            # The data-free root intentionally has no host ld.so cache.
            env={"LANG": "C.UTF-8", "LD_LIBRARY_PATH": "/usr/local/lib"}, close_fds=True, bufsize=0,
            preexec_fn=lambda: _enter_jail(str(jail)),
        )
        try:
            try:
                records, reason = supervise(env, initial, PipeChannel(process), seconds=seconds, closed=mode == "closed",
                                             deadline=total_deadline, judge_protocol=judge_config is not None)
            except (PolicyError, TimeoutError) as exc:
                transition = env.truncate("TIME_LIMIT" if isinstance(exc, TimeoutError) else "POLICY_ERROR")
                message = transition_message(None, transition, closed=mode == "closed")
                if judge_config is not None:
                    from judge_adapter import observation_reply
                    message["observation"] = observation_reply(message["observation"], {})
                records = [{"episode_id": initial["manifest"]["episode_id"], "step": 1,
                            "action": None, "delivered": False, **copy.deepcopy(message)}]
                reason = "startup_timeout" if isinstance(exc, TimeoutError) else "startup_error"
        finally:
            # The seccomp bootstrap forbids creating children or changing groups.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
        return {
            "initial_observation": initial, "trajectory": records,
            "private_result": {
                "score": asdict(env._last_scoring_result),
                "submission": env._last_submission.model_dump(mode="json") if env._last_submission else None,
                "actions": env.action_count, "reason": reason,
                "evaluator_pid": os.getpid(), "evaluator_uid": os.geteuid(),
                "agent_pid": process.pid, "agent_uid": AGENT_UID, "agent_gid": AGENT_GID,
                "agent_reaped": process.returncode is not None,
                "data_ownership": {
                    name: {"uid": path.stat().st_uid, "mode": oct(path.stat().st_mode & 0o777)}
                    for name, path in ({
                        "public_ledger": Path(fixture_root) / fixture / "public/ledger.csv",
                        "private_truth": Path(fixture_root) / fixture / "private/truth.json",
                        "policy_program": jail / "policy.py",
                    } if generator_config is None and episode is None and judge_config is None else {"policy_program": jail / "policy.py"}).items()
                },
                **({"record_storage": "trusted evaluator memory"} if generator_config is not None or episode is not None else {}),
                "elapsed_seconds": time.monotonic() - started,
            },
        }


def run_isolated_generated(seed, config=None, **kwargs):
    """Select generated records without changing the restricted tool channel."""
    return run_isolated_fixture(generator_config={} if config is None else config, seed=seed, **kwargs)
