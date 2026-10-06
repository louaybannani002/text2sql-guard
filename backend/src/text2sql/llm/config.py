"""LLM configuration: which model serves each role, and how calls are bounded."""

from dataclasses import dataclass, field

from pydantic import SecretStr

from text2sql.config.settings import Settings
from text2sql.llm._litellm import litellm
from text2sql.llm.types import ModelRole


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff with full jitter: delay = U(0, min(cap, base * 2**retry))."""

    max_retries: int = 2
    base_delay_s: float = 1.0
    max_delay_s: float = 8.0


@dataclass(frozen=True, slots=True)
class ModelTarget:
    """Everything LiteLLM needs to reach one concrete model."""

    model: str
    api_key: SecretStr | None
    api_base: str | None


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Resolved LLM settings. Build it with ``from_settings``; tests construct it directly."""

    models: dict[ModelRole, str]
    timeout_s: float = 30.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    openai_api_key: SecretStr | None = None
    local_api_base: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMConfig":
        """Map application settings onto the LLM configuration."""
        return cls(
            models={
                "main": settings.llm_model_main,
                "fast": settings.llm_model_fast,
                "local": settings.llm_model_local,
            },
            timeout_s=settings.llm_timeout_s,
            retry=RetryPolicy(max_retries=settings.llm_max_retries),
            openai_api_key=settings.openai_api_key,
            local_api_base=settings.llm_local_api_base,
        )

    def target(self, role: ModelRole) -> ModelTarget:
        """Resolve a role to its model and credentials."""
        model = self.models[role]
        try:
            provider = litellm.get_llm_provider(model)[1]
        except Exception:  # noqa: BLE001 - unknown provider: let LiteLLM report it on call
            provider = None
        return ModelTarget(
            model=model,
            # Pass keys explicitly: Settings reads .env, LiteLLM would only see os.environ.
            api_key=self.openai_api_key if provider == "openai" else None,
            api_base=self.local_api_base if role == "local" else None,
        )
