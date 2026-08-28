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


def _markdown_agent(name: str, role: dict[str, object], profile_path: Path) -> str:
    return (
        f'---\nname: "{name}"\ndescription: "{role["description"]}"\n---\n\n'
        f"# {role['title']}\n\n"
        f"Read the personal profile at `{profile_path}` before acting. Bind the active project at "
        "runtime; do not copy project data into this profile. Produce a reviewable draft final and "
        "ask for explicit approval before any irreversible external action.\n"
    )


def _codex_agent(name: str, role: dict[str, object], profile_path: Path) -> str:
    instructions = (
        f"Read the personal profile at {profile_path} before acting. Bind the active project at runtime. "
        "Produce a reviewable draft final and ask for explicit approval before irreversible external actions."
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
        name = f"{card_slug}-{raw_role['slug']}"
        if "claude" in platforms:
            target = home / ".claude" / "agents" / "agent-factory" / f"{name}.md"
            _write(target, _markdown_agent(name, raw_role, destination))
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
