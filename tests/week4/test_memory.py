from harnessy.memory import MemoryStore, memory_tools
from harnessy.tools.registry import ToolRegistry
from harnessy.types import ToolCall


def test_a_fact_survives_a_new_store_on_the_same_file(tmp_path):
    path = tmp_path / "memory.json"
    assert not path.exists()
    assert MemoryStore(path).remember("user_timezone", "Europe/Berlin") == "Remembered 'user_timezone'."
    assert path.exists()
    assert MemoryStore(path).recall("what timezone is the user in") == "- user_timezone: Europe/Berlin"


def test_ranking_and_limit(tmp_path):
    store = MemoryStore(tmp_path / "m.json")
    store.remember("a", "the cat sat on the mat")
    store.remember("b", "cat food brand")
    store.remember("c", "dog walker")
    assert store.recall("cat mat") == "- a: the cat sat on the mat\n- b: cat food brand"
    assert store.recall("cat mat", limit=1) == "- a: the cat sat on the mat"


def test_ties_are_ordered_by_key(tmp_path):
    store = MemoryStore(tmp_path / "m.json")
    store.remember("zeta", "blue")
    store.remember("alpha", "blue")
    assert store.recall("blue") == "- alpha: blue\n- zeta: blue"


def test_no_match_and_short_words(tmp_path):
    store = MemoryStore(tmp_path / "m.json")
    store.remember("a", "on a hill")
    assert store.recall("zebra") == "No memories match 'zebra'."
    assert store.recall("on a") == "No memories match 'on a'."


def test_memory_tools(tmp_path):
    reg = ToolRegistry(memory_tools(MemoryStore(tmp_path / "m.json")))
    assert [s.name for s in reg.specs()] == ["remember", "recall"]
    reg.call(ToolCall("c1", "remember", {"key": "colour", "text": "teal"}))
    assert reg.call(ToolCall("c2", "recall", {"query": "favourite colour"})).content == "- colour: teal"
