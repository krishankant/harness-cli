from harnessy.tracer import format_timeline

RUN = "ab12cd34"
EVENTS = [
    {"run_id": RUN, "seq": 0, "t": 0.0, "kind": "run_start", "task": "What is 2+2?", "model": "scripted", "system": None, "tools": ["add"]},
    {
        "run_id": RUN, "seq": 1, "t": 0.5, "kind": "model_call", "step": 0, "stop_reason": "tool_use",
        "input_tokens": 100, "output_tokens": 20, "text": "",
        "tool_calls": [{"id": "c1", "name": "add", "arguments": {"a": 2, "b": 2}}],
    },
    {
        "run_id": RUN, "seq": 2, "t": 0.75, "kind": "tool_result", "step": 0, "name": "add",
        "arguments": {"a": 2, "b": 2}, "tool_call_id": "c1", "content": "4", "is_error": False,
    },
    {
        "run_id": RUN, "seq": 3, "t": 1.5, "kind": "model_call", "step": 1, "stop_reason": "end_turn",
        "input_tokens": 130, "output_tokens": 5, "text": "4", "tool_calls": [],
    },
    {
        "run_id": RUN, "seq": 4, "t": 1.5, "kind": "stop", "stop_reason": "end_turn", "steps": 2,
        "input_tokens": 230, "output_tokens": 25, "error": None, "final_text": "4",
    },
]


def test_a_run_as_a_timeline():
    assert format_timeline(EVENTS).splitlines() == [
        "run ab12cd34  model=scripted  tools=add",
        "task: What is 2+2?",
        '[   0.50s + 0.50s] step 0 model tool_use in=100 out=20 add({"a": 2, "b": 2})',
        "[   0.75s + 0.25s]   add -> 4",
        "[   1.50s + 0.75s] step 1 model end_turn in=130 out=5 '4'",
        "[   1.50s] stop end_turn steps=2 tokens=255",
    ]


def test_errors_and_long_text_are_shortened():
    events = [
        {"run_id": RUN, "seq": 0, "t": 0.0, "kind": "tool_result", "step": 0, "name": "read_file", "content": "x" * 100, "is_error": True},
        {"run_id": RUN, "seq": 1, "t": 2.0, "kind": "stop", "stop_reason": "model_error", "steps": 1,
         "input_tokens": 1, "output_tokens": 1, "error": "RuntimeError: 503"},
    ]
    assert format_timeline(events).splitlines() == [
        "[   0.00s + 0.00s]   read_file -> ERROR " + "x" * 57 + "...",
        "[   2.00s] stop model_error steps=1 tokens=2 error=RuntimeError: 503",
    ]


def test_unknown_kinds_are_shown_as_json():
    events = [{"run_id": RUN, "seq": 0, "t": 1.0, "kind": "approval", "tool": "write_file", "ok": True}]
    assert format_timeline(events) == '[   1.00s] approval {"tool": "write_file", "ok": true}'
