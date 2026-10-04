import pytest

from harnessy.context import SUMMARY_PROMPT, Summarize, render_transcript
from harnessy.models.scripted import ScriptedModel, text_reply
from harnessy.types import Usage

from .helpers import history


def test_first_view_summarizes_the_dropped_span():
    h = history(6)
    model = ScriptedModel([text_reply("S1", input_tokens=50, output_tokens=7)])
    s = Summarize(model)
    view = s.view(h, 5)
    [call] = model.calls
    assert call.system == SUMMARY_PROMPT and call.tools == []
    assert render_transcript(h[1:5]) in call.messages[0].text
    assert view[0].text == h[0].text + "\n\n[Summary of earlier work]\nS1"
    assert view[1:] == h[5:]
    assert s.usage == Usage(50, 7)


def test_the_same_cut_makes_no_new_call():
    h = history(6)
    model = ScriptedModel([text_reply("S1")])
    s = Summarize(model)
    assert s.view(h, 5) == s.view(h + [h[-2], h[-1]], 5)[: len(h) - 4]
    assert len(model.calls) == 1


def test_a_later_cut_is_incremental():
    h = history(6)
    model = ScriptedModel([text_reply("S1"), text_reply("S2")])
    s = Summarize(model)
    s.view(h, 5)
    view = s.view(h, 9)
    text = model.calls[1].messages[0].text
    assert "S1" in text and render_transcript(h[5:9]) in text and render_transcript(h[1:5]) not in text
    assert view[0].text.endswith("S2")


def test_summary_is_capped_to_the_reserve():
    model = ScriptedModel([text_reply("w" * 1000)])
    view = Summarize(model, reserve_tokens=10).view(history(6), 5)
    assert view[0].text.endswith("\n" + "w" * 40)


def test_cut_one_drops_nothing():
    h = history(3)
    model = ScriptedModel([])
    assert Summarize(model).view(h, 1) == h and model.calls == []


def test_reset_forgets_the_summary():
    h = history(6)
    model = ScriptedModel([text_reply("S1"), text_reply("S1 again")])
    s = Summarize(model)
    s.view(h, 5)
    s.reset()
    s.view(h, 5)
    assert len(model.calls) == 2 and "Summary so far" not in model.calls[1].messages[0].text


def test_a_refused_or_failed_summary_raises_and_is_not_kept():
    h = history(6)
    Summarize(ScriptedModel([text_reply("S0")])).view(h, 5)  # fails plainly while view is still a stub
    s = Summarize(ScriptedModel([text_reply("", stop_reason="refused"), text_reply("S1")]))
    with pytest.raises(RuntimeError, match="refused"):
        s.view(h, 5)
    assert s.view(h, 5)[0].text.endswith("S1")
