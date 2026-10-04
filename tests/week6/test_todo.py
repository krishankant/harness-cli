import pytest

from harnessy.todo import TodoList
from harnessy.types import Message, ToolResult


def test_add_complete_and_list():
    todo = TodoList()
    assert todo.apply("add", "read the notes") == "Added #1: read the notes"
    todo.apply("add", "write the summary")
    assert todo.apply("complete", id=1) == "Completed #1: read the notes"
    assert todo.apply("list") == todo.render() == "Todo list:\n[x] #1 read the notes\n[ ] #2 write the summary"


def test_empty_list():
    assert TodoList().render() == "Todo list: (empty)"


def test_problems_raise():
    todo = TodoList()
    todo.apply("add", "x")  # fails plainly while still a stub
    for args in [("add", None, None), ("complete", None, 9), ("delete", None, None)]:
        with pytest.raises(ValueError):
            todo.apply(*args)


def test_before_model_adds_the_list_to_the_last_message_only_in_the_view():
    todo = TodoList()
    view = [Message("user", text="task")]
    assert todo.before_model(view) is None
    todo.apply("add", "x")
    out = todo.before_model(view)
    assert out[-1].text == "task\n\nTodo list:\n[ ] #1 x" and view[0].text == "task"
    results = [Message("user", tool_results=(ToolResult("c1", "ok"),))]
    changed = todo.before_model(results)[-1]
    assert changed.text == "Todo list:\n[ ] #1 x" and changed.tool_results == results[0].tool_results


def test_a_new_run_starts_an_empty_list():
    todo = TodoList()
    todo.apply("add", "x")
    todo.on_start(None, "next task")
    assert todo.render() == "Todo list: (empty)"


def test_the_tool_is_given():
    spec = TodoList().tool().spec
    assert spec.name == "todo" and spec.parameters["properties"]["action"]["enum"] == ["add", "complete", "list"]
