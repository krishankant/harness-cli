import uuid
from pathlib import Path

import pytest

from harness_cli.sandbox import run_sandboxed, sandbox_available, seatbelt_profile

needs_seatbelt = pytest.mark.skipif(not sandbox_available(), reason="Seatbelt needs macOS sandbox-exec")


def test_profile_quotes_paths(tmp_path):
    ws = tmp_path / 'we"ird'
    ws.mkdir()
    assert 'we\\"ird' in seatbelt_profile(ws)


def test_off_runs_plainly(workspace):
    r = run_sandboxed("echo ok > f.txt && cat f.txt", workspace, 10, "off")
    assert r.exit_code == 0 and "ok" in r.output


@needs_seatbelt
def test_blocks_write_outside_workspace(workspace):
    # Temp folders are writable on purpose, so probe a path in the home folder instead.
    outside = Path.home() / f".harness-sandbox-probe-{uuid.uuid4().hex}"
    try:
        r = run_sandboxed(f"echo x > '{outside}'", workspace, 10, "workspace-write")
        assert r.exit_code != 0 and not outside.exists()
    finally:
        outside.unlink(missing_ok=True)
    inside = run_sandboxed("echo x > inside.txt", workspace, 10, "workspace-write")
    assert inside.exit_code == 0 and (workspace / "inside.txt").exists()


@needs_seatbelt
def test_sandbox_workspace_with_space(tmp_path):
    ws = tmp_path / "my project"
    ws.mkdir()
    r = run_sandboxed("echo x > a.txt && cat a.txt", ws, 10, "workspace-write")
    assert r.exit_code == 0 and (ws / "a.txt").exists()


@needs_seatbelt
def test_blocks_network(workspace):
    r = run_sandboxed("/usr/bin/curl -sS -m 3 https://example.com -o /dev/null", workspace, 10, "workspace-write")
    assert r.exit_code != 0
