from harness_cli.config import Settings
from harness_cli.instructions import build_system_prompt


def test_includes_project_files_in_order(workspace, harness_home):
    (workspace / "AGENTS.md").write_text("agents rules")
    (workspace / "HARNESS.md").write_text("harness rules")
    harness_home.mkdir(parents=True)
    (harness_home / "HARNESS.md").write_text("user rules")
    prompt = build_system_prompt(workspace, Settings(append_system_prompt="be brief"), ["read_file"])
    assert prompt.index("user rules") < prompt.index("harness rules") < prompt.index("agents rules") < prompt.index("be brief")
    assert str(workspace) in prompt


def test_system_prompt_replaces_base(workspace):
    prompt = build_system_prompt(workspace, Settings(system_prompt="ONLY THIS"), [])
    assert prompt.startswith("ONLY THIS")
    assert "coding agent" not in prompt
