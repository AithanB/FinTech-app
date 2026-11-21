"""Fail-closed allowlists for the trusted-to-policy JSON channel."""

from typing import Annotated

from pydantic import Field, ValidationError

from .schemas import (
    CalculatorReply, DocumentReply, ErrorReply, ListReply, Manifest, Policy,
    RecordReply, StrictModel, SubmitReply,
)


class InitialObservation(StrictModel):
    task: str
    manifest: Manifest
    policy: Policy
    remaining_steps: Annotated[int, Field(ge=0, le=100)]


ERRORS = frozenset({
    "EPISODE_CLOSED", "INVALID_ACTION", "INVALID_SUBMISSION", "INVALID_CURSOR",
    "UNKNOWN_ID", "CALCULATOR_ERROR", "TIME_LIMIT", "POLICY_ERROR",
})
REPLIES = {
    "list_records": ListReply, "get_record": RecordReply,
    "get_document": DocumentReply, "calculator": CalculatorReply,
    "submit": SubmitReply,
}


def initial_message(observation):
    return {"observation": InitialObservation.model_validate(observation).model_dump(mode="json"), "info": {}}


def transition_message(action, transition, *, closed):
    observation, reward, terminated, truncated, info = transition
    if info != {} or type(terminated) is not bool or type(truncated) is not bool:
        raise ValueError("unsafe transition")
    if "error" in observation:
        model = ErrorReply
        if observation["error"] not in ERRORS:
            raise ValueError("unsafe error")
    else:
        model = REPLIES.get(action.get("type")) if isinstance(action, dict) else None
        if model is None:
            raise ValueError("unsafe result")
    try:
        public = model.model_validate(observation).model_dump(mode="json")
    except ValidationError as exc:
        raise ValueError("unsafe observation") from exc
    return {
        "observation": public, "reward": 0.0 if closed else reward,
        "terminated": terminated, "truncated": truncated, "info": {},
    }
