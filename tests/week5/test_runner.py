from harnessy.evals.runner import TrialRecord, aggregate, compare, format_table, run_evals, run_trial
from harnessy.evals.tasks import EvalTask
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.tracer import load_trace
from harnessy.types import ToolCall

TASK = EvalTask(
    "w", "Write hi to out.txt", "easy", ({"type": "file_contains", "path": "out.txt", "text": "hi"},), {"seed.txt": "x"}, ("files",), 5
)


def scripted() -> ScriptedModel:
    return ScriptedModel(
        [
            tool_reply(ToolCall("c1", "write_file", {"path": "out.txt", "content": "hi"}), input_tokens=100, output_tokens=10),
            text_reply("done", 120, 5),
        ]
    )


def test_a_passing_trial_is_recorded_and_traced(tmp_path):
    r = run_trial(TASK, scripted(), 1, trace_dir=tmp_path)
    assert r.error is None, r.error
    assert (r.task_id, r.difficulty, r.trial, r.passed, r.stop_reason, r.steps) == ("w", "easy", 1, True, "end_turn", 2)
    assert (r.input_tokens, r.output_tokens, r.answer, r.error) == (220, 15, "done", None)
    assert r.checks == [{"type": "file_contains", "passed": True, "detail": "out.txt contains 'hi'"}]
    assert [e["kind"] for e in load_trace(r.trace)] == ["run_start", "model_call", "tool_result", "model_call", "stop"]


def test_the_workspace_is_seeded_and_the_task_tools_are_given():
    task = EvalTask("s", "p", "easy", ({"type": "file_exists", "path": "seed.txt"},), {"seed.txt": "x"}, ("files", "memory"), 3)
    model = ScriptedModel([text_reply("ok")])
    r = run_trial(task, model, 1)
    assert r.passed, r.error
    assert [t.name for t in model.calls[0].tools] == ["read_file", "write_file", "remember", "recall"]


def test_a_failing_check_fails_the_trial():
    model = ScriptedModel([text_reply("I did nothing")])
    r = run_trial(TASK, model, 1)
    assert r.error is None, r.error
    assert not r.passed and r.checks[0]["detail"] == "out.txt does not exist" and r.trace is None


def test_a_crash_becomes_a_failed_record():
    task = EvalTask("c", "p", "hard", ({"type": "file_exists", "path": "x"},), {"../evil.txt": "x"}, ("files",), 3)
    r = run_trial(task, ScriptedModel([]), 2)
    assert (r.passed, r.stop_reason, r.trial) == (False, "crash", 2)
    assert "escapes" in r.error, r.error


def test_run_evals_makes_a_model_per_trial_and_reports_each_record():
    seen = []
    records = run_evals([TASK], scripted, trials=2, on_record=seen.append)
    assert all(r.error is None for r in records), records[0].error
    assert [(r.task_id, r.trial, r.passed) for r in records] == [("w", 1, True), ("w", 2, True)]
    assert seen == records


def rec(task_id, difficulty, trial, passed, steps, inp, out):
    return TrialRecord(task_id, difficulty, trial, passed, [], "end_turn", steps, inp, out)


def test_aggregate():
    s = aggregate([rec("a", "easy", 1, True, 2, 100, 10), rec("a", "easy", 2, False, 4, 200, 20), rec("b", "hard", 1, True, 3, 300, 30)])
    assert s["tasks"]["a"] == {"difficulty": "easy", "trials": 2, "passed": 1, "pass_rate": 0.5, "mean_steps": 3.0, "mean_tokens": 165.0, "mean_cost_usd": 0.0}
    assert s["tasks"]["b"]["pass_rate"] == 1.0
    assert s["overall"] == {"trials": 3, "passed": 2, "pass_rate": 0.667, "mean_steps": 3.0, "mean_tokens": 220.0, "mean_cost_usd": 0.0}


def stats(rate, steps, tokens):
    return {"pass_rate": rate, "mean_steps": steps, "mean_tokens": tokens}


def test_compare():
    old = {"overall": stats(0.5, 3.0, 165.0), "tasks": {"a": stats(0.5, 3.0, 165.0), "gone": stats(1.0, 1.0, 10.0)}}
    new = {"overall": stats(1.0, 3.0, 145.0), "tasks": {"a": stats(1.0, 3.0, 145.0), "fresh": stats(1.0, 2.0, 50.0)}}
    assert compare(old, new) == [
        "overall: pass_rate 0.5 -> 1 (+0.5)",
        "overall: mean_tokens 165 -> 145 (-20)",
        "a: pass_rate 0.5 -> 1 (+0.5)",
        "a: mean_tokens 165 -> 145 (-20)",
        "fresh: new task",
        "gone: removed",
    ]
    assert compare(new, new) == []


def test_format_table_is_given():
    s = {
        "tasks": {"a": {"difficulty": "easy", "trials": 2, "passed": 1, "pass_rate": 0.5, "mean_steps": 3.0, "mean_tokens": 165.0}},
        "overall": {"trials": 2, "passed": 1, "pass_rate": 0.5, "mean_steps": 3.0, "mean_tokens": 165.0},
    }
    table = format_table(s)
    assert "OVERALL" in table and "50%" in table and "1/2" in table


def test_cost_is_recorded_and_averaged():
    records = [
        TrialRecord("a", "easy", 1, True, [], "end_turn", 1, 10, 1, cost_usd=0.02),
        TrialRecord("a", "easy", 2, True, [], "end_turn", 1, 10, 1, cost_usd=0.04),
    ]
    s = aggregate(records)
    assert s["tasks"]["a"]["mean_cost_usd"] == 0.03 and s["overall"]["mean_cost_usd"] == 0.03
    assert "$0.0300" in format_table(s)


def test_compare_skips_metrics_missing_from_old_results():
    old = {"overall": stats(0.5, 3.0, 165.0), "tasks": {}}
    new = {"overall": {**stats(0.5, 3.0, 165.0), "mean_cost_usd": 0.01}, "tasks": {}}
    assert compare(old, new) == []
