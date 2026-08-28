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
from pathlib import Path

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
