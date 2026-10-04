import json

import pytest

from harnessy.tracer import Tracer, load_trace, to_jsonable
from harnessy.types import ToolCall


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        self.now += 0.25
        return self.now


def test_to_jsonable_is_given():
    assert to_jsonable((ToolCall("c1", "add", {"a": 1}),)) == [{"id": "c1", "name": "add", "arguments": {"a": 1}}]
    assert to_jsonable({1: None, "x": object}) == {"1": None, "x": str(object)}


def test_events_are_json_lines_with_run_id_seq_and_time(tmp_path):
    path = tmp_path / "traces" / "run.jsonl"
    tracer = Tracer(path, clock=Clock())
    tracer.event("run_start", task="t")
    tracer.event("model_call", step=0, tool_calls=(ToolCall("c1", "add", {"a": 1}),))
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(e["seq"], e["t"], e["kind"]) for e in lines] == [(0, 0.0, "run_start"), (1, 0.25, "model_call")]
    assert len({e["run_id"] for e in lines}) == 1 and len(lines[0]["run_id"]) == 8
    assert lines[0]["task"] == "t"
    assert lines[1]["tool_calls"] == [{"id": "c1", "name": "add", "arguments": {"a": 1}}]


def test_a_new_run_start_begins_a_new_run(tmp_path):
    path = tmp_path / "r.jsonl"
    tracer = Tracer(path, clock=Clock())
    tracer.event("run_start")
    first = tracer.run_id
    tracer.event("stop")
    tracer.event("run_start")
    tracer.event("stop")
    assert tracer.run_id != first
    events = load_trace(path)
    assert [e["seq"] for e in events] == [0, 1] and all(e["run_id"] == tracer.run_id for e in events)
    assert [e["kind"] for e in load_trace(path, run_id=first)] == ["run_start", "stop"]


def test_an_event_before_run_start_raises(tmp_path):
    Tracer(tmp_path / "ok.jsonl").event("run_start")  # fails plainly while event is still a stub
    with pytest.raises(RuntimeError, match="run_start"):
        Tracer(tmp_path / "r.jsonl").event("stop")


def test_load_trace_of_an_empty_file(tmp_path):
    (tmp_path / "e.jsonl").write_text("")
    assert load_trace(tmp_path / "e.jsonl") == []
