#!/usr/bin/env python3
"""Freeze a server Avatar Card (Card/Role/Task) and/or its local install files into a *.zip backup.

Every captured piece is stored byte-for-byte as received/read -- never re-serialized -- so a
restore can reproduce the exact same content later. See scripts/restore_avatar.py for the
reverse direction (import to server / restore to local).
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

Scope = Literal["server", "local", "both"]
HttpGet = Callable[[str], bytes]


class HttpError(RuntimeError):
    def __init__(self, path: str, status: int, body: bytes) -> None:
        super().__init__(f"GET {path} -> {status}")
        self.path = path
        self.status = status
        self.body = body


def default_http_get(base_url: str, api_key: str) -> HttpGet:
    def get(path: str) -> bytes:
        req = urllib.request.Request(f"{base_url}{path}", headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise HttpError(path, exc.code, exc.read()) from exc

    return get


def fetch_server_snapshot(http_get: HttpGet, card_id: str) -> dict[str, bytes]:
    """Walk card -> roles -> tasks and return {arcname: raw_response_bytes}, verbatim."""
    files: dict[str, bytes] = {}
    card_bytes = http_get(f"/avatars/cards/{card_id}")
    files["server/card.json"] = card_bytes
    card = json.loads(card_bytes)
    for role_ref in card.get("roles", []):
        role_id = role_ref["avatar_role_id"]
        role_bytes = http_get(f"/avatars/roles/{role_id}")
        files[f"server/roles/{role_id}.json"] = role_bytes
        role = json.loads(role_bytes)
        for task_ref in role.get("tasks", []):
            task_id = task_ref["avatar_task_id"]
            arcname = f"server/tasks/{task_id}.json"
            if arcname in files:
                continue
            files[arcname] = http_get(f"/avatars/tasks/{task_id}")
    return files


_LOCAL_TARGETS = (
    ("{home}/.claude/agents/agent-factory/{name}.md",),
    ("{home}/.config/opencode/agents/agent-factory/{name}.md",),
    ("{home}/.codex/agents/{name}.toml",),
)


def collect_local_files(home: Path, card_slug: str, role_slugs: list[str]) -> dict[str, bytes]:
    """Return {arcname: raw_bytes} for whichever install targets exist, arcname mirroring the
    home-relative path so restore_avatar.py can write it back unchanged."""
    files: dict[str, bytes] = {}

    def _add(path: Path) -> None:
        if path.exists():
            arcname = "local/" + path.relative_to(home).as_posix()
            files[arcname] = path.read_bytes()

    _add(home / ".agent-factory" / "avatars" / card_slug / "profile.md")
    _add(home / ".agent-factory" / "avatars" / card_slug / "decisions.md")
    for role_slug in role_slugs:
        name = f"{card_slug}-{role_slug}"
        _add(home / ".claude" / "agents" / "agent-factory" / f"{name}.md")
        _add(home / ".config" / "opencode" / "agents" / "agent-factory" / f"{name}.md")
        _add(home / ".codex" / "agents" / f"{name}.toml")
    return files


def backup(
    *,
    output: Path,
    scope: Scope = "both",
    http_get: HttpGet | None = None,
    card_id: str | None = None,
    home: Path | None = None,
    card_slug: str | None = None,
    role_slugs: list[str] | None = None,
) -> Path:
    if scope in ("server", "both"):
        if http_get is None or card_id is None:
            raise ValueError("server scope requires http_get and card_id")
    if scope in ("local", "both"):
        if home is None or card_slug is None:
            raise ValueError("local scope requires home and card_slug")

    files: dict[str, bytes] = {}
    if scope in ("server", "both"):
        assert http_get is not None and card_id is not None
        files.update(fetch_server_snapshot(http_get, card_id))
    if scope in ("local", "both"):
        assert home is not None and card_slug is not None
        files.update(collect_local_files(home, card_slug, role_slugs or []))

    manifest = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "card_id": card_id,
        "card_slug": card_slug,
        "files": sorted(files.keys()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for arcname, data in files.items():
            zf.writestr(arcname, data)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", choices=["server", "local", "both"], default="both")
    parser.add_argument("--card-id")
    parser.add_argument("--card-slug")
    parser.add_argument("--role-slug", action="append", dest="role_slugs", default=[])
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AGENT_FACTORY_BASE_URL", "https://agent.samsungds.net:3355/api/v1/agent"),
    )
    args = parser.parse_args()

    http_get = None
    if args.scope in ("server", "both"):
        api_key = os.environ.get("AGENT_FACTORY_API_KEY")
        if not api_key:
            raise SystemExit("AGENT_FACTORY_API_KEY is required for server scope")
        http_get = default_http_get(args.base_url, api_key)

    result = backup(
        output=args.output,
        scope=args.scope,
        http_get=http_get,
        card_id=args.card_id,
        home=args.home,
        card_slug=args.card_slug,
        role_slugs=args.role_slugs,
    )
    print(result)


if __name__ == "__main__":
    main()
