"""Settings: built-in defaults <- ~/.harness/settings.json <- <project>/.harness/settings.json <- flags.

Scalars from a later layer replace earlier ones; the permission allow/deny lists add up, so a
project can grant more without repeating the user's own rules."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

MODES = ("default", "accept-edits", "plan", "bypass")
SANDBOXES = ("workspace-write", "off")
PROVIDERS = ("anthropic", "openai", "ollama")

# settings.json key -> Settings field
_KEYS = {
    "provider": "provider",
    "model": "model",
    "sandbox": "sandbox",
    "maxSteps": "max_steps",
    "maxCostUsd": "max_cost_usd",
    "shellTimeout": "shell_timeout_s",
    "contextBudgetTokens": "context_budget_tokens",
    "systemPrompt": "system_prompt",
    "appendSystemPrompt": "append_system_prompt",
    "mcpServers": "mcp_servers",
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    provider: str = "anthropic"
    model: str | None = None
    permission_mode: str = "default"
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    sandbox: str = "workspace-write"
    max_steps: int = 50
    max_cost_usd: float | None = None
    shell_timeout_s: float = 120.0
    context_budget_tokens: int = 120_000
    system_prompt: str | None = None
    append_system_prompt: str | None = None
    mcp_servers: dict[str, Any] = field(default_factory=dict)


def harness_home() -> Path:
    """The user-level config folder: $HARNESS_HOME, else ~/.harness."""
    return Path(os.environ.get("HARNESS_HOME") or Path.home() / ".harness")


def settings_files(workspace: Path) -> list[Path]:
    return [harness_home() / "settings.json", Path(workspace) / ".harness" / "settings.json"]


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON: {e}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: settings must be a JSON object")
    return data


def _layer(data: dict[str, Any]) -> dict[str, Any]:
    """A settings.json object as Settings field names."""
    out = {name: data[key] for key, name in _KEYS.items() if key in data}
    perms = data.get("permissions") or {}
    if "defaultMode" in perms:
        out["permission_mode"] = perms["defaultMode"]
    for kind in ("allow", "deny"):
        if kind in perms:
            out[kind] = tuple(perms[kind])
    return out


def _merge(settings: Settings, layer: dict[str, Any]) -> Settings:
    known = {f.name for f in fields(Settings)}
    changes: dict[str, Any] = {}
    for name, value in layer.items():
        if name not in known or value is None:
            continue
        if name in ("allow", "deny"):
            value = (*getattr(settings, name), *value)
        changes[name] = value
    return replace(settings, **changes)


def validate(s: Settings) -> Settings:
    if s.permission_mode not in MODES:
        raise ConfigError(f"unknown permission mode {s.permission_mode!r}: use one of {', '.join(MODES)}")
    if s.sandbox not in SANDBOXES:
        raise ConfigError(f"unknown sandbox {s.sandbox!r}: use one of {', '.join(SANDBOXES)}")
    if s.provider not in PROVIDERS:
        raise ConfigError(f"unknown provider {s.provider!r}: use one of {', '.join(PROVIDERS)}")
    if s.max_steps < 1:
        raise ConfigError("maxSteps must be at least 1")
    return s


def load_settings(workspace: Path, overrides: dict[str, Any] | None = None) -> Settings:
    """Merge the user file, the project file and command-line overrides (Settings field names;
    None means "not given")."""
    settings = Settings()
    for path in settings_files(workspace):
        settings = _merge(settings, _layer(_read(path)))
    return validate(_merge(settings, dict(overrides or {})))
