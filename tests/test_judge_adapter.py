"""Published jury transport, boundary decisions, reward vectors and file pairs."""

import copy
import json
from pathlib import Path
import shutil

import pytest

from judge_adapter import JudgeEnvironment, generate_episode, make_env, score_episode, run_isolated_policy
from audit_env.schemas import Truth, TruthIssue
from audit_env.scoring import score_submission
from audit_env.judge_checks import check_matrix
from test_stage05 import require_linux
from test_stage05 import Clock, Channel, episode as native_episode
from audit_env.isolation import supervise


@pytest.fixture
def episode(tmp_path):
    directory = tmp_path / "episode"
    directory.mkdir()
    fixture = Path(__file__).parent / "fixtures/company-b"
    for p in (fixture / "public").iterdir():
        shutil.copy2(p, directory / p.name)
    shutil.copytree(fixture / "private", directory / "private")
    return directory


def action(name, **args):
    return dict(name=name, args=args)


def reset(env, directory, mode="closed"):
    return env.reset(123, dict(mode=mode, episode_dir=str(directory), team_config={}))


def answer(directory):
    return json.loads((directory / "private/expected_submission.json").read_text())


def test_reset_tools_closed_reward_and_snapshot(episode):
    env = make_env()
    initial, info = reset(env, episode)
    assert info == {} and initial["remaining_steps"] == 100
    assert set(initial) == {"task", "manifest", "policy", "remaining_steps"}
    json.dumps(initial, allow_nan=False)
    request = action("list_records", table="ledger", cursor=None, limit=50)
    first = env.step(request)
    second = env.step(request)
    assert first[0]["result"] == second[0]["result"]
    assert first[0]["remaining_steps"] == 99 and second[0]["remaining_steps"] == 98
    row = first[0]["result"]["records"][0]
    assert env.step(action("get_record", table="ledger", id=row["row_id"]))[0]["result"] == row
    assert env.step(action("get_document", doc_id="doc-492"))[0]["result"]["payment"]["payment_id"] == "pay-627"
    assert env.step(action("calculator", expression="0.1+0.2"))[0]["result"] == "0.3"
    for request in (action("calculator", expression="open('/private/truth.json')"),
                    action("get_record", table="ledger", id="absent"),
                    action("get_document", doc_id="absent"), action("unknown")):
        observation, reward, terminated, truncated, info = env.step(request)
        assert observation["result"] is None and set(observation["error"]) == {"code", "message"}
        assert reward == 0 and not terminated and not truncated and info == {}
    first[0]["result"]["records"].clear()
    assert env.step(action("get_record", table="ledger", id=row["row_id"]))[0]["result"] == row
    terminal = env.step(action("submit", findings=answer(episode)))
    assert terminal[0]["result"] == {"accepted": True}
    assert terminal[1:] == (0, True, False, {})
    previous = env._env._last_scoring_result
    env.step(action("submit", findings={}))
    assert env._env._last_scoring_result == previous
    assert reset(env, episode)[0] == initial


@pytest.mark.parametrize("submit", [False, True])
def test_hundred_action_boundary(episode, submit):
    env = make_env(); reset(env, episode)
    for _ in range(99):
        assert not env.step(action("calculator", expression="1"))[3]
    final = env.step(action("submit", findings=answer(episode)) if submit else action("calculator", expression="1"))
    assert final[2:4] == (submit, not submit)
    assert env._env.action_count == 100
    assert len(env._env._last_submission.findings) == int(submit)


def test_train_and_deadline_include_reset(episode, monkeypatch):
    class Clock:
        now = 0
        def __call__(self): return self.now
    clock = Clock(); env = JudgeEnvironment(clock=clock)
    original = env._env.reset_episode
    def slow(*args, **kwargs):
        clock.now += 20
        return original(*args, **kwargs)
    monkeypatch.setattr(env._env, "reset_episode", slow)
    reset(env, episode, "train")
    clock.now = 59.999
    assert env.step(action("calculator", expression="1"))[1] == 0
    clock.now = 60
    terminal = env.step(action("submit", findings=answer(episode)))
    assert terminal[2:4] == (False, True) and env._env.action_count == 1
    assert env._env._last_submission.findings == []
    clock.now = 100
    reset(env, episode, "train")
    assert env.step(action("submit", findings=answer(episode)))[1] == 1


def test_generate_and_external_file_reload_without_history(episode, tmp_path):
    directory = tmp_path / "generated"
    generate_episode(22, dict(version="stage08-v1", invoice_count=36, size_profile="small"), str(directory))
    assert (directory / "manifest.json").is_file() and (directory / "private/provenance.json").is_file()
    env = make_env(); initial, _ = reset(env, directory)
    seen, cursor = [], None
    while True:
        reply = env.step(action("list_records", table="ledger", cursor=cursor, limit=50))[0]["result"]
        assert len(reply["records"]) <= 50
        seen.extend(r["row_id"] for r in reply["records"])
        cursor = reply["next_cursor"]
        if cursor is None: break
    assert len(seen) > 101 and len(seen) == len(set(seen))
    # The jury may edit IDs and only the required public/truth files exist.
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["episode_id"] = "jury-edited"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    truth = json.loads((directory / "private/truth.json").read_text())
    truth["episode_id"] = "jury-edited"
    (directory / "truth.json").write_text(json.dumps(truth))
    shutil.rmtree(directory / "private")
    assert reset(env, directory)[0]["manifest"]["episode_id"] == "jury-edited"
    assert initial["manifest"]["episode_id"] != "jury-edited"


