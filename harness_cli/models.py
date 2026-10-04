"""The model registry: name the models you use once, then pick any of them by name.

A model is a ModelSpec: which provider's API to speak (anthropic, openai, ollama), the model id,
and optionally an endpoint (baseUrl), the environment variable holding its key (apiKeyEnv), a
price and an output-token limit. Built-in entries cover the models in harnessy/cost.py;
settings.json "models" adds or overrides entries.

What you type after --model or /model can be:
  - an alias from the registry          opus, gpt, groq
  - provider:model                      openai:gpt-5.5, ollama:qwen3-coder
  - a bare model id                     claude-fable-5-1 (provider guessed from the name)"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, replace
from typing import Any

from harness_cli.config import PROVIDERS, ConfigError, Settings
from harnessy.cost import PRICES, Price, price_for
from harnessy.models.base import Model
from harnessy.models.retry import RetryingModel

OLLAMA_URL = "http://localhost:11434/v1"
DEFAULT_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "ollama": None}
DEFAULT_MODEL_ENV = {"anthropic": "ANTHROPIC_MODEL", "openai": "OPENAI_MODEL", "ollama": "OLLAMA_MODEL"}
FALLBACK_DEFAULT = {"anthropic": "claude-opus-5"}


class ModelError(ValueError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    alias: str
    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    price: Price | None = None
    max_tokens: int | None = None
    source: str = "built-in"  # built-in | settings | ad hoc

    @property
    def endpoint(self) -> str:
        if self.base_url:
            return self.base_url
        return OLLAMA_URL if self.provider == "ollama" else "default"

    @property
    def key_env(self) -> str | None:
        return self.api_key_env or DEFAULT_KEY_ENV[self.provider]

    def label(self) -> str:
        return self.model if self.alias == self.model else f"{self.alias} ({self.model})"


def guess_provider(model_id: str, fallback: str) -> str:
    if model_id.startswith("claude-"):
        return "anthropic"
    if re.match(r"(gpt-|chatgpt-|codex-|o\d)", model_id):
        return "openai"
    return fallback


def _builtins() -> dict[str, ModelSpec]:
    out = {key: ModelSpec(key, guess_provider(key, "openai"), key, price=price) for key, price in PRICES.items()}
    for alias, target in (("opus", "claude-opus-5"), ("fable", "claude-fable-5-1"), ("gpt", "gpt-5.5")):
        if target in out:
            out[alias] = replace(out[target], alias=alias)
    return out


def _price(value: Any, where: str) -> Price | None:
    if value is None:
        return None
    try:
        if isinstance(value, dict):
            return Price(float(value["input"]), float(value["output"]))
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return Price(float(value[0]), float(value[1]))
    except (KeyError, TypeError, ValueError):
        pass
    raise ConfigError(f"{where}: price must be {{\"input\": USD, \"output\": USD}} per million tokens, or [input, output]")


def _entry(alias: str, raw: Any, fallback_provider: str) -> ModelSpec:
    where = f"models.'{alias}'"
    if not isinstance(raw, dict) or not isinstance(raw.get("model"), str) or not raw["model"]:
        raise ConfigError(f"{where}: needs at least {{\"model\": \"<model id>\"}}")
    model_id = raw["model"]
    provider = raw.get("provider") or guess_provider(model_id, fallback_provider)
    if provider not in PROVIDERS:
        raise ConfigError(f"{where}: unknown provider {provider!r}; use one of {', '.join(PROVIDERS)} (any OpenAI-compatible API is \"openai\" with a baseUrl)")
    max_tokens = raw.get("maxTokens")
    if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens < 1):
        raise ConfigError(f"{where}: maxTokens must be a positive whole number")
    for key in ("baseUrl", "apiKeyEnv"):
        if raw.get(key) is not None and not isinstance(raw[key], str):
            raise ConfigError(f"{where}: {key} must be a string")
    price = _price(raw.get("price"), where) or price_for(model_id, PRICES)
    return ModelSpec(alias, provider, model_id, raw.get("baseUrl"), raw.get("apiKeyEnv"), price, max_tokens, "settings")


class Registry:
    def __init__(self, models: dict[str, ModelSpec], default: str | None, provider: str):
        self.models = models
        self.default = default
        self.provider = provider

    @classmethod
    def from_settings(cls, settings: Settings) -> Registry:
        models = _builtins()
        for alias, raw in (settings.models or {}).items():
            models[alias] = _entry(alias, raw, settings.provider)
        return cls(models, settings.model or settings.default_model, settings.provider)

    def resolve(self, name: str | None) -> ModelSpec:
        """The model to use for name (None = the configured default)."""
        name = (name or self.default or "").strip()
        if not name:
            return self._provider_default()
        if name in self.models:
            return self.models[name]
        provider, sep, model_id = name.partition(":")
        if sep and provider in PROVIDERS:
            return self._ad_hoc(provider, model_id)
        if sep and re.fullmatch(r"[a-z][a-z0-9-]*", provider) and "/" not in model_id:
            raise ModelError(f"unknown provider {provider!r} in '{name}': use one of {', '.join(PROVIDERS)}")
        same_id = [s for s in self.models.values() if s.model == name and s.source == "settings"]
        if same_id:
            return same_id[0]
        if re.fullmatch(r"[\w.:/-]+", name) and ("-" in name or "/" in name or ":" in name):
            return self._ad_hoc(guess_provider(name, self.provider), name)
        raise ModelError(f"Unknown model '{name}'. Use an alias from /models, provider:model, or a full model id.")

    def _ad_hoc(self, provider: str, model_id: str) -> ModelSpec:
        if not model_id:
            raise ModelError(f"'{provider}:' needs a model id after the colon")
        known = next((s for s in self.models.values() if s.model == model_id and s.provider == provider), None)
        if known:
            return known
        return ModelSpec(f"{provider}:{model_id}", provider, model_id, price=price_for(model_id, PRICES), source="ad hoc")

    def _provider_default(self) -> ModelSpec:
        env = DEFAULT_MODEL_ENV[self.provider]
        model_id = os.environ.get(env) or FALLBACK_DEFAULT.get(self.provider)
        if not model_id:
            raise ModelError(f"No model chosen for {self.provider}: pass --model, set defaultModel in settings, or set {env}.")
        return self._ad_hoc(self.provider, model_id) if model_id not in self.models else self.models[model_id]

    def prices(self) -> dict[str, Price]:
        """harnessy's price table plus every priced registry entry, keyed by model id."""
        table = dict(PRICES)
        table.update({s.model: s.price for s in self.models.values() if s.price is not None})
        return table


