from harnessy.loop import Agent
from harnessy.models.scripted import ScriptedModel, text_reply
from harnessy.streaming import Done


def test_second_run_continues_from_history():
    model = ScriptedModel([text_reply("Hi Ann."), text_reply("Your name is Ann.")])
    agent = Agent(model)
    first = agent.run("My name is Ann.")
    second = agent.run("What is my name?", history=first.messages)

    sent = model.calls[-1].messages
    assert [m.text for m in sent] == ["My name is Ann.", "Hi Ann.", "What is my name?"]
    assert [m.text for m in second.messages] == ["My name is Ann.", "Hi Ann.", "What is my name?", "Your name is Ann."]


def test_no_history_starts_fresh():
    model = ScriptedModel([text_reply("ok")])
    result = Agent(model).run("task")
    assert [m.text for m in result.messages] == ["task", "ok"]


def test_stream_passes_history():
    model = ScriptedModel([text_reply("one"), text_reply("two")])
    agent = Agent(model)
    first = agent.run("a")
    events = list(agent.stream("b", history=first.messages))
    assert isinstance(events[-1], Done)
    assert [m.text for m in events[-1].result.messages] == ["a", "one", "b", "two"]
