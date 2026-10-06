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


def test_openai_key_only_goes_to_openai_models() -> None:
    config = LLMConfig(
        models={
            "main": "gpt-5.4",  # bare OpenAI name, provider inferred
            "fast": "anthropic/claude-haiku-4-5",
            "local": "ollama_chat/qwen2.5-coder:7b",
        },
        openai_api_key=SecretStr("sk-test"),
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
