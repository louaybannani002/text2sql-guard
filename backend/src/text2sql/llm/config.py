"""LLM configuration: which model serves each role, and how calls are bounded."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import SecretStr

from text2sql.config.settings import Settings
from text2sql.llm._litellm import litellm
from text2sql.llm.types import ModelRole, UsageRole

if TYPE_CHECKING:
    from aiohttp import ClientSession

FAKE_PREFIX = "fake/"


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
    # One aiohttp session for every completion (connection reuse); set by the API at startup.
    http_session: "ClientSession | None" = field(default=None, compare=False, repr=False)
    # Fake LLM mode (load tests): None = real providers; otherwise the delay scale (0 = none).
    fake_delay_scale: float | None = None

    @property
    def fake(self) -> bool:
        """Answers come from recordings, not from providers."""
        return self.fake_delay_scale is not None

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
        # In fake mode every name gets a "fake/" prefix: cache keys (which include the main
        # model) can then never mix fake answers with real ones.
        prefix = FAKE_PREFIX if settings.llm_fake_mode else ""
        return cls(
            models={
                "main": prefix + settings.llm_model_main,
                "fast": prefix + settings.llm_model_fast,
                "local": prefix + settings.llm_model_local,
            },
            embedding_model=prefix + settings.llm_embedding_model,
            timeout_s=settings.llm_timeout_s,
            retry=RetryPolicy(max_retries=settings.llm_max_retries),
            api_keys={k: v for k, v in keys.items() if v is not None and v.get_secret_value()},
            local_api_base=settings.llm_local_api_base,
            fallbacks={}
            if settings.llm_fake_mode
            else {role: model for role, model in fallbacks.items() if model},
            embedding_dimensions=settings.llm_embedding_dimensions,
            fake_delay_scale=settings.llm_fake_delay_scale if settings.llm_fake_mode else None,
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
        if self.fake:
            return []
        models = [self.models[r] for r in roles] + [
            self.fallbacks[r] for r in roles if r in self.fallbacks
        ]
        missing = []
        for model in [*models, self.embedding_model]:
            provider = provider_of(model)
            if provider not in KEYLESS_PROVIDERS and provider not in self.api_keys:
                missing.append(f"{model} (set {str(provider).upper()}_API_KEY)")
        return missing
