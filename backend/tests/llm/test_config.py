from pydantic import SecretStr

from text2sql.config.settings import Settings
from text2sql.llm.config import LLMConfig


def test_from_settings_maps_roles_and_limits(settings: Settings) -> None:
    config = LLMConfig.from_settings(settings)
    assert config.models == {
        "main": "openai/gpt-5.4",
        "fast": "openai/gpt-5.4-mini",
        "local": "ollama_chat/qwen2.5-coder:7b",
    }
    assert config.timeout_s == 30.0
    assert config.retry.max_retries == 2


def test_each_key_only_goes_to_its_provider() -> None:
    config = LLMConfig(
        models={
            "main": "gpt-5.4",  # bare OpenAI name, provider inferred
            "fast": "anthropic/claude-haiku-4-5",
            "local": "ollama_chat/qwen2.5-coder:7b",
        },
        api_keys={"openai": SecretStr("sk-test"), "gemini": SecretStr("gm-test")},
        local_api_base="http://127.0.0.1:11434",
    )
    main, fast, local = (config.target(role) for role in ("main", "fast", "local"))
    assert main.api_key is not None
    assert main.api_key.get_secret_value() == "sk-test"
    assert fast.api_key is None  # LiteLLM falls back to the provider's own env var
    assert local.api_key is None
    assert local.api_base == "http://127.0.0.1:11434"
    assert main.api_base is None


def test_unknown_provider_does_not_crash_resolution() -> None:
    config = LLMConfig(models={"main": "nope", "fast": "nope", "local": "nope"})
    assert config.target("main").model == "nope"


def test_gemini_and_groq_keys_and_the_rate_limit_fallback(settings: Settings) -> None:
    custom = settings.model_copy(
        update={
            "llm_model_main": "gemini/gemini-2.5-flash",
            "llm_model_fast": "gemini/gemini-2.5-flash-lite",
            "llm_fallback_main": "groq/llama-3.3-70b-versatile",
            "llm_embedding_model": "gemini/gemini-embedding-001",
            "gemini_api_key": SecretStr("gm-test"),
            "groq_api_key": SecretStr("gq-test"),
        }
    )
    config = LLMConfig.from_settings(custom)
    main = config.target("main")
    assert main.api_key is not None
    assert main.api_key.get_secret_value() == "gm-test"
    fallback = config.fallback_target("main")
    assert fallback is not None
    assert fallback.model == "groq/llama-3.3-70b-versatile"
    assert fallback.api_key is not None
    assert fallback.api_key.get_secret_value() == "gq-test"
    assert config.fallback_target("fast") is None
    assert config.embedding_dimensions == 1536
    assert config.missing_keys() == []


def test_missing_keys_names_the_variable() -> None:
    config = LLMConfig(
        models={
            "main": "gemini/gemini-2.5-flash",
            "fast": "groq/llama-3.1-8b-instant",
            "local": "x",
        },
        embedding_model="gemini/gemini-embedding-001",
        api_keys={"gemini": SecretStr("gm-test")},
    )
    assert config.missing_keys() == ["groq/llama-3.1-8b-instant (set GROQ_API_KEY)"]


def test_local_models_need_no_key() -> None:
    config = LLMConfig(
        models={
            "main": "ollama_chat/qwen",
            "fast": "ollama_chat/qwen",
            "local": "ollama_chat/qwen",
        },
        embedding_model="ollama/nomic-embed-text",
    )
    assert config.missing_keys() == []
