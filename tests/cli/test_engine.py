import threading

from harness_cli.engine import ApprovalRequest, Engine
from harness_cli.permissions import PermissionHook
from harness_cli.tools import SessionTodo
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.streaming import Done, TextDelta, ToolEnd, ToolStart
from harnessy.tools.schema import tool
from harnessy.types import ToolCall


@tool(tags={"private_data", "untrusted_input", "external_send"})
def run_shell(command: str) -> str:
    """Pretend shell.

    Args:
        command: The command.
    """
    return f"ran {command}"


def engine(responses, mode="default", **kw):
    model = ScriptedModel(responses)
    eng = Engine(model, [run_shell], system="sys", mode=mode, interactive=True, **kw)
    return eng, model


def drive(eng, prompt, history, answer=True):
    events = []
    for ev in eng.turn(prompt, history):
        events.append(ev)
        if isinstance(ev, ApprovalRequest):
            ev.reply.put(answer)
    return events


def test_two_turns_keep_history_and_totals():
    eng, model = engine([text_reply("hello", 10, 5), text_reply("again", 20, 7)])
    first = drive(eng, "hi", [])
    done = first[-1]
    assert isinstance(done, Done) and done.result.final_text == "hello"
    assert "".join(e.text for e in first if isinstance(e, TextDelta)) == "hello"
    drive(eng, "more", done.result.messages)
    assert [m.text for m in model.calls[-1].messages] == ["hi", "hello", "more"]
    assert eng.usage.input_tokens == 30 and eng.usage.output_tokens == 12
    assert model.calls[-1].system == "sys"


def test_approval_round_trip_yes():
    call = ToolCall("c1", "run_shell", {"command": "ls"})
    eng, _ = engine([tool_reply(call), text_reply("done")])
    events = drive(eng, "list", [], answer=True)
    kinds = [type(e).__name__ for e in events if not isinstance(e, TextDelta)]
    assert kinds == ["ApprovalRequest", "ToolStart", "ToolEnd", "Done"]
    end = next(e for e in events if isinstance(e, ToolEnd))
    assert end.result.content == "ran ls" and not end.result.is_error


def test_approval_no_gives_error_result_and_no_tool_start():
    call = ToolCall("c1", "run_shell", {"command": "rm -rf /"})
    eng, _ = engine([tool_reply(call), text_reply("ok")])
    events = drive(eng, "go", [], answer=False)
    assert not any(isinstance(e, ToolStart) for e in events)
    end = next(e for e in events if isinstance(e, ToolEnd))
    assert end.result.is_error and "declined" in end.result.content


def test_cancel_stops_the_turn():
    call = ToolCall("c1", "run_shell", {"command": "ls"})
    eng, _ = engine([tool_reply(call), text_reply("never")])
    events = []
    for ev in eng.turn("go", []):
        events.append(ev)
        if isinstance(ev, ApprovalRequest):
            eng.cancel()
            ev.reply.put(False)
    done = events[-1]
    assert isinstance(done, Done) and done.result.stop_reason == "blocked"
    assert "interrupted" in done.result.error


def test_headless_engine_declines_without_asking():
    call = ToolCall("c1", "run_shell", {"command": "ls"})
    model = ScriptedModel([tool_reply(call), text_reply("ok")])
    eng = Engine(model, [run_shell], system=None, mode="default", interactive=False)
    events = list(eng.turn("go", []))
    assert not any(isinstance(e, ApprovalRequest) for e in events)
    assert next(e for e in events if isinstance(e, ToolEnd)).result.is_error


def test_model_error_ends_cleanly():
    eng, _ = engine([RuntimeError("boom")])
    done = drive(eng, "x", [])[-1]
    assert done.result.stop_reason == "model_error" and "boom" in done.result.error


def test_turn_runs_off_the_main_thread():
    seen = []

    @tool
    def where() -> str:
        """Report the thread."""
        seen.append(threading.current_thread() is threading.main_thread())
        return "ok"

    model = ScriptedModel([tool_reply(ToolCall("c", "where", {})), text_reply("done")])
    eng = Engine(model, [where], system=None, mode="default", interactive=True)
    drive(eng, "go", [])  # "where" is not a built-in, so it counts as execute and asks
    assert seen == [False]


def test_recent_long_results_are_not_cleared():
    calls = [ToolCall(f"c{i}", "run_shell", {"command": "x" * 600}) for i in range(5)]
    eng, model = engine([*(tool_reply(c) for c in calls), text_reply("done")], mode="bypass")
    drive(eng, "go", [])
    last_view = model.calls[-1].messages
    contents = [r.content for m in last_view for r in m.tool_results]
    assert len(contents) == 5 and not any(c.startswith("[cleared") for c in contents)
