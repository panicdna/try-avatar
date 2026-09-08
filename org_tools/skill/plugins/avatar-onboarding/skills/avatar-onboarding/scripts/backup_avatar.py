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
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _http import DEFAULT_BASE_URL, ApiError, NetworkError  # noqa: E402
from _install_targets import INSTALL_TARGET_TEMPLATES as _PLATFORM_INSTALL_TARGETS  # noqa: E402

Scope = Literal["server", "local", "both"]
HttpGet = Callable[[str], bytes]


def default_http_get(base_url: str, api_key: str) -> HttpGet:
    def get(path: str) -> bytes:
        req = urllib.request.Request(f"{base_url}{path}", headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise ApiError("GET", path, exc.code, exc.read()) from exc
        except urllib.error.URLError as exc:
            raise NetworkError("GET", path, exc) from exc

    return get


def fetch_server_snapshot(http_get: HttpGet, card_id: str) -> dict[str, bytes]:
    """Walk card -> roles -> tasks and return {arcname: raw_response_bytes}, verbatim."""
    files: dict[str, bytes] = {}
    card_bytes = http_get(f"/avatars/cards/{card_id}")
    files["server/card.json"] = card_bytes
    card = json.loads(card_bytes)
    for role_ref in card.get("roles", []):
        role_id = role_ref["avatar_role_id"]
        role_arcname = f"server/roles/{role_id}.json"
        if role_arcname in files:
            continue
        role_bytes = http_get(f"/avatars/roles/{role_id}")
        files[role_arcname] = role_bytes
        role = json.loads(role_bytes)
        for task_ref in role.get("tasks", []):
            task_id = task_ref["avatar_task_id"]
            arcname = f"server/tasks/{task_id}.json"
            if arcname in files:
                continue
            files[arcname] = http_get(f"/avatars/tasks/{task_id}")
    return files


_INSTALL_TARGET_TEMPLATES = tuple(template for _, template in _PLATFORM_INSTALL_TARGETS)


def collect_local_files(
    home: Path, card_slug: str, role_slugs: list[str], install_home: Path | None = None
) -> dict[str, bytes]:
    """Return {arcname: raw_bytes} for whichever install targets exist, arcname mirroring the
    path relative to its own root (home for the profile, install_home for install targets) so
    restore_avatar.py can write it back unchanged. install_home defaults to home -- pass it
    separately when the platform subagent files were installed into a project directory instead
    of the profile's home (e.g. a project-scoped Claude Code install)."""
    install_home = install_home or home
    files: dict[str, bytes] = {}

    def _add(root: Path, path: Path) -> None:
        if path.exists():
            arcname = "local/" + path.relative_to(root).as_posix()
            files[arcname] = path.read_bytes()

    _add(home, home / ".agent-factory" / "avatars" / card_slug / "profile.md")
    _add(home, home / ".agent-factory" / "avatars" / card_slug / "decisions.md")
    for role_slug in role_slugs:
        name = f"{card_slug}-{role_slug}"
        for template in _INSTALL_TARGET_TEMPLATES:
            _add(install_home, install_home / template.format(name=name))
    return files


def backup(
    *,
    output: Path,
    scope: Scope = "both",
    http_get: HttpGet | None = None,
    card_id: str | None = None,
    home: Path | None = None,
    install_home: Path | None = None,
    card_slug: str | None = None,
    role_slugs: list[str] | None = None,
) -> Path:
    files: dict[str, bytes] = {}
    if scope in ("server", "both"):
        if http_get is None or card_id is None:
            raise ValueError("server scope requires http_get and card_id")
        files.update(fetch_server_snapshot(http_get, card_id))
    if scope in ("local", "both"):
        if home is None or card_slug is None:
            raise ValueError("local scope requires home and card_slug")
        files.update(collect_local_files(home, card_slug, role_slugs or [], install_home=install_home))

    manifest = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "card_id": card_id,
        "card_slug": card_slug,
        # Recorded so a later restore can refuse to silently default --install-home to --home
        # when this backup was captured with a distinct one (see restore_avatar.py). None means
        # install_home was not explicitly given at backup time -- restore may default freely.
        "install_home": str(install_home) if install_home is not None else None,
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
        "--install-home",
        type=Path,
        default=None,
        help="Root to search for installed platform subagent files (--claude/--config/--codex "
        "targets), if different from --home -- e.g. a project-scoped Claude Code install. "
        "Defaults to --home.",
    )
    parser.add_argument("--base-url", default=os.environ.get("AGENT_FACTORY_BASE_URL", DEFAULT_BASE_URL))
    args = parser.parse_args()

    http_get = None
    if args.scope in ("server", "both"):
        api_key = os.environ.get("AGENT_FACTORY_API_KEY")
        if not api_key:
            raise SystemExit("AGENT_FACTORY_API_KEY is required for server scope")
        http_get = default_http_get(args.base_url, api_key)

    # fetch_server_snapshot deliberately propagates the typed errors (it is also used as a
    # library function), so rendering them for a human is this entry point's job -- otherwise a
    # plain 403/timeout reaches the user as a raw traceback.
    try:
        result = backup(
            output=args.output,
            scope=args.scope,
            http_get=http_get,
            card_id=args.card_id,
            home=args.home,
            install_home=args.install_home,
            card_slug=args.card_slug,
            role_slugs=args.role_slugs,
        )
    except ApiError as exc:
        raise SystemExit(f"backup failed: {exc} {exc.body.decode(errors='replace')[:200]}") from exc
    except NetworkError as exc:
        raise SystemExit(f"backup failed: {exc}") from exc
    print(result)


if __name__ == "__main__":
    main()
