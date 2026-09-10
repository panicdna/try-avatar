from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from conftest import load_script

backup_avatar = load_script("backup_avatar")


_CARD_RAW = b'{"id": "card-1", "name": "Weekly Report",  "roles": [{"avatar_role_id": "role-1", "title": "Writer", "task_count": 1}]}'
_ROLE_RAW = b'{"id":   "role-1", "title": "Writer", "tasks": [{"avatar_task_id": "task-1", "title": "Draft"}]}'
_TASK_RAW = b'{"id": "task-1",\n  "title": "Draft"}'


def _fake_http_get(responses: dict[str, bytes]):
    def get(path: str) -> bytes:
        return responses[path]

    return get


def test_fetch_server_snapshot_walks_card_role_task_closure_and_preserves_raw_bytes() -> None:
    http_get = _fake_http_get(
        {
            "/avatars/cards/card-1": _CARD_RAW,
            "/avatars/roles/role-1": _ROLE_RAW,
            "/avatars/tasks/task-1": _TASK_RAW,
        }
    )

    files = backup_avatar.fetch_server_snapshot(http_get, "card-1")

    assert files["server/card.json"] == _CARD_RAW
    assert files["server/roles/role-1.json"] == _ROLE_RAW
    assert files["server/tasks/task-1.json"] == _TASK_RAW


def test_fetch_server_snapshot_dedupes_role_shared_across_the_card(tmp_path: Path) -> None:
    card_raw = b'{"id": "card-1", "name": "Weekly Report", "roles": [{"avatar_role_id": "role-1", "title": "Writer", "task_count": 1}, {"avatar_role_id": "role-1", "title": "Writer", "task_count": 1}]}'
    calls: list[str] = []

    def get(path: str) -> bytes:
        calls.append(path)
        return {"/avatars/cards/card-1": card_raw, "/avatars/roles/role-1": _ROLE_RAW, "/avatars/tasks/task-1": _TASK_RAW}[path]

    files = backup_avatar.fetch_server_snapshot(get, "card-1")

    assert calls.count("/avatars/roles/role-1") == 1
    assert files["server/roles/role-1.json"] == _ROLE_RAW


def test_default_http_get_wraps_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_url_error(*_args: object, **_kwargs: object) -> None:
        raise backup_avatar.urllib.error.URLError("connection refused")

    monkeypatch.setattr(backup_avatar.urllib.request, "urlopen", _raise_url_error)
    get = backup_avatar.default_http_get("https://example.invalid", "key")

    with pytest.raises(backup_avatar.NetworkError):
        get("/avatars/cards/card-1")


def test_collect_local_files_includes_existing_and_skips_missing(tmp_path: Path) -> None:
    profile_dir = tmp_path / ".agent-factory" / "avatars" / "weekly-report"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("profile body", encoding="utf-8")
    claude_dir = tmp_path / ".claude" / "agents" / "agent-factory"
    claude_dir.mkdir(parents=True)
    (claude_dir / "weekly-report-writer.md").write_text("agent body", encoding="utf-8")
    # decisions.md and opencode/codex targets deliberately absent

    files = backup_avatar.collect_local_files(tmp_path, "weekly-report", ["writer"])

    assert files["local/.agent-factory/avatars/weekly-report/profile.md"] == b"profile body"
    assert files["local/.claude/agents/agent-factory/weekly-report-writer.md"] == b"agent body"
    assert not any("decisions.md" in name for name in files)
    assert not any("opencode" in name for name in files)
    assert not any("codex" in name for name in files)


def test_collect_local_files_uses_install_home_for_install_targets(tmp_path: Path) -> None:
    home = tmp_path / "home"
    install_home = tmp_path / "project"
    profile_dir = home / ".agent-factory" / "avatars" / "weekly-report"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("profile body", encoding="utf-8")
    claude_dir = install_home / ".claude" / "agents" / "agent-factory"
    claude_dir.mkdir(parents=True)
    (claude_dir / "weekly-report-writer.md").write_text("agent body", encoding="utf-8")

    files = backup_avatar.collect_local_files(home, "weekly-report", ["writer"], install_home=install_home)

    assert files["local/.agent-factory/avatars/weekly-report/profile.md"] == b"profile body"
    assert files["local/.claude/agents/agent-factory/weekly-report-writer.md"] == b"agent body"


def test_collect_local_files_without_install_home_only_searches_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    install_home = tmp_path / "project"
    profile_dir = home / ".agent-factory" / "avatars" / "weekly-report"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("profile body", encoding="utf-8")
    claude_dir = install_home / ".claude" / "agents" / "agent-factory"
    claude_dir.mkdir(parents=True)
    (claude_dir / "weekly-report-writer.md").write_text("agent body", encoding="utf-8")

    files = backup_avatar.collect_local_files(home, "weekly-report", ["writer"])

    assert "local/.agent-factory/avatars/weekly-report/profile.md" in files
    assert not any("weekly-report-writer.md" in name for name in files)