def key_status(spec: ModelSpec) -> str:
    env = spec.key_env
    if env is None:
        return "no key needed"
    if os.environ.get(env):
        return f"{env} set"
    if spec.provider == "anthropic" and env == "ANTHROPIC_API_KEY":
        return f"{env} not set (ok if you use `ant auth login`)"
    return f"{env} not set"


def build_model(spec: ModelSpec) -> Model:
    """A harnessy model for spec, wrapped in RetryingModel (week 7)."""
    key = os.environ.get(spec.key_env) if spec.key_env else None
    if spec.api_key_env and not key:
        raise ModelError(f"model '{spec.alias}' needs the environment variable {spec.api_key_env} (or put it in ~/.harness/.env)")
    try:
        if spec.provider == "anthropic":
            import anthropic

            from harnessy.models.anthropic import MAX_TOKENS, AnthropicModel

            client_args: dict[str, Any] = {}
            if key:
                client_args["api_key"] = key
            if spec.base_url:
                client_args["base_url"] = spec.base_url
            inner: Model = AnthropicModel(spec.model, client=anthropic.Anthropic(**client_args), max_tokens=spec.max_tokens or MAX_TOKENS)
        else:
            import openai

            from harnessy.models.openai import OpenAIModel

            if spec.provider == "ollama":
                key = key or "ollama"
            if not key:
                raise ModelError(f"model '{spec.alias}' needs {spec.key_env} (or put it in ~/.harness/.env)")
            client = openai.OpenAI(api_key=key, base_url=spec.base_url or (OLLAMA_URL if spec.provider == "ollama" else None))
            inner = OpenAIModel(spec.model, client=client)
    except ModelError:
        raise
    except Exception as e:  # SDK import or client construction problems
        raise ModelError(f"could not set up model '{spec.alias}' ({spec.provider}): {type(e).__name__}: {e}") from None

    def note(attempt: int, exc: BaseException, delay: float) -> None:
        print(f"[retry {attempt + 1}] {type(exc).__name__}; waiting {delay:.1f}s", file=sys.stderr)

    return RetryingModel(inner, on_retry=note)
