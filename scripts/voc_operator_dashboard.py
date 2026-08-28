#!/usr/bin/env python3
"""VoC Operator 이력 대시보드 — 로컬 전용, 표준 라이브러리만 사용한다.

~/.voc-hub/operator-decisions.jsonl 을 웹 페이지로 열람·검색·수정·삭제한다.
이 파일은 voc-avatar-operator 에이전트가 human-in-the-loop 선례 재사용에
직접 읽는 실제 소스이므로, 수정/삭제는 항상 백업 후에만 실행한다.
"""
from __future__ import annotations

import json
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_JSONL_PATH = Path.home() / ".voc-hub" / "operator-decisions.jsonl"
DEFAULT_PORT = 8765
EDITABLE_FIELDS = (
    "voc_number",
    "decision",
    "trigger_condition",
    "human_instruction",
    "precedent_used",
)


def parse_jsonl(path: Path) -> tuple[list[dict], list[dict]]:
    """JSONL 파일을 파싱한다.

    손상된 줄은 건너뛰고 parse_errors에 {"line_no", "raw"}로 담는다.
    파일이 없으면 (빈 목록, 빈 에러 목록)을 반환한다 — 에러가 아니다
    (아직 판단 이력이 쌓인 적 없는 최초 상태를 표현).
    """
    if not path.exists():
        return [], []
    items: list[dict] = []
    errors: list[dict] = []
    text = path.read_text(encoding="utf-8")
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            items.append(json.loads(raw))
        except json.JSONDecodeError:
            errors.append({"line_no": line_no, "raw": raw})
    return items, errors


class ConflictError(Exception):
    """요청의 original이 현재 파일 내용과 일치하지 않을 때 발생한다."""


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _write_lines(path: Path, lines: list[str]) -> None:
    text = ("\n".join(lines) + "\n") if lines else ""
    path.write_text(text, encoding="utf-8")


def _find_matching_line_index(lines: list[str], original: dict) -> int | None:
    for i, raw in enumerate(lines):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if parsed == original:
            return i
    return None


def write_backup(path: Path) -> Path | None:
    """현재 파일을 <path>.bak-<epoch>로 복사한다.

    원본이 아직 없으면(최초 상태) 백업할 것이 없으므로 None을 반환한다.
    복사 자체가 실패하면(디스크 등) 예외가 그대로 위로 전파된다 — 백업
    없이는 원본을 고치지 않는다는 원칙을 호출자가 지키게 한다.
    """
    if not path.exists():
        return None
    backup_path = path.with_name(f"{path.name}.bak-{int(time.time())}")
    shutil.copy2(path, backup_path)
    return backup_path


def apply_patch(path: Path, original: dict, updated: dict) -> list[dict]:
    lines = _read_lines(path)
    idx = _find_matching_line_index(lines, original)
    if idx is None:
        raise ConflictError("original not found — file changed since it was read")
    write_backup(path)
    merged = dict(original)
    for field in EDITABLE_FIELDS:
        if field in updated:
            merged[field] = updated[field]
    lines[idx] = json.dumps(merged, ensure_ascii=False)
    _write_lines(path, lines)
    items, _ = parse_jsonl(path)
    return items


def apply_delete(path: Path, original: dict) -> list[dict]:
    lines = _read_lines(path)
    idx = _find_matching_line_index(lines, original)
    if idx is None:
        raise ConflictError("original not found — file changed since it was read")
    write_backup(path)
    del lines[idx]
    _write_lines(path, lines)
    items, _ = parse_jsonl(path)
    return items


DASHBOARD_HTML = "<html><body>placeholder</body></html>"  # Task 4에서 실제 내용으로 교체


def make_handler(jsonl_path: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, status: int, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw or b"{}")

        def _conflict(self) -> None:
            self._send_json(409, {
                "error": "conflict",
                "message": "파일이 변경되었습니다. 새로고침 후 다시 시도하세요",
            })

        def _bad_request(self, message: str) -> None:
            self._send_json(400, {"error": "bad_request", "message": message})

        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler 관례)
            if self.path == "/":
                self._send_html(200, DASHBOARD_HTML)
                return
            if self.path == "/api/entries":
                items, errors = parse_jsonl(jsonl_path)
                self._send_json(200, {"items": items, "parse_errors": errors})
                return
            self._send_json(404, {"error": "not_found"})

        def do_PATCH(self) -> None:  # noqa: N802
            if self.path != "/api/entries":
                self._send_json(404, {"error": "not_found"})
                return
            try:
                body = self._read_json_body()
                original = body["original"]
            except json.JSONDecodeError:
                self._bad_request("요청 본문이 올바른 JSON이 아닙니다")
                return
            except KeyError:
                self._bad_request("'original' 필드가 필요합니다")
                return
            try:
                items = apply_patch(jsonl_path, original, body.get("updated", {}))
            except ConflictError:
                self._conflict()
                return
            self._send_json(200, {"items": items})

        def do_DELETE(self) -> None:  # noqa: N802
            if self.path != "/api/entries":
                self._send_json(404, {"error": "not_found"})
                return
            try:
                body = self._read_json_body()
                original = body["original"]
            except json.JSONDecodeError:
                self._bad_request("요청 본문이 올바른 JSON이 아닙니다")
                return
            except KeyError:
                self._bad_request("'original' 필드가 필요합니다")
                return
            try:
                items = apply_delete(jsonl_path, original)
            except ConflictError:
                self._conflict()
                return
            self._send_json(200, {"items": items})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # 터미널 스팸 방지 — 필요하면 나중에 로깅으로 바꾼다

    return Handler


def build_server(jsonl_path: Path, port: int) -> ThreadingHTTPServer:
    """포트가 이미 쓰이는 중이면 OSError를 그대로 전파한다 — 호출자(main)가
    "이미 실행 중일 수 있음" 메시지로 바꿔 보여준다."""
    handler_cls = make_handler(jsonl_path)
    return ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
