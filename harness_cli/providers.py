"""Turn a provider name and model name into a harnessy model, with retries (week 7)."""

from __future__ import annotations

import os
import sys

from harnessy.models.base import Model
from harnessy.models.retry import RetryingModel

OLLAMA_URL = "http://localhost:11434/v1"


class ProviderError(RuntimeError):
    pass


def make_model(provider: str, model: str | None = None) -> Model:
    try:
        if provider == "anthropic":
            from harnessy.models.anthropic import AnthropicModel

            inner: Model = AnthropicModel(model)
        elif provider == "openai":
            from harnessy.models.openai import OpenAIModel

            inner = OpenAIModel(model)
        elif provider == "ollama":
            from harnessy.models.openai import OpenAIModel

            os.environ.setdefault("OPENAI_API_KEY", "ollama")
            inner = OpenAIModel(model or os.environ.get("OLLAMA_MODEL"), base_url=os.environ.get("OLLAMA_BASE_URL", OLLAMA_URL))
        else:
            raise ProviderError(f"unknown provider {provider!r}")
    except ProviderError:
        raise
    except Exception as e:  # missing key, missing model name, SDK import problems
        raise ProviderError(f"could not set up {provider}: {e}") from None

    def note(attempt: int, exc: BaseException, delay: float) -> None:
        print(f"[retry {attempt + 1}] {type(exc).__name__}; waiting {delay:.1f}s", file=sys.stderr)

    return RetryingModel(inner, on_retry=note)
