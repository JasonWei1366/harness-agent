"""HTTP API request models for the web boot module."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StreamingBehavior = Literal["steer", "follow_up"]
SessionAction = Literal["state", "messages", "prompt", "command", "terminal", "abort"]


class SessionsRequest(BaseModel):
    """List this user's sessions, open one they own, or create one."""

    model_config = ConfigDict(populate_by_name=True)

    user_id: str | None = Field(default=None, alias="userId")
    session_id: str | None = Field(default=None, alias="sessionId")
    model: str | None = None
    create: bool = False


class SessionRequest(BaseModel):
    """One JSON action on a session this user already owns."""

    model_config = ConfigDict(populate_by_name=True)

    user_id: str | None = Field(default=None, alias="userId")
    action: SessionAction
    session_id: str | None = Field(default=None, alias="sessionId")
    model: str | None = Field(default=None, examples=["gpt-4.1"])
    message: str | None = Field(default=None, examples=["explain this repository"])
    streaming_behavior: Literal["steer", "follow_up"] | None = Field(
        default=None,
        alias="streamingBehavior",
        description="Required when a turn is already running. JSON value followUp or steer.",
    )
    text: str | None = Field(default=None, examples=["/session"])
    command: str | None = Field(default=None, examples=["pwd"])
    add_to_context: bool = Field(default=True, alias="addToContext")

    @field_validator("streaming_behavior", mode="before")
    @classmethod
    def normalize_streaming_behavior(cls, value: object) -> object:
        if value == "followUp":
            return "follow_up"
        return value


class EventsRequest(BaseModel):
    """Subscribe to one owned session. The response is an event stream."""

    model_config = ConfigDict(populate_by_name=True)

    user_id: str | None = Field(default=None, alias="userId")
    session_id: str | None = Field(default=None, alias="sessionId")
