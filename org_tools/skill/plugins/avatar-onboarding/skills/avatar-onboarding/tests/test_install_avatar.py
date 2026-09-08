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


def _profile(tmp_path: Path, skills: list[str] | None = None, approval_scope: object | None = None) -> Path:
    role: dict[str, object] = {"slug": "reviewer", "title": "PR Reviewer", "description": "Review pull requests."}
    if skills is not None:
        role["skills"] = skills
    if approval_scope is not None:
        role["approval_scope"] = approval_scope
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "card_slug": "pr-review",
                "profile": "Review code carefully. Ask before creating a PR.",
                "roles": [role],
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


def test_claude_agent_denies_delegation_tools_by_default(tmp_path: Path) -> None:
    installer.install(_profile(tmp_path), home=tmp_path, platforms=["claude"])
    claude = (tmp_path / ".claude/agents/agent-factory/pr-review-reviewer.md").read_text(encoding="utf-8")

    assert f"tools: {installer._BASE_TOOL_BUNDLE}\n" in claude
    assert "Agent" not in claude
    assert "SendMessage" not in claude


def test_claude_agent_allows_delegation_when_role_opts_in(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "card_slug": "pr-review",
                "profile": "Review code carefully. Ask before creating a PR.",
                "roles": [
                    {
                        "slug": "reviewer",
                        "title": "PR Reviewer",
                        "description": "Review pull requests.",
                        "allow_delegation": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    installer.install(profile, home=tmp_path, platforms=["claude"])
    claude = (tmp_path / ".claude/agents/agent-factory/pr-review-reviewer.md").read_text(encoding="utf-8")

    assert f"tools: {installer._BASE_TOOL_BUNDLE}, Agent, SendMessage\n" in claude


def test_opencode_agent_has_no_tools_field(tmp_path: Path) -> None:
    installer.install(_profile(tmp_path), home=tmp_path, platforms=["opencode"])
    opencode = (tmp_path / ".config/opencode/agents/agent-factory/pr-review-reviewer.md").read_text(encoding="utf-8")

    assert "tools:" not in opencode


def test_install_rejects_non_boolean_allow_delegation(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "card_slug": "pr-review",
                "profile": "Review code carefully.",
                "roles": [
                    {
                        "slug": "reviewer",
                        "title": "PR Reviewer",
                        "description": "Review pull requests.",
                        "allow_delegation": "yes",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="allow_delegation"):
        installer.install(profile, home=tmp_path, platforms=["claude"])


def test_claude_agent_scopes_tools_to_base_bundle_plus_named_skills(tmp_path: Path) -> None:
    installer.install(
        _profile(tmp_path, skills=["foo", "bar"]), home=tmp_path, platforms=["claude", "opencode", "codex"]
    )

    claude = (tmp_path / ".claude/agents/agent-factory/pr-review-reviewer.md").read_text(encoding="utf-8")
    assert f"tools: {installer._BASE_TOOL_BUNDLE}, Skill(foo, bar)\n" in claude

    opencode = (tmp_path / ".config/opencode/agents/agent-factory/pr-review-reviewer.md").read_text(encoding="utf-8")
    codex = (tmp_path / ".codex/agents/pr-review-reviewer.toml").read_text(encoding="utf-8")
    assert "tools:" not in opencode
    assert "Skill(" not in opencode
    assert "tools =" not in codex
    assert "Skill(" not in codex


@pytest.mark.parametrize("skills", [None, []])
def test_claude_agent_without_skills_still_scopes_to_base_bundle(tmp_path: Path, skills: list[str] | None) -> None:
    installer.install(_profile(tmp_path, skills=skills), home=tmp_path, platforms=["claude"])

    claude = (tmp_path / ".claude/agents/agent-factory/pr-review-reviewer.md").read_text(encoding="utf-8")
    assert f"tools: {installer._BASE_TOOL_BUNDLE}\n" in claude
    assert "Skill(" not in claude


@pytest.mark.parametrize("skills", ["foo", ["foo", 3]])
def test_install_rejects_malformed_skills(tmp_path: Path, skills: object) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "card_slug": "pr-review",
                "profile": "Review code carefully.",
                "roles": [
                    {
                        "slug": "reviewer",
                        "title": "PR Reviewer",
                        "description": "Review pull requests.",
                        "skills": skills,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="role skills"):
        installer.install(profile, home=tmp_path, platforms=["claude"])


_EXTERNAL_WRITE_CLAUSE = (
    "Produce a reviewable draft final and ask for explicit approval before any irreversible external action."
)


def _rendered(tmp_path: Path, approval_scope: object | None = None) -> tuple[str, str]:
    installer.install(
        _profile(tmp_path, approval_scope=approval_scope), home=tmp_path, platforms=["claude", "codex"]
    )
    return (
        (tmp_path / ".claude/agents/agent-factory/pr-review-reviewer.md").read_text(encoding="utf-8"),
        (tmp_path / ".codex/agents/pr-review-reviewer.toml").read_text(encoding="utf-8"),
    )


def test_unset_approval_scope_keeps_external_write_clause(tmp_path: Path) -> None:
    claude, codex = _rendered(tmp_path)

    assert claude.endswith(f"this profile. {_EXTERNAL_WRITE_CLAUSE}\n")
    assert f"runtime. {_EXTERNAL_WRITE_CLAUSE}\"\n" in codex


def test_approval_scope_external_write_renders_the_default_clause(tmp_path: Path) -> None:
    claude, codex = _rendered(tmp_path, approval_scope="external-write")

    assert _EXTERNAL_WRITE_CLAUSE in claude
    assert _EXTERNAL_WRITE_CLAUSE in codex


def test_approval_scope_none_omits_the_clause(tmp_path: Path) -> None:
    claude, codex = _rendered(tmp_path, approval_scope="none")

    assert "Produce a reviewable draft final" not in claude
    assert "Produce a reviewable draft final" not in codex
    assert claude.endswith("do not copy project data into this profile.\n")
    assert codex.endswith('Bind the active project at runtime."\n')


def test_approval_scope_all_requires_approval_before_any_action(tmp_path: Path) -> None:
    claude, codex = _rendered(tmp_path, approval_scope="all")

    clause = "ask for explicit approval before any action, external or local, reversible or not."
    assert clause in claude
    assert clause in codex
    assert "irreversible external action." not in claude


@pytest.mark.parametrize("scope", ["sometimes", True])
def test_install_rejects_invalid_approval_scope(tmp_path: Path, scope: object) -> None:
    with pytest.raises(ValueError, match="role approval_scope"):
        installer.install(_profile(tmp_path, approval_scope=scope), home=tmp_path, platforms=["claude"])


def test_install_refuses_to_overwrite_user_modified_agent(tmp_path: Path) -> None:
    installer.install(_profile(tmp_path), home=tmp_path, platforms=["claude"])
    agent = tmp_path / ".claude/agents/agent-factory/pr-review-reviewer.md"
    agent.write_text("user modification", encoding="utf-8")

    with pytest.raises(installer.InstallConflictError, match="user-modified"):
        installer.install(_profile(tmp_path), home=tmp_path, platforms=["claude"])
