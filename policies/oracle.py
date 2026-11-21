"""Evaluator-only adapter. Never copy this module or its input into the jail."""


def run_policy(initial, act, *, truth):
    """A zero-inspection upper bound, using the same submit action and scorer."""
    if truth.episode_id != initial["manifest"]["episode_id"]:
        raise ValueError("oracle episode mismatch")
    act({"type": "submit", "findings": {
        "episode_id": truth.episode_id,
        "findings": [{
            "type": issue.type, "affected_ids": list(issue.affected_ids),
            "claimed_amount_minor": issue.expected_amount_minor,
            "currency": issue.currency, "evidence_ids": list(issue.evidence_sets[0]),
            "explanation": "Trusted oracle supplies one complete accepted proof.",
        } for issue in truth.issues],
    }})
