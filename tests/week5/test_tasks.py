import re
import textwrap
from collections import Counter
from pathlib import Path

import pytest
import yaml

from harnessy.evals.tasks import EvalTask, TaskError, load_task, load_tasks

ROOT = Path(__file__).resolve().parents[2]
VALID = """
id: demo
prompt: Say hi.
difficulty: easy
toolsets: [files]
files:
  a.txt: hello
checks:
  - type: answer_contains
    text: hi
"""


def write(folder: Path, text: str, name: str = "t.yaml") -> Path:
    path = folder / name
    path.write_text(textwrap.dedent(text))
    return path


def test_a_valid_task(tmp_path):
    assert load_task(write(tmp_path, VALID)) == EvalTask(
        "demo", "Say hi.", "easy", ({"type": "answer_contains", "text": "hi"},), {"a.txt": "hello"}, ("files",), 10, None
    )


@pytest.mark.parametrize(
    "change, problem",
    [
        (lambda d: d.pop("prompt"), "missing 'prompt'"),
        (lambda d: d.update(difficulty="extreme"), "difficulty must be one of easy, medium, hard"),
        (lambda d: d.update(checks=[]), "'checks' must be a non-empty list"),
        (lambda d: d.update(checks=[{"type": "vibes"}]), "check 1 needs a 'type' from:"),
        (lambda d: d.update(toolsets=["web"]), "unknown toolsets: web"),
        (lambda d: d.update(max_steps=0), "'max_steps' must be a positive integer"),
        (lambda d: d.update(files={"a.txt": 3}), "'files' must map paths to text"),
        (lambda d: d.update(colour="red"), "unknown keys: colour"),
        (lambda d: d.update(agent="robot"), "unknown agent: robot"),
    ],
)
def test_invalid_tasks_name_the_file_and_the_problem(tmp_path, change, problem):
    data = yaml.safe_load(VALID)
    change(data)
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(TaskError, match=re.escape(f"bad.yaml: {problem}")):
        load_task(path)


def test_not_a_mapping(tmp_path):
    with pytest.raises(TaskError, match="must be a mapping"):
        load_task(write(tmp_path, "- just\n- a list\n"))


def test_load_tasks_select_and_duplicates(tmp_path):
    write(tmp_path, VALID, "a.yaml")
    write(tmp_path, VALID.replace("id: demo", "id: demo2").replace("difficulty: easy", "difficulty: hard"), "b.yaml")
    assert [t.id for t in load_tasks(tmp_path)] == ["demo", "demo2"]
    assert [t.id for t in load_tasks(tmp_path, "hard")] == ["demo2"]
    assert [t.id for t in load_tasks(tmp_path, "demo2")] == ["demo2"]
    write(tmp_path, VALID, "c.yaml")
    with pytest.raises(TaskError, match="duplicate task id: demo"):
        load_tasks(tmp_path)


def test_the_shipped_tasks_all_load():
    tasks = load_tasks(ROOT / "evals" / "tasks")
    assert len(tasks) == 15
    assert Counter(t.difficulty for t in tasks) == {"easy": 5, "medium": 5, "hard": 5}
    assert sum(any(c["type"] == "rubric" for c in t.checks) for t in tasks) == 1
    assert all(any(c["type"] != "rubric" for c in t.checks) for t in tasks)


def test_every_seeded_file_is_named_in_the_prompt():
    """The file tools can't list a folder, so a task must name every file the agent needs."""
    for task in load_tasks(ROOT / "evals" / "tasks"):
        if "files" not in task.toolsets:
            continue
        for path in task.files:
            name = Path(path).name
            assert name.startswith(".") or name in task.prompt, f"{task.id}: prompt doesn't name {name}"
