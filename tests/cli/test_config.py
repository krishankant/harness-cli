import json

import pytest

from harness_cli.config import ConfigError, Settings, load_settings


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


def test_defaults_without_files(workspace):
    s = load_settings(workspace)
    assert s == Settings()
    assert s.permission_mode == "default" and s.sandbox == "workspace-write"


def test_project_overrides_user_and_flags_override_both(workspace, harness_home):
    write(harness_home / "settings.json", {"provider": "openai", "model": "u", "maxSteps": 5})
    write(workspace / ".harness" / "settings.json", {"model": "p"})
    s = load_settings(workspace, {"max_steps": 9})
    assert (s.provider, s.model, s.max_steps) == ("openai", "p", 9)


def test_none_overrides_are_ignored(workspace, harness_home):
    write(harness_home / "settings.json", {"model": "u"})
    assert load_settings(workspace, {"model": None}).model == "u"


def test_permission_lists_are_concatenated(workspace, harness_home):
    write(harness_home / "settings.json", {"permissions": {"allow": ["run_shell(ls*)"], "deny": ["run_shell(rm*)"]}})
    write(workspace / ".harness" / "settings.json", {"permissions": {"allow": ["run_shell(git *)"], "defaultMode": "plan"}})
    s = load_settings(workspace, {"allow": ["edit_file"]})
    assert s.allow == ("run_shell(ls*)", "run_shell(git *)", "edit_file")
    assert s.deny == ("run_shell(rm*)",)
    assert s.permission_mode == "plan"


def test_bad_json_names_the_file(workspace):
    write(workspace / ".harness" / "settings.json", "{not json")
    with pytest.raises(ConfigError, match=r"\.harness/settings\.json"):
        load_settings(workspace)


def test_unknown_mode_and_sandbox_rejected(workspace):
    with pytest.raises(ConfigError, match="permission mode"):
        load_settings(workspace, {"permission_mode": "yolo"})
    with pytest.raises(ConfigError, match="sandbox"):
        load_settings(workspace, {"sandbox": "docker"})


def test_mcp_servers_read(workspace):
    write(workspace / ".harness" / "settings.json", {"mcpServers": {"notes": {"command": ["python", "server.py"]}}})
    assert load_settings(workspace).mcp_servers == {"notes": {"command": ["python", "server.py"]}}
