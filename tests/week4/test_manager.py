from harnessy.context import ContextManager, Summarize, estimate_tokens
from harnessy.models.scripted import ScriptedModel, text_reply
from harnessy.types import Message, ToolResult

from .helpers import history


def test_under_budget_returns_the_history_unchanged():
    h = history(5)
    assert ContextManager(budget_tokens=10**6).prepare(h) == h


def test_over_budget_compacts_to_the_target():
    h = history(10)
    cm = ContextManager(budget_tokens=1000, keep_last_results=100)
    view = cm.prepare(h)
    assert estimate_tokens(view) <= 500 and view[0] is h[0] and cm.cut is not None


def test_cut_is_sticky_until_the_budget_is_exceeded_again():
    h = history(10)
    cm = ContextManager(budget_tokens=1000, keep_last_results=100)
    view1 = cm.prepare(h)
    cut = cm.cut
    h2 = history(11)
    view2 = cm.prepare(h2)
    assert cm.cut == cut and view2[: len(view1)] == view1  # same prefix: the cache keeps hitting
    h3 = history(14)
    view3 = cm.prepare(h3)
    assert cm.cut > cut and estimate_tokens(view3) <= 1000


def test_old_results_are_cleared_before_measuring():
    h = history(6, size=10, result_size=2000)
    view = ContextManager(budget_tokens=10**6, keep_last_results=2).prepare(h)
    assert sum(r.content.startswith("[cleared") for m in view for r in m.tool_results) == 4


def test_new_run_resets():
    cm = ContextManager(budget_tokens=1000, keep_last_results=100)
    cm.prepare(history(10))
    assert cm.cut is not None
    other = [Message("user", text="A different task.")]
    assert cm.prepare(other) == other and cm.cut is None


def test_summarize_keeps_room_for_its_summary():
    model = ScriptedModel([text_reply("short summary")])
    cm = ContextManager(budget_tokens=1000, strategy=Summarize(model, reserve_tokens=100), keep_last_results=100)
    view = cm.prepare(history(10))
    assert estimate_tokens(view) <= 500 and "short summary" in view[0].text


def test_summarize_reads_the_original_results_not_the_cleared_stubs():
    h = history(10, result_size=600)
    h[2] = Message("user", tool_results=(ToolResult("c0", "a purple elephant " + "r" * 600),))
    model = ScriptedModel([text_reply("S")])
    cm = ContextManager(budget_tokens=1000, strategy=Summarize(model))  # default keep_last_results=3
    view = cm.prepare(h)
    assert "purple elephant" in model.calls[0].messages[0].text
    assert "purple elephant" not in "".join(r.content for m in view[1:] for r in m.tool_results)
