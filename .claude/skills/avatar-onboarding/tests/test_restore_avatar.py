from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from conftest import load_script

restore_avatar = load_script("restore_avatar")


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


def test_restore_local_writes_install_targets_relative_to_install_home(tmp_path: Path) -> None:
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        local_files={
            "local/.agent-factory/avatars/weekly-report/profile.md": b"profile body",
            "local/.claude/agents/agent-factory/weekly-report-writer.md": b"agent body",
        },
    )
    home = tmp_path / "home"
    home.mkdir()
    install_home = tmp_path / "project"
    install_home.mkdir()

    written = restore_avatar.restore_local(zip_path, home=home, install_home=install_home)

    profile = home / ".agent-factory" / "avatars" / "weekly-report" / "profile.md"
    agent = install_home / ".claude" / "agents" / "agent-factory" / "weekly-report-writer.md"
    assert profile in written and profile.read_bytes() == b"profile body"
    assert agent in written and agent.read_bytes() == b"agent body"
    assert not (home / ".claude").exists()


def test_restore_local_defaults_install_home_to_home(tmp_path: Path) -> None:
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        local_files={"local/.claude/agents/agent-factory/weekly-report-writer.md": b"agent body"},
    )
    home = tmp_path / "home"
    home.mkdir()

    restore_avatar.restore_local(zip_path, home=home)

    agent = home / ".claude" / "agents" / "agent-factory" / "weekly-report-writer.md"
    assert agent.read_bytes() == b"agent body"


def test_restore_local_rejects_path_traversal_entry(tmp_path: Path) -> None:
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        local_files={"local/../../../../tmp/evil.md": b"malicious"},
    )
    home = tmp_path / "home"
    home.mkdir()

    with pytest.raises(restore_avatar.RestoreConflictError, match="escapes"):
        restore_avatar.restore_local(zip_path, home=home)


def test_restore_local_rejects_absolute_path_entry(tmp_path: Path) -> None:
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        local_files={"local//etc/evil.md": b"malicious"},
    )
    home = tmp_path / "home"
    home.mkdir()

    with pytest.raises(restore_avatar.RestoreConflictError, match="escapes"):
        restore_avatar.restore_local(zip_path, home=home)


def test_restore_local_conflict_leaves_earlier_entries_unwritten(tmp_path: Path) -> None:
    """A conflict on one entry must be caught before any entry is written, not partway through."""
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        local_files={
            "local/.agent-factory/avatars/weekly-report/profile.md": b"frozen profile",
            "local/.claude/agents/agent-factory/weekly-report-writer.md": b"frozen agent",
        },
    )
    home = tmp_path / "home"
    live_target = home / ".claude" / "agents" / "agent-factory" / "weekly-report-writer.md"
    live_target.parent.mkdir(parents=True)
    live_target.write_text("live edited body", encoding="utf-8")

    with pytest.raises(restore_avatar.RestoreConflictError):
        restore_avatar.restore_local(zip_path, home=home)

    profile = home / ".agent-factory" / "avatars" / "weekly-report" / "profile.md"
    assert not profile.exists()


def test_restore_local_requires_install_home_when_backup_used_one(tmp_path: Path) -> None:
    zip_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"install_home": "/some/project"}))
    home = tmp_path / "home"
    home.mkdir()

    with pytest.raises(restore_avatar.RestoreConflictError, match="install-home"):
        restore_avatar.restore_local(zip_path, home=home)


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

    with pytest.raises(restore_avatar.ImportPartialFailure) as exc_info:
        restore_avatar.import_to_server(zip_path, http_request=api, mode="update")
    assert isinstance(exc_info.value.cause, restore_avatar.ApiError)


def test_import_to_server_create_mode_never_checks_existing_ids(tmp_path: Path) -> None:
    zip_path = _server_backup_zip(tmp_path / "backup.zip")
    api = _FakeApi(existing_ids={"card-1", "role-1", "task-1"})

    report = restore_avatar.import_to_server(zip_path, http_request=api, mode="create")

    assert not any(m == "GET" for m, _, _ in api.calls)
    assert report["card"]["action"] == "created"


_SHARED_TASK_CARD_JSON = json.dumps(
    {
        "id": "card-1",
        "name": "Weekly Report",
        "roles": [
            {"avatar_role_id": "role-1", "title": "Writer", "task_count": 1},
            {"avatar_role_id": "role-2", "title": "Editor", "task_count": 1},
        ],
        "manager_emails": [],
    }
).encode()
_SHARED_ROLE_1_JSON = json.dumps(
    {"id": "role-1", "title": "Writer", "description": "Writes drafts", "tasks": [{"avatar_task_id": "task-1", "title": "Draft"}], "manager_emails": []}
).encode()
_SHARED_ROLE_2_JSON = json.dumps(
    {"id": "role-2", "title": "Editor", "description": "Edits drafts", "tasks": [{"avatar_task_id": "task-1", "title": "Draft"}], "manager_emails": []}
).encode()


