"""Trusted jury entry points. Never import this module into a policy process."""

import copy
import logging
from pathlib import Path
import time

from audit_env.environment import AuditEnvironment
from audit_env.generation import generate_episode as generate
from audit_env.schemas import Truth
from audit_env.scoring import score_submission
from audit_env.serialization import load_public, read_json
from audit_env.wire import initial_message, transition_message

LOG = logging.getLogger(__name__)


def generate_episode(seed: int, config: dict, output_dir: str) -> None:
    """Six public files at the root; evaluator files in private/."""
    episode = generate(seed, config)
    from audit_env.serialization import save_public, write_json
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    save_public(directory, episode.public)
    private = directory / "private"
    private.mkdir(mode=0o700)
    for name in ("truth", "provenance", "history", "clean"):
        path = private / f"{name}.json"
        write_json(path, getattr(episode, name))
        path.chmod(0o600)


def _load(directory):
    directory = Path(directory)
    public = load_public(directory)
    truth_path = directory / "private/truth.json"
    if not truth_path.exists():
        truth_path = directory / "truth.json"
    truth = read_json(truth_path, Truth)
    return public, truth


def native_action(action):
    if (not isinstance(action, dict) or set(action) != {"name", "args"}
            or not isinstance(action["name"], str) or not isinstance(action["args"], dict)):
        # A malformed submit is still a submit and must terminate at -1.
        return {"type": "submit"} if isinstance(action, dict) and action.get("name") == "submit" else {}
    if "type" in action["args"]:
        return {"type": "submit"} if action["name"] == "submit" else {}
    return {"type": action["name"], **action["args"]}


def observation_reply(observation, action):
    result = copy.deepcopy(observation.get("result"))
    if action.get("type") == "list_records" and result is not None:
        result = {"records": [item["record"] for item in result["rows"]],
                  "next_cursor": result["next_cursor"]}
    elif action.get("type") == "get_record" and result is not None:
        result = result["record"]
    code = observation.get("error")
    return {"result": result, "error": None if code is None else {"code": code, "message": code},
            "remaining_steps": observation["remaining_steps"]}


class JudgeEnvironment:
    """Trusted environment facade; the supervisor must isolate the policy."""

    def __init__(self, *, clock=time.monotonic):
        self._env = AuditEnvironment()
        self._clock = clock
        self._deadline = None

    def reset(self, seed=None, config=None):
        started = self._clock()
        config = {} if config is None else config
        if (not isinstance(config, dict) or set(config) - {"mode", "episode_dir", "team_config"}
                or config.get("mode", "closed") not in ("closed", "train")):
            raise ValueError("invalid jury reset configuration")
        mode = "open" if config.get("mode") == "train" else "closed"
        if "episode_dir" in config:
            public, truth = _load(config["episode_dir"])
            initial, info = self._env.reset_episode(public, truth, mode=mode)
        else:
            initial, info = self._env.reset(seed, {"generator": config.get("team_config", {}), "mode": mode})
        self._deadline = started + 60
        return initial_message(initial)["observation"], info

    def step(self, action):
        request = native_action(action)
        if self._deadline is None:
            raise RuntimeError("reset required")
        if not self._env._episode_done and self._clock() >= self._deadline:
            transition = self._env.truncate()
        else:
            transition = self._env.step(request)
        message = transition_message(request, transition, closed=self._env._closed)
        return (observation_reply(message["observation"], request), message["reward"],
                message["terminated"], message["truncated"], message["info"])


def make_env():
    return JudgeEnvironment()


def run_isolated_policy(program: bytes, *, seed=None, config=None, seconds=60):
    """Run an unchanged jury JSONL policy in the existing data-free Linux jail.

    The initial message and transitions have the standard observation/reward/
    terminated/truncated/info envelope; incoming actions use name/args.
    The external supervisor includes reset and jail preparation in the deadline.
    """
    from audit_env.isolation import run_isolated_fixture
    return run_isolated_fixture(policy_program=program, seed=seed, seconds=seconds,
                                judge_config={} if config is None else config)


def score_episode(episode_dir: str, findings: dict, inspection_steps: int) -> dict:
    public, truth = _load(episode_dir)
    env = AuditEnvironment()
    env.reset_episode(public, truth)
    score = score_submission(truth, findings, env._evidence_ids(), inspection_steps)
    keys = ("tp", "fp", "fn", "precision", "recall", "f1")
    if score.validation_error:
        LOG.warning("Invalid jury submission: %s", score.validation_error)
        return {**dict.fromkeys(keys), "return": -1.0}
    return {**{key: getattr(score, key) for key in keys}, "return": score.score}
