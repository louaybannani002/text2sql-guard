"""Typed progress events emitted while a question is answered (for streaming to clients)."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

type StageName = Literal["input_guard", "retrieve", "generate", "validate", "execute"]


class StageStarted(BaseModel):
    """A stage began. ``attempt`` counts SQL generation attempts (1 for one-off stages)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["stage_started"] = "stage_started"
    stage: StageName
    attempt: int


class StageDone(BaseModel):
    """A stage finished successfully."""

    model_config = ConfigDict(frozen=True)

    type: Literal["stage_done"] = "stage_done"
    stage: StageName
    attempt: int
    latency_ms: float


class StageError(BaseModel):
    """A stage failed. ``retryable`` means the pipeline may try again with a fixed query."""

    model_config = ConfigDict(frozen=True)

    type: Literal["error"] = "error"
    stage: StageName
    attempt: int
    latency_ms: float
    error: str = Field(description="Error kind, e.g. 'rejected:columns' or 'QueryTimeoutError'.")
    message: str = Field(description="Safe to show to the user.")
    retryable: bool


type StageEvent = Annotated[StageStarted | StageDone | StageError, Field(discriminator="type")]
type EventSink = Callable[[StageEvent], Awaitable[None]]
