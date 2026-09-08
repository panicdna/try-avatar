#!/usr/bin/env python3
"""Install a reviewed Avatar Onboarding profile into local assistant targets.

The JSON input is intentionally local and contains no credentials or raw domain
data. The calling Skill obtains/assembles it after the user approves the plan.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

Platform = Literal["claude", "opencode", "codex"]

_BASE_TOOL_BUNDLE = "Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion, TaskCreate, TaskGet, TaskList, TaskUpdate"
# Excluded from the base bundle: without this, a subagent could recursively spawn
# (Agent) or message (SendMessage) further subagents of its own type instead of
# doing the work itself. Set role["allow_delegation"] = true to add them back.
_DELEGATION_TOOLS = ("Agent", "SendMessage")
_APPROVAL_CLAUSES = {
    "none": "",
    "external-write": (
        "Produce a reviewable draft final and ask for explicit approval before any irreversible "
        "external action."
    ),
    "all": (
        "Produce a reviewable draft final and ask for explicit approval before any action, external "
        "or local, reversible or not."
    ),
}


class InstallConflictError(RuntimeError):
    """An existing target is not the exact generated content for this install."""


def _read_profile(profile_path: Path) -> dict[str, object]:
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(data.get("card_slug"), str) or not isinstance(data.get("profile"), str):
        raise ValueError("profile JSON requires string card_slug and profile")
    if not isinstance(data.get("roles"), list) or not data["roles"]:
        raise ValueError("profile JSON requires at least one role")
    return data


def _profile_path(home: Path, card_slug: str) -> Path:
    return home / ".agent-factory" / "avatars" / card_slug / "profile.md"


def _tools_line(role: dict[str, object]) -> str:
    tools = _BASE_TOOL_BUNDLE
    if role.get("allow_delegation"):
        tools += f", {', '.join(_DELEGATION_TOOLS)}"
    skills = role.get("skills") or []
    assert isinstance(skills, list)
    suffix = f", Skill({', '.join(skills)})" if skills else ""
    return f"tools: {tools}{suffix}\n"


def _approval_clause(role: dict[str, object]) -> str:
    scope = role.get("approval_scope", "external-write")
    assert isinstance(scope, str)
    return _APPROVAL_CLAUSES[scope]


def _with_approval_clause(base: str, role: dict[str, object]) -> str:
    clause = _approval_clause(role)
    return f"{base} {clause}" if clause else base


def _markdown_agent(name: str, role: dict[str, object], profile_path: Path, tools_line: str = "") -> str:
    prose = _with_approval_clause(
        f"Read the personal profile at `{profile_path}` before acting. Bind the active project at "
        "runtime; do not copy project data into this profile.",
        role,
    )
    return (
        f'---\nname: "{name}"\ndescription: "{role["description"]}"\n{tools_line}---\n\n'
        f"# {role['title']}\n\n{prose}\n"
    )


def _codex_agent(name: str, role: dict[str, object], profile_path: Path) -> str:
    instructions = _with_approval_clause(
        f"Read the personal profile at {profile_path} before acting. Bind the active project at runtime.",
        role,
    ).replace('"', '\\"')
    return f'name = "{name}"\ndescription = "{role["description"]}"\ndeveloper_instructions = "{instructions}"\n'


def _write(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise InstallConflictError(f"user-modified target: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def install(profile_path: Path, *, home: Path, platforms: list[Platform]) -> list[Path]:
    data = _read_profile(profile_path)
    card_slug = data["card_slug"]
    assert isinstance(card_slug, str)
    profile = data["profile"]
    assert isinstance(profile, str)
    destination = _profile_path(home, card_slug)
    written: list[Path] = []
    _write(destination, profile + "\n")
    written.append(destination)
    roles = data["roles"]
    assert isinstance(roles, list)
    for raw_role in roles:
        if not isinstance(raw_role, dict) or not all(isinstance(raw_role.get(key), str) for key in ("slug", "title", "description")):
            raise ValueError("each role requires string slug, title, and description")
        if "allow_delegation" in raw_role and not isinstance(raw_role["allow_delegation"], bool):
            raise ValueError("role allow_delegation must be a boolean when present")
        if "skills" in raw_role and not (
            isinstance(raw_role["skills"], list) and all(isinstance(item, str) for item in raw_role["skills"])
        ):
            raise ValueError("role skills must be a list of strings when present")
        if "approval_scope" in raw_role and raw_role["approval_scope"] not in _APPROVAL_CLAUSES:
            raise ValueError("role approval_scope must be one of none, external-write, all when present")
        name = f"{card_slug}-{raw_role['slug']}"
        if "claude" in platforms:
            target = home / ".claude" / "agents" / "agent-factory" / f"{name}.md"
            _write(target, _markdown_agent(name, raw_role, destination, tools_line=_tools_line(raw_role)))
            written.append(target)
        if "opencode" in platforms:
            target = home / ".config" / "opencode" / "agents" / "agent-factory" / f"{name}.md"
            _write(target, _markdown_agent(name, raw_role, destination))
            written.append(target)
        if "codex" in platforms:
            target = home / ".codex" / "agents" / f"{name}.toml"
            _write(target, _codex_agent(name, raw_role, destination))
            written.append(target)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--platform", choices=["claude", "opencode", "codex"], action="append", required=True)
    args = parser.parse_args()
    for path in install(args.profile, home=args.home, platforms=args.platform):
        print(path)


if __name__ == "__main__":
    main()