def test_backup_writes_zip_with_manifest_and_both_scopes(tmp_path: Path) -> None:
    profile_dir = tmp_path / ".agent-factory" / "avatars" / "weekly-report"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("profile body", encoding="utf-8")
    http_get = _fake_http_get(
        {
            "/avatars/cards/card-1": _CARD_RAW,
            "/avatars/roles/role-1": _ROLE_RAW,
            "/avatars/tasks/task-1": _TASK_RAW,
        }
    )
    output = tmp_path / "out" / "weekly-report.zip"

    result = backup_avatar.backup(
        output=output,
        scope="both",
        http_get=http_get,
        card_id="card-1",
        home=tmp_path,
        card_slug="weekly-report",
        role_slugs=["writer"],
    )

    assert result == output
    with zipfile.ZipFile(output) as zf:
        assert zf.read("server/card.json") == _CARD_RAW
        assert zf.read("local/.agent-factory/avatars/weekly-report/profile.md") == b"profile body"
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["scope"] == "both"
        assert manifest["card_id"] == "card-1"
        assert manifest["card_slug"] == "weekly-report"


def test_backup_records_install_home_in_manifest_when_given(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    install_home = tmp_path / "project"
    install_home.mkdir()
    output = tmp_path / "weekly-report.zip"

    backup_avatar.backup(
        output=output, scope="local", http_get=_fake_http_get({}), home=home, install_home=install_home,
        card_slug="weekly-report", role_slugs=[],
    )

    with zipfile.ZipFile(output) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["install_home"] == str(install_home)


def test_backup_records_no_install_home_when_not_given(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    output = tmp_path / "weekly-report.zip"

    backup_avatar.backup(
        output=output, scope="local", http_get=_fake_http_get({}), home=home, card_slug="weekly-report", role_slugs=[],
    )

    with zipfile.ZipFile(output) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["install_home"] is None


def test_backup_forwards_install_home_to_local_collection(tmp_path: Path) -> None:
    home = tmp_path / "home"
    install_home = tmp_path / "project"
    profile_dir = home / ".agent-factory" / "avatars" / "weekly-report"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("profile body", encoding="utf-8")
    claude_dir = install_home / ".claude" / "agents" / "agent-factory"
    claude_dir.mkdir(parents=True)
    (claude_dir / "weekly-report-writer.md").write_text("agent body", encoding="utf-8")
    output = tmp_path / "out" / "weekly-report.zip"

    backup_avatar.backup(
        output=output,
        scope="local",
        http_get=_fake_http_get({}),
        home=home,
        install_home=install_home,
        card_slug="weekly-report",
        role_slugs=["writer"],
    )

    with zipfile.ZipFile(output) as zf:
        assert zf.read("local/.claude/agents/agent-factory/weekly-report-writer.md") == b"agent body"


def test_backup_scope_local_never_calls_http_get(tmp_path: Path) -> None:
    profile_dir = tmp_path / ".agent-factory" / "avatars" / "weekly-report"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("profile body", encoding="utf-8")

    def _unexpected_get(path: str) -> bytes:
        raise AssertionError(f"http_get should not be called for local-only scope: {path}")

    output = tmp_path / "weekly-report.zip"
    backup_avatar.backup(
        output=output,
        scope="local",
        http_get=_unexpected_get,
        home=tmp_path,
        card_slug="weekly-report",
        role_slugs=[],
    )

    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        assert not any(name.startswith("server/") for name in names)


def test_backup_scope_server_requires_no_local_files(tmp_path: Path) -> None:
    card_without_roles = b'{"id": "card-1", "name": "Weekly Report", "roles": []}'
    http_get = _fake_http_get({"/avatars/cards/card-1": card_without_roles})
    output = tmp_path / "weekly-report.zip"

    backup_avatar.backup(output=output, scope="server", http_get=http_get, card_id="card-1")

    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        assert not any(name.startswith("local/") for name in names)


def test_backup_server_scope_without_card_id_raises() -> None:
    with pytest.raises(ValueError, match="card_id"):
        backup_avatar.backup(output=Path("unused.zip"), scope="server", http_get=_fake_http_get({}))


@pytest.mark.parametrize(
    "error",
    [
        backup_avatar.ApiError("GET", "/avatars/cards/card-1", 403, b"forbidden: bad key"),
        backup_avatar.NetworkError("GET", "/avatars/cards/card-1", OSError("connection refused")),
    ],
    ids=["api-error", "network-error"],
)
def test_main_reports_server_failure_as_a_message_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """A server-side HTTP error or a network failure must reach the user as a one-line message."""

    def _raise(*_args: object, **_kwargs: object) -> bytes:
        raise error

    monkeypatch.setattr(backup_avatar, "default_http_get", lambda *_a, **_k: _raise)
    monkeypatch.setenv("AGENT_FACTORY_API_KEY", "key")
    monkeypatch.setattr(
        backup_avatar.sys,
        "argv",
        [
            "backup_avatar.py",
            "--output",
            str(tmp_path / "out.zip"),
            "--scope",
            "server",
            "--card-id",
            "card-1",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        backup_avatar.main()

    assert "backup failed:" in str(exc_info.value)
    assert "/avatars/cards/card-1" in str(exc_info.value)
