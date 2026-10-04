import pytest

from harnessy.evals.graders import JUDGE_PROMPT, CheckResult, grade, judge_verdict
from harnessy.models.scripted import ScriptedModel, text_reply


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "out.txt").write_text("Hello, harness!")
    (tmp_path / "d.json").write_text('{"a": 1}')
    (tmp_path / "bad.json").write_text("{nope")
    return tmp_path


def test_file_exists(ws):
    assert grade({"type": "file_exists", "path": "out.txt"}, "", ws) == CheckResult(True, "out.txt exists")
    assert grade({"type": "file_exists", "path": "no.txt"}, "", ws) == CheckResult(False, "no.txt does not exist")


def test_file_contains_and_lacks(ws):
    assert grade({"type": "file_contains", "path": "out.txt", "text": "harness"}, "", ws).passed
    assert not grade({"type": "file_contains", "path": "out.txt", "text": "HARNESS"}, "", ws).passed
    assert not grade({"type": "file_contains", "path": "no.txt", "text": "x"}, "", ws).passed
    assert grade({"type": "file_lacks", "path": "out.txt", "text": "goodbye"}, "", ws).passed
    assert not grade({"type": "file_lacks", "path": "out.txt", "text": "Hello"}, "", ws).passed
    assert not grade({"type": "file_lacks", "path": "no.txt", "text": "x"}, "", ws).passed


def test_answer_contains_ignores_case(ws):
    assert grade({"type": "answer_contains", "text": "blue heron"}, "It is BLUE HERON.", ws).passed
    assert not grade({"type": "answer_contains", "text": "red"}, "It is blue.", ws).passed


def test_answer_matches(ws):
    assert grade({"type": "answer_matches", "pattern": r"\b7\b"}, "There are 7 lines.", ws).passed
    assert not grade({"type": "answer_matches", "pattern": r"\b7\b"}, "There are 17 lines.", ws).passed


def test_json_valid_and_equals(ws):
    assert grade({"type": "json_valid", "path": "d.json"}, "", ws).passed
    assert grade({"type": "json_valid", "path": "d.json", "equals": {"a": 1}}, "", ws).passed
    assert not grade({"type": "json_valid", "path": "d.json", "equals": {"a": 2}}, "", ws).passed
    bad = grade({"type": "json_valid", "path": "bad.json"}, "", ws)
    assert not bad.passed and "not valid JSON" in bad.detail


def test_a_check_cannot_read_outside_the_workspace(ws):
    r = grade({"type": "file_exists", "path": "../out.txt"}, "", ws)
    assert not r.passed and "escapes" in r.detail


def test_a_missing_field_is_a_failed_check(ws):
    r = grade({"type": "file_contains", "path": "out.txt"}, "", ws)
    assert not r.passed and "missing 'text'" in r.detail


def test_rubric_needs_a_judge(ws):
    assert grade({"type": "rubric", "criteria": "c"}, "a", ws) == CheckResult(False, "rubric check needs a judge model")


def test_judge_pass_fail_and_unclear():
    judge = ScriptedModel([text_reply("**PASS** - three lines about bees."), text_reply("fail: too long"), text_reply("Looks good")])
    assert judge_verdict(judge, "About bees.", "a haiku") == CheckResult(True, "judge: PASS - three lines about bees.")
    [call] = judge.calls[:1]
    assert call.system == JUDGE_PROMPT and call.messages[0].text == "Rubric:\nAbout bees.\n\nWork to grade:\na haiku"
    assert judge_verdict(judge, "c", "a") == CheckResult(False, "judge: FAIL too long")
    unclear = judge_verdict(judge, "c", "a")
    assert not unclear.passed and unclear.detail.startswith("judge reply unclear")


def test_rubric_can_grade_a_file(ws):
    judge = ScriptedModel([text_reply("PASS fine")])
    assert grade({"type": "rubric", "criteria": "c", "path": "out.txt"}, "ignored", ws, judge).passed
    assert judge.calls[0].messages[0].text.endswith("Work to grade:\nHello, harness!")
