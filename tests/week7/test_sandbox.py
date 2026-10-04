import os
import sys
import time

import pytest

from harnessy.tools.registry import ToolRegistry
from harnessy.tools.sandbox import CommandResult, run_command, shell_tool
from harnessy.types import ToolCall


def test_exit_code_and_merged_output(tmp_path):
    r = run_command("echo out; echo err >&2; exit 3", tmp_path)
    assert r == CommandResult(3, "out\nerr\n", False)
    assert run_command([sys.executable, "-c", "print(1 + 1)"], tmp_path).output == "2\n"


def test_runs_in_the_workdir_with_a_scrubbed_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    r = run_command("pwd; echo HOME=$HOME; echo TOKEN=$SECRET_TOKEN", tmp_path, env={"EXTRA": "1"})
    lines = r.output.splitlines()
    assert os.path.realpath(lines[0]) == os.path.realpath(tmp_path)
    assert lines[1] == f"HOME={tmp_path}" and lines[2] == "TOKEN="
    assert run_command("echo $EXTRA", tmp_path, env={"EXTRA": "1"}).output == "1\n"


def test_a_timeout_kills_the_whole_process_group(tmp_path):
    start = time.monotonic()
    r = run_command("echo started; sleep 30 & echo $! > child.pid; wait", tmp_path, timeout_s=0.5)
    assert r.timed_out and r.exit_code is None and "started" in r.output
    assert time.monotonic() - start < 5
    pid = int((tmp_path / "child.pid").read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the background child is still running")


def test_output_is_capped(tmp_path):
    r = run_command([sys.executable, "-c", "print('x' * 5000)"], tmp_path, max_output=100)
    assert r.output.startswith("x" * 100) and "[truncated: showing the first 100 of 5,001 characters]" in r.output


def test_shell_tool_is_given(tmp_path):
    reg = ToolRegistry([shell_tool(tmp_path, timeout_s=0.5)])
    assert reg.call(ToolCall("c1", "run_shell", {"command": "echo hi"})).content == "exit code 0\nhi\n"
    slow = reg.call(ToolCall("c2", "run_shell", {"command": "sleep 5"})).content
    assert slow.startswith("timed out after 0.5s; the process was killed")
    assert reg.tools[0].tags == frozenset({"private_data", "untrusted_input", "external_send"})


def test_a_flood_of_output_is_stopped(tmp_path):
    run_command("echo ok", tmp_path)  # fails plainly while a stub
    start = time.monotonic()
    r = run_command([sys.executable, "-c", "while True: print('y' * 1000)"], tmp_path, timeout_s=30, max_output=100, max_bytes=200_000)
    assert r.exit_code is None and not r.timed_out and time.monotonic() - start < 10
    assert r.output.startswith("y" * 100) and "output limit of 200,000 bytes reached; the process was killed" in r.output
