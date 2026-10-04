import pytest

from harnessy.models.retry import RetryingModel, backoff_delay, is_retryable, retry_after
from harnessy.models.scripted import ScriptedModel, text_reply


class StatusError(Exception):
    def __init__(self, status, retry_after=None):
        super().__init__(f"HTTP {status}")
        self.status_code = status
        headers = {} if retry_after is None else {"retry-after": str(retry_after)}
        self.response = type("Response", (), {"headers": headers})()


class APIConnectionError(Exception):
    pass


def test_what_is_retryable():
    assert [is_retryable(StatusError(s)) for s in (408, 429, 500, 503, 529)] == [True] * 5
    assert [is_retryable(StatusError(s)) for s in (400, 401, 404, 422)] == [False] * 4
    assert is_retryable(APIConnectionError()) and is_retryable(TimeoutError())
    assert not is_retryable(ValueError("bad input"))


def test_retry_after_is_given():
    assert retry_after(StatusError(429, retry_after=3)) == 3.0
    assert retry_after(StatusError(429)) is None and retry_after(ValueError()) is None


def test_backoff_is_full_jitter_and_capped():
    assert backoff_delay(0, rng=lambda: 1.0) == 0.5
    assert backoff_delay(3, rng=lambda: 1.0) == 4.0
    assert backoff_delay(10, rng=lambda: 1.0) == 8.0
    assert backoff_delay(3, rng=lambda: 0.25) == 1.0


def test_retries_then_succeeds():
    sleeps, seen = [], []
    model = RetryingModel(
        ScriptedModel([StatusError(429), StatusError(503), text_reply("ok")]),
        sleep=sleeps.append, rng=lambda: 1.0, on_retry=lambda attempt, exc, delay: seen.append((attempt, str(exc))),
    )
    assert model.name == "scripted"
    assert model.complete([], []).message.text == "ok"
    assert sleeps == [0.5, 1.0] and seen == [(0, "HTTP 429"), (1, "HTTP 503")]


def test_retry_after_header_wins_but_is_capped():
    sleeps = []
    model = RetryingModel(ScriptedModel([StatusError(429, retry_after=2), StatusError(429, retry_after=60), text_reply("ok")]),
                          sleep=sleeps.append, max_delay=8.0)
    model.complete([], [])
    assert sleeps == [2.0, 8.0]


def test_gives_up_after_max_attempts_and_reraises():
    sleeps = []
    model = RetryingModel(ScriptedModel([StatusError(500)] * 3), max_attempts=3, sleep=sleeps.append, rng=lambda: 0.0)
    with pytest.raises(StatusError):
        model.complete([], [])
    assert len(sleeps) == 2


def test_non_retryable_errors_raise_at_once():
    RetryingModel(ScriptedModel([text_reply("ok")]), sleep=lambda s: None).complete([], [])  # fails plainly while a stub
    sleeps = []
    with pytest.raises(StatusError):
        RetryingModel(ScriptedModel([StatusError(400), text_reply("ok")]), sleep=sleeps.append).complete([], [])
    assert sleeps == []


class FlakyStream:
    name = "flaky"

    def __init__(self, fail_after_first_chunk):
        self.calls = 0
        self.fail_after_first_chunk = fail_after_first_chunk

    def complete(self, messages, tools, system=None):
        raise AssertionError("not used")

    def stream(self, messages, tools, system=None):
        self.calls += 1
        if self.calls == 1:
            if self.fail_after_first_chunk:
                yield "partial "
            raise StatusError(503)
        yield "fine"
        yield text_reply("fine")


def test_stream_retries_only_before_the_first_chunk():
    inner = FlakyStream(fail_after_first_chunk=False)
    items = list(RetryingModel(inner, sleep=lambda s: None).stream([], []))
    assert items[0] == "fine" and inner.calls == 2
    inner = FlakyStream(fail_after_first_chunk=True)
    got = []
    with pytest.raises(StatusError):
        for item in RetryingModel(inner, sleep=lambda s: None).stream([], []):
            got.append(item)
    assert got == ["partial "] and inner.calls == 1
