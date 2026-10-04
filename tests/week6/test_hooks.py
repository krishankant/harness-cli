from dataclasses import replace

from harnessy.hooks import Block, Hook, HookRunner, StopCheck
from harnessy.models.scripted import text_reply
from harnessy.types import Message, ToolCall, ToolResult


class Tag(Hook):
    def __init__(self, tag):
        self.tag = tag

    def before_model(self, view):
        return [*view, Message("user", text=self.tag)]

    def after_model(self, response):
        return replace(response, message=replace(response.message, text=response.message.text + self.tag))

    def before_tool(self, call):
        return replace(call, arguments={**call.arguments, self.tag: True})

    def after_tool(self, call, result):
        return replace(result, content=result.content + self.tag)


class Watch(Hook):
    def __init__(self):
        self.seen = []

    def before_model(self, view):
        self.seen.append([m.text for m in view])

    def before_tool(self, call):
        self.seen.append(call.name)


class Stopper(Hook):
    def before_model(self, view):
        return Block("no model")

    def before_tool(self, call):
        return Block("no tool")


CALL = ToolCall("c1", "add", {"a": 1})


def test_before_model_chains_in_order():
    watch = Watch()
    out = HookRunner([Tag("a"), watch, Tag("b")]).before_model([Message("user", text="t")])
    assert [m.text for m in out] == ["t", "a", "b"]
    assert watch.seen == [["t", "a"]]


def test_the_first_block_wins_and_later_hooks_do_not_run():
    watch = Watch()
    runner = HookRunner([Stopper(), watch])
    assert runner.before_model([Message("user", text="t")]) == Block("no model")
    assert runner.before_tool(CALL) == Block("no tool")
    assert watch.seen == []


def test_after_model_before_tool_and_after_tool_chain():
    runner = HookRunner([Tag("a"), Tag("b")])
    assert runner.after_model(text_reply("x")).message.text == "xab"
    assert runner.before_tool(CALL).arguments == {"a": True, "b": True}
    assert runner.after_tool(CALL, ToolResult("c1", "r")).content == "rab"


def test_none_keeps_the_value():
    runner = HookRunner([Watch(), Hook()])
    view = [Message("user", text="t")]
    assert runner.before_model(view) == view
    assert runner.before_tool(CALL) == CALL
    assert runner.after_tool(CALL, ToolResult("c1", "r")) == ToolResult("c1", "r")


def test_on_stop_returns_the_first_rejection():
    class Says(Hook):
        def __init__(self, msg):
            self.msg = msg

        def on_stop(self, result):
            return self.msg

    assert HookRunner([Says(None), Says("first"), Says("second")]).on_stop(object()) == "first"
    assert HookRunner([Says(None)]).on_stop(object()) is None


def test_on_start_and_on_finish_reach_every_hook():
    calls = []

    class Log(Hook):
        def on_start(self, agent, task):
            calls.append(("start", task))

        def on_finish(self, result):
            calls.append(("finish", result))

    runner = HookRunner([Log(), Log()])
    runner.on_start(None, "t")
    runner.on_finish("r")
    assert calls == [("start", "t"), ("start", "t"), ("finish", "r"), ("finish", "r")]


def test_stop_check_rejects_until_its_limit():
    check = StopCheck(lambda result: "not yet", max_rejections=2)
    assert [check.on_stop(None) for _ in range(3)] == ["not yet", "not yet", None]
    check.on_start(None, "t")
    assert check.on_stop(None) == "not yet"
    assert StopCheck(lambda result: None).on_stop(None) is None