def test_score_api_invalid_null_metrics_and_unknown_type(episode, caplog):
    expected = answer(episode)
    assert score_episode(str(episode), expected, 10)["return"] == .98
    expected["findings"][0]["type"] = "unknown-string"
    assert score_episode(str(episode), expected, 10) == dict(tp=0, fp=1, fn=1, precision=0, recall=0, f1=0, **{"return": -1})
    expected["findings"] *= 31
    result = score_episode(str(episode), expected, 0)
    assert result["return"] == -1 and all(result[k] is None for k in result if k != "return")
    assert "Invalid jury submission" in caplog.text


F = dict(type="duplicate_invoice", affected_ids=["R1"], claimed_amount_minor=10000,
         currency="KZT", evidence_ids=["D1", "D2"], explanation="proof")
A = dict(issue_id="A", type="duplicate_invoice", affected_ids=["R1"], expected_amount_minor=10000,
         currency="KZT", evidence_sets=[["D1", "D2"]])


@pytest.mark.parametrize("number", range(1, 21))
def test_published_twenty_reward_vectors(number):
    truths, findings, steps = [copy.deepcopy(A)], [copy.deepcopy(F)], 10
    expected = (1, 0, 0, .98)
    if number == 2: findings=[]; expected=(0,0,1,-1)
    if number == 3: truths=[]; findings=[]; expected=(0,0,0,.98)
    if number == 4: truths=[]; expected=(0,1,0,-1)
    if number == 5: findings*=2; expected=(1,1,0,47/150)
    for n, key, value in ((6,"type","payment_allocation"),(7,"affected_ids",["R2"]),
                          (8,"claimed_amount_minor",10001),(9,"currency","USD"),
                          (10,"evidence_ids",["D1"]),(11,"evidence_ids",["D1","U"])):
        if number == n: findings[0][key]=value; expected=(0,1,1,-1)
    if number == 12:
        findings=[dict(F,type=kind,affected_ids=[f"R{i}"]) for i in range(1,6)
                  for kind in ("duplicate_invoice","payment_allocation","fx_conversion","period_cutoff")]
        expected=(1,19,0,-871/1050)
    if number in (13,14):
        truths.append(dict(A,issue_id="B",affected_ids=["R2"]))
        expected=(1,0,1,47/150)
        if number == 14: findings.append(dict(F,affected_ids=["R3"])); expected=(1,1,1,-.02)
    if number in (15,16,17):
        steps={15:0,16:50,17:100}[number]; expected=(1,0,0,{15:1,16:.9,17:.8}[number])
    if number == 18: findings*=31
    if number == 19: findings[0]["evidence_ids"]=[f"D{i}" for i in range(11)]
    if number == 20: findings[0]["explanation"]="x"*1001
    result=score_submission(Truth(episode_id="E",issues=[TruthIssue(**t) for t in truths]),
                            dict(episode_id="E",findings=findings), {"D1","D2","D3"}, steps)
    if number >= 18: assert result.score == -1 and result.validation_error
    else:
        assert (result.tp,result.fp,result.fn)==expected[:3]
        assert result.score == pytest.approx(expected[3],abs=1e-9,rel=0)


def test_published_data_and_file_pair_matrix():
    report=check_matrix()
    assert report["passed"] and report["transformations"]==dict(order=5,ids=5,both=10)
    assert [r["issues"] for r in report["rows"]]==[0]*5+[1]*10+[2]*5


def test_jury_supervisor_records_actual_translated_messages():
    env, initial = native_episode()
    clock = Clock()
    requests = [action("list_records", table="payments", cursor=None, limit=50),
                action("submit", findings=dict(episode_id=initial["manifest"]["episode_id"], findings=[]))]
    channel = Channel(clock, [(0, request) for request in requests])
    rows, reason = supervise(env, initial, channel, clock=clock, judge_protocol=True)
    assert reason == "completed"
    assert [r["action"] for r in rows] == requests
    assert "records" in rows[0]["observation"]["result"]
    assert rows[0]["observation"]["error"] is None
    assert rows[-1]["observation"]["result"] == {"accepted": True}
    for row, message in zip(rows, channel.sent[1:]):
        assert all(row[key] == value for key, value in message.items())


def test_linux_jury_protocol_uses_real_jail(episode):
    require_linux()
    program=b'''import json,sys,os
initial=json.loads(sys.stdin.readline())["observation"]
assert os.getuid()==65534
try:
    open("/app/judge_adapter.py")
    raise AssertionError("evaluator accessible")
except (FileNotFoundError,PermissionError): pass
print(json.dumps({"name":"calculator","args":{"expression":"0.1+0.2"}}),flush=True)
reply=json.loads(sys.stdin.readline())
assert reply["observation"]["result"]=="0.3" and reply["observation"]["error"] is None
print(json.dumps({"name":"submit","args":{"findings":{"episode_id":initial["manifest"]["episode_id"],"findings":[]}}}),flush=True)
json.loads(sys.stdin.readline())
'''
    run=run_isolated_policy(program,config=dict(mode="closed",episode_dir=str(episode)))
    assert run["private_result"]["agent_reaped"] and run["private_result"]["actions"]==2
    assert all(r["reward"]==0 and r["delivered"] for r in run["trajectory"])
    assert run["trajectory"][0]["action"]["name"]=="calculator"
    assert run["trajectory"][0]["observation"]["error"] is None


def test_linux_jury_policy_sleep_is_stopped_from_reset(episode):
    require_linux()
    import time
    started = time.monotonic()
    run = run_isolated_policy(b"import time\ntime.sleep(10)\n",
                              config=dict(mode="closed", episode_dir=str(episode)), seconds=.5)
    assert time.monotonic() - started < 5
    assert run["private_result"]["agent_reaped"]
    assert run["private_result"]["actions"] == 0
    assert run["trajectory"][-1]["truncated"]
    assert run["trajectory"][-1]["action"] is None
    assert run["trajectory"][-1]["observation"]["error"]["code"] == "TIME_LIMIT"
