import pytest


@pytest.fixture(autouse=True)
def harness_home(tmp_path, monkeypatch):
    """Every CLI test gets its own ~/.harness, so nothing reads or writes the real one."""
    home = tmp_path / "harness-home"
    monkeypatch.setenv("HARNESS_HOME", str(home))
    monkeypatch.delenv("NO_COLOR", raising=False)
    return home


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "project"
    ws.mkdir()
    return ws.resolve()
