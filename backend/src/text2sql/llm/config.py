"""LLM configuration: which model serves each role, and how calls are bounded."""

from dataclasses import dataclass, field

from pydantic import SecretStr

from text2sql.config.settings import Settings
from text2sql.llm._litellm import litellm
from text2sql.llm.types import ModelRole, UsageRole


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


# Providers that are reached without an API key (local servers).
KEYLESS_PROVIDERS = frozenset({"ollama", "ollama_chat"})


def provider_of(model: str) -> str | None:
    """LiteLLM's provider name for ``model`` (``gemini``, ``groq``, ``openai``...)."""
    try:
        return str(litellm.get_llm_provider(model)[1])
    except Exception:  # noqa: BLE001 - unknown provider: let LiteLLM report it on call
        return None


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Resolved LLM settings. Build it with ``from_settings``; tests construct it directly."""

    models: dict[ModelRole, str]
    embedding_model: str = "openai/text-embedding-3-small"
    timeout_s: float = 30.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    api_keys: dict[str, SecretStr] = field(default_factory=dict)  # provider -> key
    local_api_base: str | None = None
    fallbacks: dict[ModelRole, str] = field(default_factory=dict)  # used on HTTP 429
    embedding_dimensions: int | None = 1536

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMConfig":
        """Map application settings onto the LLM configuration."""
        keys = {
            "openai": settings.openai_api_key,
            "gemini": settings.gemini_api_key,
            "groq": settings.groq_api_key,
        }
        fallbacks: dict[ModelRole, str | None] = {
            "main": settings.llm_fallback_main,
            "fast": settings.llm_fallback_fast,
        }
        return cls(
            models={
                "main": settings.llm_model_main,
                "fast": settings.llm_model_fast,
                "local": settings.llm_model_local,
            },
            embedding_model=settings.llm_embedding_model,
            timeout_s=settings.llm_timeout_s,
            retry=RetryPolicy(max_retries=settings.llm_max_retries),
            api_keys={k: v for k, v in keys.items() if v is not None and v.get_secret_value()},
            local_api_base=settings.llm_local_api_base,
            fallbacks={role: model for role, model in fallbacks.items() if model},
            embedding_dimensions=settings.llm_embedding_dimensions,
        )

    def _target_for(self, model: str, *, local: bool) -> ModelTarget:
        # Pass keys explicitly: Settings reads .env, LiteLLM would only see os.environ.
        provider = provider_of(model)
        return ModelTarget(
            model=model,
            api_key=self.api_keys.get(provider) if provider else None,
            api_base=self.local_api_base if local else None,
        )

    def target(self, role: UsageRole) -> ModelTarget:
        """Resolve a role (or ``"embedding"``) to its model and credentials."""
        model = self.embedding_model if role == "embedding" else self.models[role]
        return self._target_for(model, local=role == "local")

    def fallback_target(self, role: ModelRole) -> ModelTarget | None:
        """The role's rate-limit fallback, if one is configured."""
        model = self.fallbacks.get(role)
        return self._target_for(model, local=False) if model else None

    def missing_keys(self, roles: tuple[ModelRole, ...] = ("main", "fast")) -> list[str]:
        """Models in use (``roles``, their fallbacks, embeddings) whose provider has no key."""
        models = [self.models[r] for r in roles] + [
            self.fallbacks[r] for r in roles if r in self.fallbacks
        ]
        missing = []
        for model in [*models, self.embedding_model]:
            provider = provider_of(model)
            if provider not in KEYLESS_PROVIDERS and provider not in self.api_keys:
                missing.append(f"{model} (set {str(provider).upper()}_API_KEY)")
        return missing
