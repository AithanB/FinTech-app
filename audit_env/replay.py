"""Deterministic semantic replay and paired-check reports, excluding wall time."""

from dataclasses import asdict
import hashlib
import json

from policies.oracle import run_policy as oracle

from .environment import AuditEnvironment
from .transformations import remap_ids, transform_episode
from .validation import validate_final_evidence
from .wire import initial_message, transition_message


REPLAY_VERSION = "stage10-replay-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def oracle_action(episode):
    actions = []
    oracle({"manifest": episode.public.manifest.model_dump(mode="json")}, actions.append, truth=episode.truth)
    return actions[0]


def replay_actions(episode, actions, *, mode="closed"):
    """Replay explicit requests; None is a trusted between-action TIME_LIMIT event."""
    env = AuditEnvironment()
    initial, _ = env.reset_episode(episode.public, episode.truth, mode=mode)
    rows = []
    for index, action in enumerate(actions, 1):
        request = json.loads(json.dumps(action, allow_nan=False))
        transition = env.truncate() if request is None else env.step(request)
        message = transition_message(request, transition, closed=mode == "closed")
        rows.append({"episode_id": initial["manifest"]["episode_id"], "step": index,
                     "action": request, **message})
        if message["terminated"] or message["truncated"]:
            # Do not silently ignore actions in a corrupted replay input.
            if index != len(actions):
                raise ValueError("replay contains actions after termination")
    private = {
        "actions": env.action_count,
        "score": asdict(env._last_scoring_result) if env._last_scoring_result is not None else None,
        "submission": env._last_submission.model_dump(mode="json") if env._last_submission else None,
    }
    return json.loads(json.dumps({"initial_observation": initial_message(initial)["observation"],
                                  "trajectory": rows, "private_result": private}, allow_nan=False))


def verify_capture(episode, capture, *, mode="closed"):
    """Verify captured delivery snapshots without pretending to redeliver timeout notices.

    Delivery status is transport metadata. Semantic responses, including explicit
    supervisor timeout events, must match. POLICY_ERROR events are replayed using
    their bounded error code, independent of the original process failure.
    """
    env = AuditEnvironment()
    initial, _ = env.reset_episode(episode.public, episode.truth, mode=mode)
    if capture[0]["metadata"]["initial_observation"] != initial:
        raise ValueError("replay initial observation mismatch")
    for index, row in enumerate(capture[1:], 1):
        if row["step"] != index or row["episode_id"] != episode.public.manifest.episode_id:
            raise ValueError("replay event identity mismatch")
        action = row["action"]
        if action is None:
            error = row["observation"].get("error")
            if error not in ("TIME_LIMIT", "POLICY_ERROR") or row.get("delivered") is not False:
                raise ValueError("invalid supervisor replay event")
            transition = env.truncate(error)
        else:
            transition = env.step(action)
        message = transition_message(action, transition, closed=mode == "closed")
        if any(row.get(key) != value for key, value in message.items()):
            raise ValueError(f"replay response mismatch at event {index}")
        if (message["terminated"] or message["truncated"]) and index != len(capture) - 1:
            raise ValueError("replay contains events after termination")
    return {"events": len(capture) - 1, "actions": env.action_count,
            "score": asdict(env._last_scoring_result) if env._last_scoring_result else None}


def check_pair(episode, transform_seed, *, duplicate=None):
    """Four actual inspections on each side, then equivalent oracle submissions."""
    validate_final_evidence(episode.public, episode.truth)
    transformed, mapping = transform_episode(episode, transform_seed)
    validate_final_evidence(transformed.public, transformed.truth)
    before = oracle_action(episode)
    after = remap_ids(before, mapping)
    if after != oracle_action(transformed):
        raise ValueError("paired oracle answer mismatch")
    inspections = [
        {"type": "list_records", "table": "ledger", "cursor": None, "limit": 50},
        {"type": "list_records", "table": "payments", "cursor": None, "limit": 50},
        {"type": "get_document", "doc_id": episode.public.payments[0].doc_id},
        {"type": "calculator", "expression": "1+2"},
    ]
    actions = [*inspections, before]
    source = replay_actions(episode, actions)
    repeated = replay_actions(episode if duplicate is None else duplicate, actions)
    public = episode.public.model_dump(mode="json")
    repeated_public = (episode if duplicate is None else duplicate).public.model_dump(mode="json")
    if public != repeated_public or source != repeated:
        raise ValueError("identical input replay mismatch")
    target = replay_actions(transformed, [*remap_ids(inspections, mapping), after])
    mapped_result = remap_ids(source["private_result"], mapping)
    # The scorer publishes matches sorted by issue ID. Renaming IDs changes
    # that presentation order without changing the compatible matched pairs.
    mapped_result["score"]["matches"].sort(key=lambda match: (match["issue_id"], match["submission_index"]))
    if mapped_result != target["private_result"]:
        raise ValueError("paired score or action cost mismatch")
    if source["private_result"]["score"]["score"] != .992:
        raise ValueError("oracle did not achieve hand-calculated four-inspection return")
    # Benign description/ID/order changes must not create issues for the public
    # reconciliation adapter. No truth is supplied to that adapter.
    from .baselines import run_local_policy

    reconciled = run_local_policy("reconciliation", episode=transformed)["private_result"]
    if reconciled["score"]["fp"] or reconciled["score"]["fn"]:
        raise ValueError("public reconciliation failed transformed episode")
    return {
        "episode_id": episode.public.manifest.episode_id,
        "transformed_episode_id": transformed.public.manifest.episode_id,
        "transform_seed": transform_seed, "issue_count": len(episode.truth.issues),
        "id_count": len(mapping), "public_sha256": digest(public),
        "replay_sha256": digest(source), "repeated_replay_sha256": digest(repeated),
        "transformed_public_sha256": digest(transformed.public.model_dump(mode="json")),
        "inspection_steps": 4, "total_actions": 5,
        "source_return": source["private_result"]["score"]["score"],
        "transformed_return": target["private_result"]["score"]["score"],
        "reconciliation_actions": reconciled["total_actions"],
        "passed": True,
    }
