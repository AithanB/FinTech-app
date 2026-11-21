"""Deadline/allowlist unit tests plus real Linux identity and jail checks."""

import json
import os
import sys
import time

import pytest

from audit_env.environment import AuditEnvironment, FIXTURE_ROOT
from audit_env.isolation import Deadline, PolicyError, RUNTIME, run_isolated_fixture, supervise
from audit_env.wire import initial_message, transition_message


class Clock:
    now = 10.0

    def __call__(self):
        return self.now


class Channel:
    def __init__(self, clock, events):
        self.clock = clock
        self.events = iter(events)
        self.sent = []

    def send(self, message, deadline):
        deadline.remaining()
        self.sent.append(message)

    def receive(self, deadline):
        advance, action = next(self.events)
        self.clock.now += advance
        deadline.remaining()
        if isinstance(action, Exception):
            raise action
        return action


def episode(fixture="company-b", mode="closed"):
    env = AuditEnvironment()
    initial, _ = env.reset(config={"fixture": fixture, "mode": mode})
    return env, initial


def empty_submit(initial):
    return {"type": "submit", "findings": {"episode_id": initial["manifest"]["episode_id"], "findings": []}}


@pytest.mark.parametrize("elapsed,expected", [(0.999, "completed"), (1.0, "timeout"), (1.001, "timeout")])
def test_exact_receipt_deadline(elapsed, expected):
    env, initial = episode("company-a")
    clock = Clock()
    channel = Channel(clock, [(elapsed, empty_submit(initial))])
    records, reason = supervise(env, initial, channel, seconds=1.0, clock=clock)
    assert reason == expected
    assert env.action_count == (1 if expected == "completed" else 0)
    assert records[-1]["truncated"] == (expected == "timeout")
    assert records[-1]["terminated"] == (expected == "completed")
    assert records[-1]["reward"] == 0
    assert env._last_submission.findings == []
    # A timeout adds no inspection: clean empty answer remains perfect.
    assert env._last_score == 1.0


def test_timeout_after_inspection_and_next_episode_starts_clean():
    env, initial = episode()
    clock = Clock()
    channel = Channel(clock, [(0.1, {"type": "calculator", "expression": "1+2"}), (1.0, None)])
    records, reason = supervise(env, initial, channel, seconds=1.0, clock=clock)
    assert reason == "timeout" and len(records) == 2
    assert records[0]["observation"]["result"] == "3" and records[0]["delivered"]
    assert records[1]["action"] is None and not records[1]["delivered"]
    assert records[1]["observation"]["remaining_steps"] == 99
    assert env.action_count == 1 and env._last_score == -1
    assert env._last_submission.findings == []
    observation, _ = env.reset(config={"fixture": "company-a"})
    assert observation["remaining_steps"] == 100 and env._last_score is None
    assert env._last_submission is None


def test_protocol_error_is_bounded_and_private():
    env, initial = episode()
    clock = Clock()
    channel = Channel(clock, [(0, PolicyError("PRIVATE-SENTINEL"))])
    records, reason = supervise(env, initial, channel, clock=clock)
    assert reason == "policy_error" and records[-1]["truncated"]
    assert "PRIVATE-SENTINEL" not in json.dumps(channel.sent + records)
    assert env.action_count == 0


def test_blocked_output_is_deadline_bounded():
    env, initial = episode()
    clock = Clock()

    class BlockedChannel(Channel):
        def send(self, message, deadline):
            if "reward" in message:
                self.clock.now += 2
                deadline.remaining()
            super().send(message, deadline)

    channel = BlockedChannel(clock, [(0, {"type": "calculator", "expression": "2"})])
    records, reason = supervise(env, initial, channel, seconds=1, clock=clock)
    assert reason == "timeout" and records[-1]["truncated"]
    assert all(not row["delivered"] for row in records)
    assert env.action_count == 1


def test_allowlists_fail_closed_on_nested_fields_and_error_text():
    env, initial = episode()
    initial["seed"] = 123
    with pytest.raises(ValueError):
        initial_message(initial)
    env, initial = episode()
    action = {"type": "get_document", "doc_id": "doc-492"}
    response = env.step(action)
    response[0]["result"]["payment"]["truth"] = "PRIVATE-SENTINEL"
    with pytest.raises(ValueError, match="unsafe observation"):
        transition_message(action, response, closed=True)
    with pytest.raises(ValueError, match="unsafe error"):
        transition_message(None, ({"error": "/private/truth.json", "remaining_steps": 1}, -1, False, True, {}), closed=True)
    safe = transition_message(None, ({"error": "TIME_LIMIT", "remaining_steps": 100}, -1, False, True, {}), closed=True)
    assert safe["reward"] == 0 and safe["info"] == {}


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_deadlines(value):
    with pytest.raises(ValueError):
        Deadline(value)


def test_never_fall_back_to_unrestricted_windows_policy():
    if sys.platform == "linux" and os.geteuid() == 0:
        pytest.skip("this host supports privilege dropping")
    with pytest.raises(RuntimeError, match="prepared Linux container"):
        run_isolated_fixture()


def require_linux():
    available = sys.platform == "linux" and os.geteuid() == 0 and (RUNTIME / "bootstrap.py").is_file()
    if not available:
        if os.environ.get("AUDIT_REQUIRE_ISOLATION") == "1":
            pytest.fail("required prepared root Linux isolation runtime unavailable")
        pytest.skip("requires prepared root Linux container; set AUDIT_REQUIRE_ISOLATION=1 to require")


