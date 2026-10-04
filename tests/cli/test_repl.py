from harness_cli import session as sessions
from harness_cli.repl import run_repl
from harnessy.models.scripted import text_reply, tool_reply
from harnessy.types import ToolCall

from tests.cli.helpers import make_app


def test_chat_two_prompts_and_commands(workspace):
    app, model, out, feeder = make_app(
        workspace,
        [text_reply("Hello!", 100, 10), text_reply("Still here.", 200, 20)],
        lines=["hi", "/cost", "are you there?", "/mode plan", "/mode", "/exit"],
    )
    assert run_repl(app, input_fn=feeder) == 0
    text = out.getvalue()
    assert "Hello!" in text and "Still here." in text
    assert "tokens in 100" in text
    assert "Permission mode is now plan" in text
    assert [m.text for m in model.calls[-1].messages] == ["hi", "Hello!", "are you there?"]
    saved = sessions.latest(workspace)
    assert saved.id == app.session.id and len(saved.messages) == 4


def test_approval_prompt_yes_runs_the_edit(workspace):
    (workspace / "a.txt").write_text("old")
    call = ToolCall("c1", "edit_file", {"path": "a.txt", "old": "old", "new": "new"})
    app, _, out, _ = make_app(workspace, [tool_reply(call), text_reply("Edited.")], lines=["change it", "y"])
    run_repl(app, input_fn=app.renderer.input_fn)
    assert (workspace / "a.txt").read_text() == "new"
    assert "Allow edit_file" in out.getvalue() and "- old" in out.getvalue() and "+ new" in out.getvalue()


def test_prompt_eof_is_no(workspace):
    (workspace / "a.txt").write_text("old")
    call = ToolCall("c1", "write_file", {"path": "a.txt", "content": "x"})
    app, model, out, _ = make_app(workspace, [tool_reply(call), text_reply("ok, I won't.")], lines=["overwrite it"])
    assert run_repl(app, input_fn=app.renderer.input_fn) == 0  # EOF at the approval prompt, then EOF at the next prompt
    assert (workspace / "a.txt").read_text() == "old"
    results = model.calls[-1].messages[-1].tool_results
    assert results[0].is_error and "declined" in results[0].content


def test_always_answer_skips_later_prompts(workspace):
    calls = [ToolCall(f"c{i}", "write_file", {"path": f"f{i}.txt", "content": "x"}) for i in range(2)]
    app, _, out, _ = make_app(workspace, [tool_reply(calls[0]), tool_reply(calls[1]), text_reply("done")], lines=["make files", "a"])
    run_repl(app, input_fn=app.renderer.input_fn)
    assert (workspace / "f0.txt").exists() and (workspace / "f1.txt").exists()
    assert out.getvalue().count("Allow write_file") == 1


def test_shell_escape_and_unknown_command(workspace):
    app, model, out, feeder = make_app(workspace, [], lines=["!echo from-shell", "/nope"])
    run_repl(app, input_fn=feeder)
    assert "from-shell" in out.getvalue() and "[exit code 0]" in out.getvalue()
    assert "Unknown command /nope" in out.getvalue()
    assert model.calls == []


def test_custom_command_and_mention(workspace):
    (workspace / ".harness" / "commands").mkdir(parents=True)
    (workspace / ".harness" / "commands" / "explain.md").write_text("Explain $ARGUMENTS")
    (workspace / "m.py").write_text("x = 1")
    app, model, out, feeder = make_app(workspace, [text_reply("It sets x.")], lines=["/explain @m.py"])
    run_repl(app, input_fn=feeder)
    sent = model.calls[0].messages[-1].text
    assert sent.startswith("Explain @m.py") and "x = 1" in sent


def test_clear_starts_new_session_and_resume_goes_back(workspace):
    app, model, out, feeder = make_app(workspace, [text_reply("one"), text_reply("two")], lines=["first", "/clear", "second"])
    first_id = None
    run_repl(app, input_fn=feeder, first_prompt=None)
    ids = [i.id for i in sessions.list_sessions(workspace)]
    assert len(ids) == 2
    assert [m.text for m in model.calls[-1].messages] == ["second"]
    app2, _, out2, feeder2 = make_app(workspace, [], lines=[f"/resume {ids[-1]}", "/sessions"])
    run_repl(app2, input_fn=feeder2)
    assert app2.session.messages[0].text == "first"
    del first_id


def test_compact_replaces_history(workspace):
    app, model, out, feeder = make_app(
        workspace,
        [text_reply("A long answer."), text_reply("Summary: user asked X."), text_reply("Continuing.")],
        lines=["question", "/compact", "next"],
    )
    run_repl(app, input_fn=feeder)
    sent = [m.text for m in model.calls[-1].messages]
    assert sent[0].endswith("Summary: user asked X.") and sent[-1] == "next" and len(sent) == 3


def test_model_switch(workspace):
    app, model, out, feeder = make_app(workspace, [], lines=["/model other-model", "/model"])
    run_repl(app, input_fn=feeder)
    assert app.model.name == "other-model" and "other-model (anthropic)" in out.getvalue()


def test_plan_mode_blocks_writes(workspace):
    call = ToolCall("c1", "write_file", {"path": "x.txt", "content": "x"})
    app, model, out, feeder = make_app(workspace, [tool_reply(call), text_reply("I can't in plan mode.")], lines=["write it"], permission_mode="plan")
    run_repl(app, input_fn=feeder)
    assert not (workspace / "x.txt").exists()
    assert "plan mode" in model.calls[-1].messages[-1].tool_results[0].content
