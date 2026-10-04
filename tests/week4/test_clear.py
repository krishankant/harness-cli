from harnessy.context import clear_old_results
from harnessy.types import Message, ToolCall, ToolResult

from .helpers import history


def results(msgs):
    return [m.tool_results[0].content for m in msgs if m.tool_results]


def test_old_large_results_are_cleared_and_the_newest_kept():
    h = history(5, result_size=1000)
    out = clear_old_results(h, keep_last=3, min_chars=500)
    assert results(out)[:2] == ["[cleared: read_file result, 1,000 chars]"] * 2
    assert results(out)[2:] == ["r" * 1000] * 3


def test_small_results_are_kept():
    h = history(5, result_size=100)
    assert clear_old_results(h, keep_last=1, min_chars=500) == h


def test_input_is_untouched_and_other_turns_are_the_same_objects():
    h = history(5, result_size=1000)
    before = list(h)
    out = clear_old_results(h, keep_last=0)
    assert h == before
    assert all(o is m for o, m in zip(out, h) if not m.tool_results)
    assert len(results(out)) == 5 and all(r.startswith("[cleared") for r in results(out))


def test_is_error_is_kept():
    h = [
        Message("user", text="t"),
        Message("assistant", tool_calls=(ToolCall("c1", "boom", {}),)),
        Message("user", tool_results=(ToolResult("c1", "e" * 600, is_error=True),)),
    ]
    [res] = clear_old_results(h, keep_last=0)[2].tool_results
    assert res.is_error and res.content == "[cleared: boom result, 600 chars]"
