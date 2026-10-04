import io
import json

from harness_cli import session as sessions
from harness_cli.main import main
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.types import ToolCall

from tests.cli.helpers import factory


class FakeStdin(io.StringIO):
    def __init__(self, text="", tty=False):
        super().__init__(text)
        self.tty = tty

    def isatty(self):
        return self.tty


def run(workspace, argv, responses, stdin=None):
    model = ScriptedModel(responses)
    out, err = io.StringIO(), io.StringIO()
    code = main(["-C", str(workspace), "--sandbox", "off", *argv], model_factory=factory(model), stdin=stdin or FakeStdin(tty=True), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue(), model


def test_text_output(workspace):
    code, out, err, _ = run(workspace, ["-p", "say hi"], [text_reply("hi there")])
    assert (code, out) == (0, "hi there\n")


def test_json_output(workspace):
    code, out, _, _ = run(workspace, ["-p", "x", "--output-format", "json"], [text_reply("answer", 7, 3)])
    data = json.loads(out)
    assert data["result"] == "answer" and data["stop_reason"] == "end_turn"
    assert data["usage"] == {"input_tokens": 7, "output_tokens": 3}
    assert sessions.load(workspace, data["session_id"]).messages[-1].text == "answer"


def test_stream_json_output(workspace):
    (workspace / "a.txt").write_text("content")
    call = ToolCall("c1", "read_file", {"path": "a.txt"})
    code, out, _, _ = run(workspace, ["-p", "read", "--output-format", "stream-json"], [tool_reply(call), text_reply("done")])
    kinds = [json.loads(line)["type"] for line in out.splitlines()]
    assert kinds == ["tool_start", "tool_end", "text", "done"]


def test_exit_code_on_limit(workspace):
    call = ToolCall("c1", "read_file", {"path": "missing"})
    code, _, err, _ = run(workspace, ["-p", "loop", "--max-steps", "1"], [tool_reply(call), text_reply("never")])
    assert code == 1 and "max_steps" in err


def test_prompt_from_stdin_and_combined(workspace):
    code, _, _, model = run(workspace, ["-p"], [text_reply("ok")], stdin=FakeStdin("diff text"))
    assert code == 0 and model.calls[0].messages[0].text == "diff text"
    code, _, _, model = run(workspace, ["-p", "review this"], [text_reply("ok")], stdin=FakeStdin("diff text"))
    assert model.calls[0].messages[0].text == "review this\n\n<stdin>\ndiff text\n</stdin>"


def test_headless_declines_edits_but_allowed_tools_permit(workspace):
    call = ToolCall("c1", "write_file", {"path": "x.txt", "content": "x"})
    run(workspace, ["-p", "write"], [tool_reply(call), text_reply("couldn't")])
    assert not (workspace / "x.txt").exists()
    run(workspace, ["-p", "write", "--allowed-tools", "write_file(x.txt)"], [tool_reply(call), text_reply("wrote")])
    assert (workspace / "x.txt").exists()


def test_plan_mode_flag(workspace):
    call = ToolCall("c1", "write_file", {"path": "x.txt", "content": "x"})
    run(workspace, ["-p", "write", "--permission-mode", "plan", "--allowed-tools", "write_file"], [tool_reply(call), text_reply("no")])
    assert not (workspace / "x.txt").exists()


def test_bad_settings_exit_2(workspace):
    (workspace / ".harness").mkdir()
    (workspace / ".harness" / "settings.json").write_text("{oops")
    code, _, err, _ = run(workspace, ["-p", "x"], [])
    assert code == 2 and "settings.json" in err


def test_missing_prompt_and_bad_rule(workspace):
    assert run(workspace, ["-p"], [])[0] == 2
    code, _, err, _ = run(workspace, ["-p", "x", "--allowed-tools", "run_shell(oops"], [])
    assert code == 2 and "bad permission rule" in err


def test_no_color_when_not_tty(workspace):
    code, out, err, _ = run(workspace, ["-p", "x"], [text_reply("plain")])
    assert "\033[" not in out + err


def test_continue_latest(workspace):
    run(workspace, ["-p", "my name is Ann"], [text_reply("Hi Ann")])
    code, out, _, model = run(workspace, ["-p", "-c", "what is my name?"], [text_reply("Ann")])
    assert [m.text for m in model.calls[0].messages] == ["my name is Ann", "Hi Ann", "what is my name?"]
    assert len(sessions.list_sessions(workspace)) == 1


def test_continue_with_nothing_fails(workspace):
    code, _, err, _ = run(workspace, ["-p", "-c", "x"], [])
    assert code == 2 and "no conversation" in err


def test_resume_without_id_lists(workspace):
    run(workspace, ["-p", "remember this"], [text_reply("ok")])
    code, out, _, _ = run(workspace, ["-r"], [])
    assert code == 0 and "remember this" in out


def test_max_cost_warns_for_unpriced_model(workspace):
    code, _, err, _ = run(workspace, ["-p", "x", "--max-cost", "1", "-m", "ollama:mystery"], [text_reply("ok")])
    assert code == 0 and "can't be enforced" in err


def settings_file(workspace, data):
    (workspace / ".harness").mkdir(exist_ok=True)
    (workspace / ".harness" / "settings.json").write_text(json.dumps(data))


def test_list_models(workspace):
    settings_file(workspace, {"models": {"groq": {"provider": "openai", "model": "llama-4", "baseUrl": "https://api.groq.com/openai/v1", "apiKeyEnv": "GROQ_KEY_FOR_TEST"}}})
    code, out, _, _ = run(workspace, ["--list-models"], [])
    assert code == 0
    groq = next(line for line in out.splitlines() if "groq" in line)
    assert "llama-4" in groq and "api.groq.com" in groq and "GROQ_KEY_FOR_TEST not set" in groq
    assert "claude-opus-5" in out and "gpt-5.5" in out


def test_settings_model_and_price_used(workspace):
    settings_file(workspace, {"defaultModel": "cheap", "models": {"cheap": {"provider": "openai", "model": "tiny-1", "price": [1, 2]}}})
    code, out, _, model = run(workspace, ["-p", "x", "--output-format", "json"], [text_reply("ok", 1_000_000, 1_000_000)])
    data = json.loads(out)
    assert model.name == "tiny-1" and data["cost_usd"] == 3.0


def test_cli_model_flag_and_errors(workspace):
    code, out, _, model = run(workspace, ["-p", "x", "-m", "openai:gpt-5.5"], [text_reply("ok")])
    assert code == 0 and model.name == "gpt-5.5"
    code, _, err, _ = run(workspace, ["-p", "x", "-m", "nope"], [])
    assert code == 2 and "Unknown model 'nope'" in err
    settings_file(workspace, {"models": {"bad": {"provider": "openai"}}})
    code, _, err, _ = run(workspace, ["-p", "x"], [])
    assert code == 2 and "models.'bad'" in err


def test_missing_key_exits_2(workspace, monkeypatch):
    from harness_cli.main import main

    monkeypatch.delenv("NO_SUCH_KEY_VAR", raising=False)
    settings_file(workspace, {"models": {"g": {"provider": "openai", "model": "m-1", "apiKeyEnv": "NO_SUCH_KEY_VAR"}}})
    out, err = io.StringIO(), io.StringIO()
    code = main(["-C", str(workspace), "-p", "x", "-m", "g"], stdin=FakeStdin(tty=True), stdout=out, stderr=err)
    assert code == 2 and "NO_SUCH_KEY_VAR" in err.getvalue()


def test_continue_with_another_model_records_it(workspace):
    run(workspace, ["-p", "hello"], [text_reply("hi")])
    run(workspace, ["-p", "-c", "-m", "gpt-5.5", "again"], [text_reply("hi again")])
    s = sessions.latest(workspace)
    assert (s.provider, s.model) == ("openai", "gpt-5.5") and len(s.messages) == 4


def test_headless_declines_remember_unless_allowed(workspace):
    call = ToolCall("c1", "remember", {"text": "fact"})
    run(workspace, ["-p", "x"], [tool_reply(call), text_reply("ok")])
    assert not (workspace / "HARNESS.md").exists()
    run(workspace, ["-p", "x", "--allowed-tools", "remember"], [tool_reply(call), text_reply("ok")])
    assert (workspace / "HARNESS.md").exists()