def test_import_to_server_resolves_task_shared_across_roles_once(tmp_path: Path) -> None:
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        server={
            "server/card.json": _SHARED_TASK_CARD_JSON,
            "server/roles/role-1.json": _SHARED_ROLE_1_JSON,
            "server/roles/role-2.json": _SHARED_ROLE_2_JSON,
            "server/tasks/task-1.json": _TASK_JSON,
        },
    )
    api = _FakeApi(existing_ids=set())

    report = restore_avatar.import_to_server(zip_path, http_request=api, mode="auto")

    post_paths = [p for m, p, _ in api.calls if m == "POST"]
    assert post_paths.count("/avatars/tasks") == 1
    assert len(report["tasks"]) == 1
    role_task_ids = {r["new_id"] for r in report["roles"]}
    assert len(role_task_ids) == 2  # both roles still created distinctly
    assert len({t["new_id"] for t in report["tasks"]}) == 1


def test_import_to_server_auto_mode_raises_on_ambiguous_get_failure(tmp_path: Path) -> None:
    """A 403/5xx on the existence check must not be treated as 'doesn't exist' -- only a genuine
    404 may fall back to create; anything else is an ambiguous failure that must raise."""
    zip_path = _server_backup_zip(tmp_path / "backup.zip")

    def flaky_api(method: str, path: str, body: bytes | None) -> tuple[int, bytes]:
        if method == "GET":
            return 500, b"internal error"
        raise AssertionError(f"unexpected method {method} after an ambiguous GET failure")

    with pytest.raises(restore_avatar.ImportPartialFailure) as exc_info:
        restore_avatar.import_to_server(zip_path, http_request=flaky_api, mode="auto")
    assert isinstance(exc_info.value.cause, restore_avatar.ApiError)


def test_task_and_role_payload_forward_team_id() -> None:
    task_payload = restore_avatar._task_payload({"title": "Draft", "team_id": "team-1"})
    role_payload = restore_avatar._role_payload({"title": "Writer", "description": "Writes drafts", "team_id": "team-1"}, [])
    assert task_payload["team_id"] == "team-1"
    assert role_payload["team_id"] == "team-1"


def test_main_target_both_restores_locally_even_when_server_import_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--target both`: the local step only reads the zip, so a failed server import must not
    cancel it -- the command still exits non-zero afterwards."""
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        server={
            "server/card.json": _CARD_JSON,
            "server/roles/role-1.json": _ROLE_JSON,
            "server/tasks/task-1.json": _TASK_JSON,
        },
        local_files={"local/.agent-factory/avatars/weekly-report/profile.md": b"profile body"},
    )
    home = tmp_path / "home"

    def failing_http_request(*_args: object, **_kwargs: object) -> restore_avatar.HttpRequest:
        return lambda _method, _path, _body: (500, b"internal error")

    monkeypatch.setattr(restore_avatar, "default_http_request", failing_http_request)
    monkeypatch.setenv("AGENT_FACTORY_API_KEY", "key")
    monkeypatch.setattr(
        restore_avatar.sys,
        "argv",
        ["restore_avatar.py", "--zip", str(zip_path), "--target", "both", "--home", str(home), "--confirm"],
    )

    with pytest.raises(SystemExit) as exc_info:
        restore_avatar.main()

    assert (home / ".agent-factory" / "avatars" / "weekly-report" / "profile.md").read_bytes() == b"profile body"
    assert "failed partway through" in str(exc_info.value)


def test_main_reports_local_conflict_as_a_message_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same contract as backup_avatar.py's main(): a refused local restore is a message."""
    zip_path = _make_backup_zip(
        tmp_path / "backup.zip",
        local_files={"local/.agent-factory/avatars/weekly-report/profile.md": b"from backup"},
    )
    home = tmp_path / "home"
    existing = home / ".agent-factory" / "avatars" / "weekly-report" / "profile.md"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"locally edited")

    monkeypatch.setattr(
        restore_avatar.sys,
        "argv",
        ["restore_avatar.py", "--zip", str(zip_path), "--target", "local", "--home", str(home), "--confirm"],
    )

    with pytest.raises(SystemExit) as exc_info:
        restore_avatar.main()

    assert "local restore refused:" in str(exc_info.value)
    assert existing.read_bytes() == b"locally edited"


def test_default_http_request_wraps_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_url_error(*_args: object, **_kwargs: object) -> None:
        raise restore_avatar.urllib.error.URLError("connection refused")

    monkeypatch.setattr(restore_avatar.urllib.request, "urlopen", _raise_url_error)
    request = restore_avatar.default_http_request("https://example.invalid", "key")

    with pytest.raises(restore_avatar.NetworkError):
        request("GET", "/avatars/cards/card-1", None)
