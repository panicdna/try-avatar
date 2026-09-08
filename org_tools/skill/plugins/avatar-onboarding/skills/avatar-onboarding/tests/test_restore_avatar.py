from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).parents[1] / "scripts" / "restore_avatar.py"
_SPEC = importlib.util.spec_from_file_location("restore_avatar", _SCRIPT)
assert _SPEC and _SPEC.loader
restore_avatar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(restore_avatar)


def _make_backup_zip(path: Path, *, local_files: dict[str, bytes] | None = None, server: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", "{}")
        for arcname, data in (local_files or {}).items():
            zf.writestr(arcname, data)
        for arcname, data in (server or {}).items():
            zf.writestr(arcname, data)
    return path


def test_restore_local_writes_files_relative_to_home(tmp_path: Path) -> None:
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        local_files={
            "local/.agent-factory/avatars/weekly-report/profile.md": b"profile body",
            "local/.claude/agents/agent-factory/weekly-report-writer.md": b"agent body",
        },
    )
    home = tmp_path / "home"
    home.mkdir()

    written = restore_avatar.restore_local(zip_path, home=home)

    profile = home / ".agent-factory" / "avatars" / "weekly-report" / "profile.md"
    agent = home / ".claude" / "agents" / "agent-factory" / "weekly-report-writer.md"
    assert profile in written and profile.read_bytes() == b"profile body"
    assert agent in written and agent.read_bytes() == b"agent body"


def test_restore_local_refuses_to_overwrite_differing_target(tmp_path: Path) -> None:
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        local_files={"local/.agent-factory/avatars/weekly-report/profile.md": b"frozen body"},
    )
    home = tmp_path / "home"
    target = home / ".agent-factory" / "avatars" / "weekly-report" / "profile.md"
    target.parent.mkdir(parents=True)
    target.write_text("live edited body", encoding="utf-8")

    with pytest.raises(restore_avatar.RestoreConflictError, match="differs"):
        restore_avatar.restore_local(zip_path, home=home)


def test_restore_local_force_overwrites_differing_target(tmp_path: Path) -> None:
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        local_files={"local/.agent-factory/avatars/weekly-report/profile.md": b"frozen body"},
    )
    home = tmp_path / "home"
    target = home / ".agent-factory" / "avatars" / "weekly-report" / "profile.md"
    target.parent.mkdir(parents=True)
    target.write_text("live edited body", encoding="utf-8")

    restore_avatar.restore_local(zip_path, home=home, force=True)

    assert target.read_bytes() == b"frozen body"


_CARD_JSON = json.dumps({"id": "card-1", "name": "Weekly Report", "responsibility": "Ship it", "roles": [{"avatar_role_id": "role-1", "title": "Writer", "task_count": 1}], "manager_emails": []}).encode()
_ROLE_JSON = json.dumps({"id": "role-1", "title": "Writer", "description": "Writes drafts", "tasks": [{"avatar_task_id": "task-1", "title": "Draft"}], "manager_emails": []}).encode()
_TASK_JSON = json.dumps({"id": "task-1", "title": "Draft", "context": None, "text": "Write it", "skills": [], "manager_emails": []}).encode()


def _server_backup_zip(path: Path) -> Path:
    return _make_backup_zip(
        path,
        server={
            "server/card.json": _CARD_JSON,
            "server/roles/role-1.json": _ROLE_JSON,
            "server/tasks/task-1.json": _TASK_JSON,
        },
    )


class _FakeApi:
    """Records calls; GET returns configured status for each id, POST/PATCH always succeed."""

    def __init__(self, existing_ids: set[str]) -> None:
        self.existing_ids = existing_ids
        self.calls: list[tuple[str, str, bytes | None]] = []
        self._next_new_id = 100

    def __call__(self, method: str, path: str, body: bytes | None) -> tuple[int, bytes]:
        self.calls.append((method, path, body))
        if method == "GET":
            item_id = path.rsplit("/", 1)[-1]
            return (200, b"{}") if item_id in self.existing_ids else (404, b"{}")
        if method == "PATCH":
            return 200, b"{}"
        if method == "POST":
            self._next_new_id += 1
            new_id = f"new-{self._next_new_id}"
            return 201, json.dumps({"id": new_id}).encode()
        raise AssertionError(f"unexpected method {method}")


def test_import_to_server_auto_mode_updates_existing_ids(tmp_path: Path) -> None:
    zip_path = _server_backup_zip(tmp_path / "backup.zip")
    api = _FakeApi(existing_ids={"card-1", "role-1", "task-1"})

    report = restore_avatar.import_to_server(zip_path, http_request=api, mode="auto")

    assert report["card"] == {"old_id": "card-1", "new_id": "card-1", "action": "updated"}
    methods_and_paths = [(m, p) for m, p, _ in api.calls]
    assert ("PATCH", "/avatars/tasks/task-1") in methods_and_paths
    assert ("PATCH", "/avatars/roles/role-1") in methods_and_paths
    assert ("PATCH", "/avatars/cards/card-1") in methods_and_paths
    assert not any(m == "POST" for m, _, _ in api.calls)


def test_import_to_server_auto_mode_creates_when_ids_missing(tmp_path: Path) -> None:
    zip_path = _server_backup_zip(tmp_path / "backup.zip")
    api = _FakeApi(existing_ids=set())

    report = restore_avatar.import_to_server(zip_path, http_request=api, mode="auto")

    assert report["card"]["old_id"] == "card-1"
    assert report["card"]["action"] == "created"
    assert report["card"]["new_id"] != "card-1"
    post_paths = [p for m, p, _ in api.calls if m == "POST"]
    assert post_paths == ["/avatars/tasks", "/avatars/roles", "/avatars/cards"]


def test_import_to_server_update_mode_raises_when_id_missing(tmp_path: Path) -> None:
    zip_path = _server_backup_zip(tmp_path / "backup.zip")
    api = _FakeApi(existing_ids=set())

    with pytest.raises(restore_avatar.ApiError):
        restore_avatar.import_to_server(zip_path, http_request=api, mode="update")


def test_import_to_server_create_mode_never_checks_existing_ids(tmp_path: Path) -> None:
    zip_path = _server_backup_zip(tmp_path / "backup.zip")
    api = _FakeApi(existing_ids={"card-1", "role-1", "task-1"})

    report = restore_avatar.import_to_server(zip_path, http_request=api, mode="create")

    assert not any(m == "GET" for m, _, _ in api.calls)
    assert report["card"]["action"] == "created"
