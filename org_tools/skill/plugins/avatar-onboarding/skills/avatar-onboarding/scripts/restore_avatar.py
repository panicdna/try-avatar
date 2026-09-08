#!/usr/bin/env python3
"""Reproduce a backup_avatar.py *.zip on the server (import) and/or on local disk (restore).

Both directions replay the frozen title/text/context/name/responsibility values unchanged --
only the envelope (which endpoint, create vs patch, which IDs) differs from the raw bytes
captured by backup_avatar.py, never the field values themselves.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Literal

Target = Literal["server", "local", "both"]
Mode = Literal["auto", "create", "update"]
HttpRequest = Callable[[str, str, bytes | None], tuple[int, bytes]]


class RestoreConflictError(RuntimeError):
    """An existing local target differs from the frozen backup content."""


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: bytes) -> None:
        super().__init__(f"{method} {path} -> {status}")
        self.status = status
        self.body = body


def default_http_request(base_url: str, api_key: str) -> HttpRequest:
    def request(method: str, path: str, body: bytes | None) -> tuple[int, bytes]:
        headers = {"Authorization": f"Bearer {api_key}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{base_url}{path}", data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    return request


def _write_local(path: Path, data: bytes, *, force: bool) -> None:
    if path.exists() and not force and path.read_bytes() != data:
        raise RestoreConflictError(f"local target differs from backup: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


_INSTALL_TARGET_PREFIXES = (
    ".claude/agents/agent-factory/",
    ".config/opencode/agents/agent-factory/",
    ".codex/agents/",
)


def restore_local(zip_path: Path, *, home: Path, install_home: Path | None = None, force: bool = False) -> list[Path]:
    """Write back every local/ entry in the backup. Entries under one of the known install-target
    paths (.claude/agents/agent-factory/, ...) are rooted at install_home (defaults to home) so a
    project-scoped install can be restored to the same project directory it came from; everything
    else (profile.md, decisions.md) is rooted at home, mirroring backup_avatar.py's split."""
    install_home = install_home or home
    written: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.startswith("local/")]
        for name in names:
            data = zf.read(name)
            rel = name[len("local/") :]
            root = install_home if rel.startswith(_INSTALL_TARGET_PREFIXES) else home
            target = root / rel
            _write_local(target, data, force=force)
            written.append(target)
    return written


def _load_server_snapshot(zip_path: Path) -> dict[str, object]:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if "server/card.json" not in names:
            raise ValueError(f"{zip_path} has no server/card.json snapshot")
        card = json.loads(zf.read("server/card.json"))
        roles: dict[str, dict] = {}
        tasks: dict[str, dict] = {}
        for name in names:
            if name.startswith("server/roles/") and name.endswith(".json"):
                role = json.loads(zf.read(name))
                roles[role["id"]] = role
            elif name.startswith("server/tasks/") and name.endswith(".json"):
                task = json.loads(zf.read(name))
                tasks[task["id"]] = task
    return {"card": card, "roles": roles, "tasks": tasks}


def _task_payload(task: dict) -> dict:
    return {
        "title": task["title"],
        "context": task.get("context"),
        "text": task.get("text"),
        "skills": [
            {"skill_id": s["skill_id"], "component_key": s.get("component_key")} for s in task.get("skills", [])
        ],
        "manager_emails": task.get("manager_emails", []),
    }


def _role_payload(role: dict, task_ids: list[str]) -> dict:
    return {
        "title": role["title"],
        "description": role["description"],
        "task_ids": task_ids,
        "manager_emails": role.get("manager_emails", []),
    }


def _card_payload(card: dict, role_ids: list[str]) -> dict:
    return {
        "name": card["name"],
        "responsibility": card.get("responsibility"),
        "role_ids": role_ids,
        "manager_emails": card.get("manager_emails", []),
    }


