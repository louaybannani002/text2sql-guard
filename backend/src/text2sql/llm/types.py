"""Public data types of the LLM layer."""

from dataclasses import dataclass
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

type ModelRole = Literal["main", "fast", "local"]
type UsageRole = ModelRole | Literal["embedding"]


class Message(TypedDict):
    """One chat message, in the OpenAI / LiteLLM format."""

    role: Literal["system", "user", "assistant"]
    content: str


class Usage(BaseModel):
    """What one ``generate_structured`` call consumed."""

    model_config = ConfigDict(frozen=True)

    role: UsageRole
    model: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0, description="Wall time including retries and backoff.")
    cost_usd: float | None = Field(
        ge=0, description="From LiteLLM's price map; None when the model has no known price."
    )
    attempts: int = Field(ge=1, description="1 + number of retries that were needed.")


@dataclass(frozen=True, slots=True)
class LLMResult[T: BaseModel]:
    """A validated structured output together with its usage."""

    output: T
    usage: Usage
