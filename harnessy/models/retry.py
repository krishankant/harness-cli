"""Retries (week 7): wrap any model so rate limits, overloads and dropped connections are
retried with backoff instead of ending the run. One wrapper, every provider."""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Iterator

from harnessy.models.base import Model
from harnessy.types import Message, ModelResponse, ToolSpec

# --- Given -----------------------------------------------------------------------------


def retry_after(exc: BaseException) -> float | None:
    """The server's retry-after header in seconds, if the error carries one."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    value = headers.get("retry-after") if hasattr(headers, "get") else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# --- Week 7 exercise -------------------------------------------------------------------


def is_retryable(exc: BaseException) -> bool:
    """Is this error worth trying again?

    - An int status_code attribute (the SDKs' APIStatusError): retry 408, 429 and every 5xx
      (Anthropic's 529 means "overloaded"); any other status is the request's own fault: no.
    - No status: retry if any class in type(exc).__mro__ has "Timeout" or "Connection" in its
      name (the SDKs' APITimeoutError and APIConnectionError, Python's TimeoutError and
      ConnectionError). Anything else: no.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status in (408, 429) or status >= 500
    return any("Timeout" in cls.__name__ or "Connection" in cls.__name__ for cls in type(exc).__mro__)


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 8.0, rng: Callable[[], float] = random.random) -> float:
    """"Full jitter": a random wait between 0 and min(cap, base * 2 ** attempt). attempt counts
    from 0. The randomness keeps many clients from retrying in lockstep."""
    return rng() * min(cap, base * 2**attempt)


class RetryingModel:
    def __init__(
        self,
        model: Model,
        max_attempts: int = 4,
        base_delay: float = 0.5,
        max_delay: float = 8.0,
        sleep: Callable[[float], object] = time.sleep,
        rng: Callable[[], float] = random.random,
        on_retry: Callable[[int, BaseException, float], object] | None = None,
    ):
        self.model = model
        self.name = model.name
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.sleep = sleep
        self.rng = rng
        self.on_retry = on_retry

    # --- Given ---

    def _wait(self, attempt: int, exc: BaseException) -> None:
        header = retry_after(exc)
        delay = min(header, self.max_delay) if header is not None else backoff_delay(attempt, self.base_delay, self.max_delay, self.rng)
        if self.on_retry:
            self.on_retry(attempt, exc, delay)
        self.sleep(delay)

    def stream(self, messages: list[Message], tools: list[ToolSpec], system: str | None = None) -> Iterator[Any]:
        """Retry a stream only if it fails before the first chunk: text already shown can't be taken back."""
        inner = getattr(self.model, "stream", None)
        if inner is None:
            response = self.complete(messages, tools, system)
            if response.message.text:
                yield response.message.text  # a model that can't stream still sends its text
            yield response
            return
        for attempt in range(self.max_attempts):
            started = False
            try:
                for item in inner(messages, tools, system):
                    started = True
                    yield item
                return
            except Exception as e:
                if started or attempt == self.max_attempts - 1 or not is_retryable(e):
                    raise
                self._wait(attempt, e)

    # --- Week 7 exercise ---

    def complete(self, messages: list[Message], tools: list[ToolSpec], system: str | None = None) -> ModelResponse:
        """Call self.model.complete. If it raises, and the error is_retryable, and this was not
        the last of self.max_attempts attempts: self._wait(attempt, exc) (given: it picks the
        delay, calls on_retry and sleeps), then try again. Otherwise re-raise the error."""
        for attempt in range(self.max_attempts):
            try:
                return self.model.complete(messages, tools, system)
            except Exception as e:
                if attempt == self.max_attempts - 1 or not is_retryable(e):
                    raise
                self._wait(attempt, e)
        raise AssertionError("unreachable")