def _resolve_or_create(
    *, http_request: HttpRequest, mode: Mode, existing_id: str, get_path: str, create_path: str, payload: dict
) -> tuple[str, str]:
    """Returns (id_to_use, action). Tries PATCH-in-place for auto/update, else POSTs a new one."""
    body = json.dumps(payload).encode()
    if mode in ("auto", "update"):
        status, _ = http_request("GET", get_path, None)
        if status == 200:
            patch_status, patch_body = http_request("PATCH", get_path, body)
            if patch_status not in (200, 204):
                raise ApiError("PATCH", get_path, patch_status, patch_body)
            return existing_id, "updated"
        if mode == "update":
            raise ApiError("GET", get_path, status, b"")
    status, resp_body = http_request("POST", create_path, body)
    if status != 201:
        raise ApiError("POST", create_path, status, resp_body)
    return json.loads(resp_body)["id"], "created"


def import_to_server(zip_path: Path, *, http_request: HttpRequest, mode: Mode = "auto") -> dict[str, object]:
    snapshot = _load_server_snapshot(zip_path)
    card, roles, tasks = snapshot["card"], snapshot["roles"], snapshot["tasks"]
    assert isinstance(card, dict) and isinstance(roles, dict) and isinstance(tasks, dict)
    report: dict[str, object] = {"tasks": [], "roles": [], "card": {}}

    def do_task(task_id: str) -> str:
        new_id, action = _resolve_or_create(
            http_request=http_request,
            mode=mode,
            existing_id=task_id,
            get_path=f"/avatars/tasks/{task_id}",
            create_path="/avatars/tasks",
            payload=_task_payload(tasks[task_id]),
        )
        report["tasks"].append({"old_id": task_id, "new_id": new_id, "action": action})
        return new_id

    def do_role(role_id: str) -> str:
        role = roles[role_id]
        new_task_ids = [do_task(t["avatar_task_id"]) for t in role.get("tasks", [])]
        new_id, action = _resolve_or_create(
            http_request=http_request,
            mode=mode,
            existing_id=role_id,
            get_path=f"/avatars/roles/{role_id}",
            create_path="/avatars/roles",
            payload=_role_payload(role, new_task_ids),
        )
        report["roles"].append({"old_id": role_id, "new_id": new_id, "action": action})
        return new_id

    card_id = card["id"]
    new_role_ids = [do_role(r["avatar_role_id"]) for r in card.get("roles", [])]
    new_card_id, action = _resolve_or_create(
        http_request=http_request,
        mode=mode,
        existing_id=card_id,
        get_path=f"/avatars/cards/{card_id}",
        create_path="/avatars/cards",
        payload=_card_payload(card, new_role_ids),
    )
    report["card"] = {"old_id": card_id, "new_id": new_card_id, "action": action}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True, dest="zip_path")
    parser.add_argument("--target", choices=["server", "local", "both"], default="both")
    parser.add_argument("--mode", choices=["auto", "create", "update"], default="auto")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument(
        "--install-home",
        type=Path,
        default=None,
        help="Root to restore installed platform subagent files under, if different from --home "
        "-- e.g. a project-scoped Claude Code install. Defaults to --home.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--confirm", action="store_true", help="Actually write/upload. Without it, only preview.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AGENT_FACTORY_BASE_URL", "https://agent.samsungds.net:3355/api/v1/agent"),
    )
    args = parser.parse_args()

    if not args.confirm:
        with zipfile.ZipFile(args.zip_path) as zf:
            names = zf.namelist()
        if args.target in ("server", "both"):
            print("[dry-run] would import to server:", [n for n in names if n.startswith("server/")])
        if args.target in ("local", "both"):
            print("[dry-run] would restore locally:", [n for n in names if n.startswith("local/")])
        print("Pass --confirm to actually apply these changes.")
        return

    if args.target in ("server", "both"):
        api_key = os.environ.get("AGENT_FACTORY_API_KEY")
        if not api_key:
            raise SystemExit("AGENT_FACTORY_API_KEY is required for server target")
        report = import_to_server(
            args.zip_path, http_request=default_http_request(args.base_url, api_key), mode=args.mode
        )
        print(json.dumps(report, indent=2))
    if args.target in ("local", "both"):
        written = restore_local(args.zip_path, home=args.home, install_home=args.install_home, force=args.force)
        for path in written:
            print(path)


if __name__ == "__main__":
    main()