def test_linux_real_fixture_closed_and_open():
    require_linux()
    for mode in ("closed", "open"):
        result = run_isolated_fixture(mode=mode)
        private = result["private_result"]
        assert private["reason"] == "completed"
        assert private["score"]["score"] == pytest.approx(0.992)
        assert private["score"]["tp"] == 1 and private["actions"] == 5
        assert private["submission"]["findings"][0]["claimed_amount_minor"] == 2000000
        assert private["agent_pid"] != private["evaluator_pid"]
        assert private["evaluator_uid"] == 0 and private["agent_uid"] == 65534
        assert private["agent_reaped"]
        assert private["data_ownership"] == {
            "public_ledger": {"uid": 0, "mode": "0o444"},
            "private_truth": {"uid": 0, "mode": "0o600"},
            "policy_program": {"uid": 0, "mode": "0o444"},
        }
        assert result["trajectory"][-1]["reward"] == (0 if mode == "closed" else pytest.approx(0.992))


def test_linux_agent_identity_permissions_and_sentinels(tmp_path, monkeypatch):
    require_linux()
    sentinel = "PRIVATE-CANARY-93817"
    private = tmp_path / "private-sentinel"
    private.write_text(sentinel)
    private.chmod(0o600)
    public = tmp_path / "public-record"
    public.write_text("unchanged")
    public.chmod(0o444)
    monkeypatch.setenv("AUDIT_PRIVATE_SENTINEL", sentinel)
    policy = tmp_path / "probe.py"
    paths = [str(private), str(public), str(FIXTURE_ROOT / "company-b/private/truth.json"),
             str(FIXTURE_ROOT / "company-b/public/ledger.csv"), "/proc/1/environ", "/proc/1/root"]
    policy.write_text('''import os, sys, json, socket
assert os.getuid() == os.geteuid() == 65534
assert os.getgid() == 65534 and os.getgroups() == []
assert "AUDIT_PRIVATE_SENTINEL" not in os.environ
assert set(os.listdir("/")) <= {"usr", "lib", "lib64", "bootstrap.py", "policy.py"}
assert not os.path.exists("/proc")
for path in PATHS:
    for mode in ("r", "w"):
        try:
            open(path, mode)
        except OSError:
            pass
        else:
            raise AssertionError("unexpected filesystem access")
for path in ("/policy.py", "/bootstrap.py", "/usr/local/bin/python3.11"):
    try:
        open(path, "w")
    except PermissionError:
        pass
    else:
        raise AssertionError("runtime writable")
for operation in (os.fork, os.setsid, lambda: socket.socket(), lambda: os.setuid(0), lambda: os.chroot("/")):
    try:
        operation()
    except PermissionError:
        pass
    else:
        raise AssertionError("forbidden syscall succeeded")
initial = json.loads(sys.stdin.readline())["observation"]
print(json.dumps({"type":"calculator","expression":str(os.getuid())}), flush=True)
assert json.loads(sys.stdin.readline())["observation"]["result"] == "65534"
print(json.dumps({"type":"submit","findings":{"episode_id":initial["manifest"]["episode_id"],"findings":[]}}), flush=True)
assert json.loads(sys.stdin.readline())["reward"] == 0
'''.replace("PATHS", repr(paths)))
    result = run_isolated_fixture(policy_path=policy)
    assert result["private_result"]["reason"] == "completed"
    assert result["private_result"]["actions"] == 2
    assert sentinel not in json.dumps(result)
    assert private.read_text() == sentinel and public.read_text() == "unchanged"
    assert private.stat().st_uid == public.stat().st_uid == 0


def test_linux_sleeping_policy_is_killed_and_next_episode_is_clean(tmp_path):
    require_linux()
    sleeper = tmp_path / "sleep.py"
    sleeper.write_text("import time\ntime.sleep(60)\n")
    started = time.monotonic()
    result = run_isolated_fixture(policy_path=sleeper, seconds=0.2)
    assert time.monotonic() - started < 5
    private = result["private_result"]
    assert private["reason"] == "timeout" and private["agent_reaped"]
    assert private["actions"] == 0 and private["submission"]["findings"] == []
    assert result["trajectory"][-1]["truncated"]
    with pytest.raises(ProcessLookupError):
        os.kill(private["agent_pid"], 0)
    clean = run_isolated_fixture("company-a")
    assert clean["private_result"]["reason"] == "completed"
    assert clean["private_result"]["score"]["score"] == pytest.approx(0.992)
    assert clean["initial_observation"]["remaining_steps"] == 100
    assert clean["private_result"]["submission"]["findings"] == []


@pytest.mark.parametrize("source", [
    'print("startup error /private/truth.json", flush=True)',
    'import sys; sys.stdout.write("x" * 300000); sys.stdout.flush()',
    'raise RuntimeError("PRIVATE-CANARY-93817")',
    'print("NaN", flush=True)',
])
def test_linux_hostile_output_cannot_leak_or_hang(tmp_path, source):
    require_linux()
    policy = tmp_path / "bad.py"
    policy.write_text(source)
    result = run_isolated_fixture(policy_path=policy, seconds=1)
    assert result["trajectory"][-1]["truncated"]
    assert result["private_result"]["agent_reaped"]
    assert "/private/truth.json" not in json.dumps(result)
    assert "PRIVATE-CANARY" not in json.dumps(result)
