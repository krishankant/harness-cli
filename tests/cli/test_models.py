import json

import pytest

from harness_cli.config import ConfigError, Settings, load_settings
from harness_cli.models import ModelError, ModelSpec, Registry, build_model, guess_provider, key_status
from harnessy.cost import Price
from harnessy.models.anthropic import to_anthropic_messages
from harnessy.models.openai import from_openai_response, to_openai_messages
from harnessy.models.retry import RetryingModel
from harnessy.types import Message, ToolResult


def registry(models=None, **settings):
    return Registry.from_settings(Settings(models=models or {}, **settings))


def test_guess_provider():
    assert guess_provider("claude-opus-5", "openai") == "anthropic"
    assert guess_provider("gpt-5.5", "anthropic") == "openai"
    assert guess_provider("o4-mini", "anthropic") == "openai"
    assert guess_provider("qwen3-coder", "ollama") == "ollama"
    assert guess_provider("mystery", "anthropic") == "anthropic"


def test_builtins_work_without_config():
    reg = registry()
    opus = reg.resolve("opus")
    assert (opus.provider, opus.model, opus.price) == ("anthropic", "claude-opus-5", Price(5.0, 25.0))
    assert reg.resolve("gpt-5.5").provider == "openai"
    assert reg.resolve(None).model == "claude-opus-5"  # the default


def test_settings_entries_and_default(harness_home):
    reg = registry(
        {
            "groq": {"provider": "openai", "model": "llama-4-70b", "baseUrl": "https://api.groq.com/openai/v1", "apiKeyEnv": "GROQ_API_KEY", "price": {"input": 0.6, "output": 0.8}},
            "opus": {"model": "claude-opus-5", "maxTokens": 32000},
        },
        default_model="groq",
    )
    groq = reg.resolve(None)
    assert groq == ModelSpec("groq", "openai", "llama-4-70b", "https://api.groq.com/openai/v1", "GROQ_API_KEY", Price(0.6, 0.8), None, "settings")
    opus = reg.resolve("opus")
    assert opus.provider == "anthropic" and opus.max_tokens == 32000 and opus.price == Price(5.0, 25.0)  # price kept from the built-in table


def test_provider_prefix_and_bare_ids():
    reg = registry({"fast": {"provider": "openai", "model": "gpt-5.5-mini", "price": [0.5, 2]}})
    spec = reg.resolve("ollama:qwen3-coder")
    assert (spec.provider, spec.model, spec.price) == ("ollama", "qwen3-coder", None)
    assert reg.resolve("gpt-5.5-mini").alias == "fast"  # a bare id that a registry entry uses
    assert reg.resolve("claude-fable-5-1").provider == "anthropic"
    assert reg.resolve("openai:gpt-5.5-2026-04-23").price == Price(5.0, 30.0)  # dated id priced like its base


def test_default_from_provider_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.5")
    assert registry(provider="openai").resolve(None).model == "gpt-5.5"
    monkeypatch.delenv("OPENAI_MODEL")
    with pytest.raises(ModelError, match="OPENAI_MODEL"):
        registry(provider="openai").resolve(None)


def test_settings_model_is_the_default():
    assert registry(model="fable").resolve(None).model == "claude-fable-5-1"


def test_bad_entries():
    with pytest.raises(ConfigError, match="'x'.*model"):
        registry({"x": {"provider": "openai"}})
    with pytest.raises(ConfigError, match="provider"):
        registry({"x": {"provider": "gemini", "model": "g"}})
    with pytest.raises(ConfigError, match="price"):
        registry({"x": {"model": "m", "price": {"input": "cheap"}}})
    with pytest.raises(ModelError, match="unknown provider 'gemini'"):
        registry().resolve("gemini:pro")
    with pytest.raises(ModelError, match="Unknown model"):
        registry(default_model="nope").resolve(None)


def test_models_merge_user_and_project(workspace, harness_home):
    harness_home.mkdir(parents=True)
    (harness_home / "settings.json").write_text(json.dumps({"models": {"a": {"model": "gpt-5.5"}, "b": {"model": "claude-opus-5"}}}))
    (workspace / ".harness").mkdir()
    (workspace / ".harness" / "settings.json").write_text(json.dumps({"models": {"b": {"model": "claude-fable-5-1"}}, "defaultModel": "b"}))
    s = load_settings(workspace)
    reg = Registry.from_settings(s)
    assert reg.resolve("a").model == "gpt-5.5" and reg.resolve(None).model == "claude-fable-5-1"


def test_build_model_uses_endpoint_and_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gk-test")
    spec = ModelSpec("groq", "openai", "llama", "https://example.invalid/v1", "GROQ_API_KEY", None, None, "settings")
    model = build_model(spec)
    assert isinstance(model, RetryingModel) and model.name == "llama"
    client = model.model._client
    assert client.api_key == "gk-test" and str(client.base_url).startswith("https://example.invalid/v1")


def test_build_model_anthropic_options(monkeypatch):
    monkeypatch.setenv("MY_KEY", "sk-ant-test")
    spec = ModelSpec("proxy", "anthropic", "claude-opus-5", "https://proxy.invalid", "MY_KEY", None, 4096, "settings")
    inner = build_model(spec).model
    assert inner.max_tokens == 4096 and inner._client.api_key == "sk-ant-test"
    assert str(inner._client.base_url).startswith("https://proxy.invalid")


def test_build_model_missing_key_names_the_variable(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    spec = ModelSpec("groq", "openai", "llama", None, "GROQ_API_KEY", None, None, "settings")
    with pytest.raises(ModelError, match="GROQ_API_KEY"):
        build_model(spec)


def test_key_status(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert key_status(registry().resolve("gpt-5.5")) == "OPENAI_API_KEY set"
    assert key_status(registry().resolve("ollama:q")) == "no key needed"


def test_history_crosses_providers():
    """An OpenAI turn with a tool call, then the same history sent to Anthropic, and back."""
    openai_turn = from_openai_response(
        {
            "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}]}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
    ).message
    history = [Message("user", text="read a.py"), openai_turn, Message("user", tool_results=(ToolResult("call_1", "x = 1"),)), Message("assistant", text="It sets x."), Message("user", text="thanks")]
    anthropic = to_anthropic_messages(history)
    assert anthropic[1] == {"role": "assistant", "content": [{"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "a.py"}}]}
    assert anthropic[2]["content"][0]["tool_use_id"] == "call_1"
    back = to_openai_messages(history)
    assert back[1]["tool_calls"][0]["id"] == "call_1" and back[2] == {"role": "tool", "tool_call_id": "call_1", "content": "x = 1"}
