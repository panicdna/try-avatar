from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).parents[1] / "scripts" / "install_avatar.py"
_SPEC = importlib.util.spec_from_file_location("install_avatar", _SCRIPT)
assert _SPEC and _SPEC.loader
installer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(installer)


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "card_slug": "pr-review",
                "profile": "Review code carefully. Ask before creating a PR.",
                "roles": [{"slug": "reviewer", "title": "PR Reviewer", "description": "Review pull requests."}],
            }
        ),
        encoding="utf-8",
    )
    return profile


def test_install_writes_profile_and_all_platform_agents(tmp_path: Path) -> None:
    written = installer.install(_profile(tmp_path), home=tmp_path, platforms=["claude", "opencode", "codex"])

    assert tmp_path / ".agent-factory/avatars/pr-review/profile.md" in written
    claude = tmp_path / ".claude/agents/agent-factory/pr-review-reviewer.md"
    opencode = tmp_path / ".config/opencode/agents/agent-factory/pr-review-reviewer.md"
    codex = tmp_path / ".codex/agents/pr-review-reviewer.toml"
    assert 'name: "pr-review-reviewer"' in claude.read_text(encoding="utf-8")
    assert "personal profile" in opencode.read_text(encoding="utf-8")
    assert 'name = "pr-review-reviewer"' in codex.read_text(encoding="utf-8")


def test_install_refuses_to_overwrite_user_modified_agent(tmp_path: Path) -> None:
    installer.install(_profile(tmp_path), home=tmp_path, platforms=["claude"])
    agent = tmp_path / ".claude/agents/agent-factory/pr-review-reviewer.md"
    agent.write_text("user modification", encoding="utf-8")

    with pytest.raises(installer.InstallConflictError, match="user-modified"):
        installer.install(_profile(tmp_path), home=tmp_path, platforms=["claude"])
