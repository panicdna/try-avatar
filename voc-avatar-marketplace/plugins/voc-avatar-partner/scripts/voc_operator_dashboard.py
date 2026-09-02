#!/usr/bin/env python3
"""VoC Operator 이력 대시보드 — 로컬 전용, 표준 라이브러리만 사용한다.

~/.voc-hub-<slug>/operator-decisions.jsonl 을 웹 페이지로 열람·검색·수정·삭제한다.
<slug>는 실행 시점의 프로젝트 경로(git 레포 루트)로부터 결정론적으로 계산되어,
설치(프로젝트)마다 별도 디렉터리를 쓴다 — compute_voc_hub_slug 참고.
이 파일은 voc-avatar-operator 에이전트가 human-in-the-loop 선례 재사용에
직접 읽는 실제 소스이므로, 수정/삭제는 항상 백업 후에만 실행한다.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _sanitize_slug_component(name: str) -> str:
    """파일시스템에 안전한 문자(영숫자·_·-)만 남기고 나머지는 '-'로 치환한다."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", name) or "root"


def compute_voc_hub_slug(root: Path) -> str:
    """프로젝트 절대경로로부터 결정론적 slug를 계산한다.

    같은 경로는 항상 같은 slug를 낳는다 — 순번 할당이나 마커 파일 없이도
    설치(프로젝트)마다 ~/.voc-hub-<slug>/ 가 자동으로 갈린다. 반대로 경로가
    바뀌면(레포 이동, 워크트리 등) slug도 바뀐다 — 이전 데이터는 따라오지
    않는다(voc-avatar-partner README §6와 같은 종류의 트레이드오프).
    """
    resolved = Path(root).resolve()
    name = _sanitize_slug_component(resolved.name or "root")
    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:6]
    return f"{name}-{digest}"


def voc_hub_dir_for(root: Path) -> Path:
    """root 프로젝트가 쓸 ~/.voc-hub-<slug>/ 경로를 계산한다 (생성은 하지 않는다)."""
    return Path.home() / f".voc-hub-{compute_voc_hub_slug(root)}"


def find_project_root(start: Path) -> Path:
    """git 레포 루트를 찾는다. git 레포가 아니거나 git이 없으면 start를 그대로 반환한다."""
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return Path(start).resolve()
    if result.returncode != 0:
        return Path(start).resolve()
    return Path(result.stdout.strip()).resolve()


def resolve_voc_hub_dir(start: Path | None = None) -> Path:
    """start(기본: 현재 작업 디렉터리) 기준으로 이 설치가 쓸 ~/.voc-hub-<slug>/ 를 계산한다."""
    start = Path(start) if start is not None else Path.cwd()
    return voc_hub_dir_for(find_project_root(start))


DEFAULT_JSONL_PATH = resolve_voc_hub_dir() / "operator-decisions.jsonl"
DEFAULT_HANDOFF_DIR = resolve_voc_hub_dir() / "handoff"
DEFAULT_PORT = 8765
BODY_START_MARKER = "--- 본문 시작 ---"
BODY_END_MARKER = "--- 본문 끝 ---"
HANDOFF_BODY_PREVIEW_LEN = 200
EDITABLE_FIELDS = (
    "voc_number",
    "decision",
    "trigger_condition",
    "human_instruction",
    "precedent_used",
    "evidence",
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
    # splitlines()가 아니라 split("\n")을 쓴다: splitlines()는 \x0b, \x0c, \x1c-\x1e,
    # \x85,  ,   같은 유니코드 줄바꿈 문자에서도 쪼갠다. json.dumps(...,
    # ensure_ascii=False)는 이런 문자를 문자열 값 안에 그대로 담을 수 있으므로, splitlines()를
    # 쓰면 유효한 한 줄짜리 JSON이 두 조각으로 쪼개져 둘 다 파싱 실패로 오분류된다.
    for line_no, raw in enumerate(text.split("\n"), start=1):
        if not raw.strip():
            continue
        try:
            items.append(json.loads(raw))
        except json.JSONDecodeError:
            errors.append({"line_no": line_no, "raw": raw})
    return items, errors


def parse_handoff_file(path: Path) -> dict:
    """핸드오프 파일(~/.voc-hub-<slug>/handoff/<voc_number>.md) 하나를 요약 정보로 만든다.

    형식은 README.md §5.1 참고: `compose: <reply|internal>` 한 줄 + 구분자
    (BODY_START_MARKER/BODY_END_MARKER)로 감싼 본문. compose 줄이나 구분자가
    없는 파일이 와도 에러를 내지 않고 전체 텍스트를 본문으로 취급한다 —
    이 대시보드는 읽기 전용 현황판이지 형식 검증기가 아니다.
    """
    text = path.read_text(encoding="utf-8")
    compose_match = re.search(r"^compose:\s*(.*)$", text, re.MULTILINE)
    compose = compose_match.group(1).strip() if compose_match else None

    body = text
    start = text.find(BODY_START_MARKER)
    end = text.find(BODY_END_MARKER)
    if start != -1 and end != -1 and end > start:
        body = text[start + len(BODY_START_MARKER):end].strip("\n")

    stat = path.stat()
    return {
        "voc_number": path.stem,
        "compose": compose,
        "body": body,
        "body_preview": body[:HANDOFF_BODY_PREVIEW_LEN],
        "body_truncated": len(body) > HANDOFF_BODY_PREVIEW_LEN,
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "size": stat.st_size,
    }


def list_handoff_files(dir_path: Path) -> list[dict]:
    """디렉터리에 지금 실제로 남아 있는 핸드오프 파일만 나열한다.

    지운 파일은 당연히 다시 나타나지 않는다 — 별도 삭제 이력을 두지 않고
    파일시스템 상태를 그대로 신뢰한다(README.md §5.1: 이 파일은 최신
    스냅샷일 뿐 감사 기록이 아니다). 디렉터리가 아직 없으면(핸드오프가 한
    번도 생긴 적 없는 최초 상태) 에러가 아니라 빈 목록을 반환한다.
    """
    if not dir_path.exists():
        return []
    items = []
    for entry in dir_path.glob("*.md"):
        if not entry.is_file():
            continue
        try:
            items.append(parse_handoff_file(entry))
        except OSError:
            continue
    items.sort(key=lambda item: item["mtime"], reverse=True)
    return items


class ConflictError(Exception):
    """요청의 original이 현재 파일 내용과 일치하지 않을 때 발생한다."""


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    # splitlines() 대신 split("\n") — 이유는 parse_jsonl 위 주석 참고.
    # split("\n")은 _write_lines가 항상 붙이는 트레일링 "\n" 때문에 마지막에 빈
    # 문자열 원소가 하나 남으므로, 그걸 제거해야 _write_lines가 다시 저장할 때마다
    # 빈 줄이 누적되지 않는다.
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


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
    # time.time_ns() — int(time.time())는 초 단위라 같은 초 안의 두 번째 쓰기가
    # 첫 백업을 덮어써 버린다(spec: 쓰기마다 백업 1개).
    backup_path = path.with_name(f"{path.name}.bak-{time.time_ns()}")
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


DASHBOARD_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>VoC Operator 이력 대시보드</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }
  h1 { font-size: 1.25rem; }
  #search-input { padding: 0.4rem; width: 20rem; margin-bottom: 1rem; }
  #parse-error-banner { display: none; background: #fff3cd; border: 1px solid #ffca2c;
                         padding: 0.6rem; margin-bottom: 1rem; border-radius: 4px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ddd; padding: 0.5rem; vertical-align: top; text-align: left; }
  th { background: #f5f5f5; }
  td textarea { width: 100%; box-sizing: border-box; }
  .row-actions button { margin-right: 0.4rem; }
  .ts-cell { white-space: nowrap; color: #666; font-size: 0.85em; }
  #source-path, #handoff-dir { color: #666; font-size: 0.85em; margin-bottom: 0.5rem; }
  #source-path code, #handoff-dir code { background: #f5f5f5; padding: 0.1rem 0.3rem; border-radius: 3px; }
  #source-path-input, #handoff-dir-input { font-family: monospace; }
  #source-path-status.ok, #handoff-dir-status.ok { color: #1a7f37; }
  #source-path-status.error, #handoff-dir-status.error { color: #c0392b; }
  h2 { font-size: 1.05rem; margin-top: 2.5rem; }
  #handoff-refresh { margin-bottom: 0.5rem; }
  .handoff-body-cell button { margin-top: 0.3rem; }
  .handoff-empty-cell { color: #666; }
</style>
</head>
<body>
<div id="source-path">
  참고 파일:
  <input id="source-path-input" type="text" value="__VOC_JSONL_PATH__" size="60">
  <button id="source-path-open">열기</button>
  <span id="source-path-status"></span>
</div>
<h1>VoC Operator 이력 대시보드</h1>
<div id="parse-error-banner"></div>
<input id="search-input" type="text" placeholder="voc_number 또는 decision 검색">
<table id="entries-table">
  <thead>
    <tr>
      <th>ts</th><th>voc_number</th><th>decision</th><th>trigger_condition</th>
      <th>human_instruction</th><th>precedent_used</th><th>evidence</th><th></th>
    </tr>
  </thead>
  <tbody id="entries-body"></tbody>
</table>

<datalist id="decision-options">
  <option value="reply"><option value="internal">
  <option value="resolver_delegate"><option value="hold">
</datalist>

<h2>핸드오프 파일 현황</h2>
<div id="handoff-dir">
  디렉터리:
  <input id="handoff-dir-input" type="text" value="__VOC_HANDOFF_DIR__" size="60">
  <button id="handoff-dir-open">열기</button>
  <span id="handoff-dir-status"></span>
</div>
<button id="handoff-refresh">새로고침</button>
<table id="handoff-table">
  <thead>
    <tr><th>voc_number</th><th>compose</th><th>수정 시각</th><th>크기</th><th>본문</th></tr>
  </thead>
  <tbody id="handoff-body"></tbody>
</table>

<script>
const EDITABLE_FIELDS = ["voc_number", "decision", "trigger_condition", "human_instruction", "precedent_used", "evidence"];
let allItems = [];

async function loadEntries() {
  const res = await fetch("/api/entries");
  const data = await res.json();
  allItems = data.items.slice().sort((a, b) => (a.ts < b.ts ? 1 : -1));
  renderParseErrorBanner(data.parse_errors);
  renderTable(allItems);
}

function renderParseErrorBanner(errors) {
  const banner = document.getElementById("parse-error-banner");
  if (errors && errors.length > 0) {
    banner.style.display = "block";
    banner.textContent = errors.length + "개 줄 파싱 실패, 무시됨 — 원본 파일에서 직접 확인하세요.";
  } else {
    banner.style.display = "none";
  }
}

function matchesSearch(item, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  return (item.voc_number || "").toLowerCase().includes(q)
      || (item.decision || "").toLowerCase().includes(q);
}

function renderTable(items) {
  const query = document.getElementById("search-input").value;
  const tbody = document.getElementById("entries-body");
  tbody.innerHTML = "";
  items.filter(item => matchesSearch(item, query)).forEach(item => {
    tbody.appendChild(renderRow(item));
  });
}

function renderRow(item) {
  const tr = document.createElement("tr");
  const tsCell = document.createElement("td");
  tsCell.className = "ts-cell";
  tsCell.textContent = item.ts || "";
  tr.appendChild(tsCell);

  const editors = {};
  EDITABLE_FIELDS.forEach(field => {
    const td = document.createElement("td");
    const span = document.createElement("span");
    span.textContent = item[field] || "";
    td.appendChild(span);
    editors[field] = { td, span };
    tr.appendChild(td);
  });

  const actionsTd = document.createElement("td");
  actionsTd.className = "row-actions";
  const editBtn = document.createElement("button");
  editBtn.textContent = "수정";
  const deleteBtn = document.createElement("button");
  deleteBtn.textContent = "삭제";
  actionsTd.appendChild(editBtn);
  actionsTd.appendChild(deleteBtn);
  tr.appendChild(actionsTd);

  editBtn.addEventListener("click", () => {
    if (editBtn.textContent === "수정") {
      EDITABLE_FIELDS.forEach(field => {
        const { td, span } = editors[field];
        td.innerHTML = "";
        let control;
        if (field === "decision") {
          control = document.createElement("input");
          control.type = "text";
          control.setAttribute("list", "decision-options");
          control.value = item[field] || "";
        } else {
          control = document.createElement("textarea");
          control.value = item[field] || "";
        }
        td.appendChild(control);
        editors[field].textarea = control;
      });
      editBtn.textContent = "저장";
    } else {
      const updated = {};
      EDITABLE_FIELDS.forEach(field => {
        updated[field] = editors[field].textarea.value;
      });
      savePatch(item, updated);
    }
  });

  deleteBtn.addEventListener("click", () => {
    if (confirm("이 항목은 향후 자동 판단의 선례로 쓰일 수 있습니다. 정말 삭제할까요?")) {
      deleteEntry(item);
    }
  });

  return tr;
}

async function reportFailure(res) {
  let message = "요청이 실패했습니다 (HTTP " + res.status + ")";
  try {
    const errorBody = await res.json();
    if (errorBody && errorBody.message) {
      message = errorBody.message;
    }
  } catch (e) {
    // 본문이 JSON이 아니면 기본 메시지를 그대로 쓴다
  }
  alert(message);
}

async function savePatch(original, updated) {
  const res = await fetch("/api/entries", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ original, updated }),
  });
  if (res.status === 409) {
    alert("파일이 변경되었습니다. 새로고침 후 다시 시도하세요");
    return;
  }
  if (!res.ok) {
    await reportFailure(res);
    return;
  }
  await loadEntries();
}

async function deleteEntry(original) {
  const res = await fetch("/api/entries", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ original }),
  });
  if (res.status === 409) {
    alert("파일이 변경되었습니다. 새로고침 후 다시 시도하세요");
    return;
  }
  if (!res.ok) {
    await reportFailure(res);
    return;
  }
  await loadEntries();
}

document.getElementById("search-input").addEventListener("input", () => renderTable(allItems));
loadEntries();

async function openSource() {
  const input = document.getElementById("source-path-input");
  const status = document.getElementById("source-path-status");
  const path = input.value.trim();
  if (!path) return;
  status.className = "";
  status.textContent = "여는 중...";
  const res = await fetch("/api/source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    status.className = "error";
    let message = "열기에 실패했습니다 (HTTP " + res.status + ")";
    try {
      const errorBody = await res.json();
      if (errorBody && errorBody.message) message = errorBody.message;
    } catch (e) {
      // 본문이 JSON이 아니면 기본 메시지를 그대로 쓴다
    }
    status.textContent = message;
    return;
  }
  const data = await res.json();
  input.value = data.path;
  status.className = "ok";
  status.textContent = "열림 (" + data.exists_note + ")";
  await loadEntries();
}

document.getElementById("source-path-open").addEventListener("click", openSource);
document.getElementById("source-path-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") openSource();
});

async function loadHandoff() {
  const res = await fetch("/api/handoff");
  const data = await res.json();
  renderHandoffTable(data.items);
}

function renderHandoffTable(items) {
  const tbody = document.getElementById("handoff-body");
  tbody.innerHTML = "";
  if (items.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "handoff-empty-cell";
    td.textContent = "핸드오프 파일이 없습니다.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  items.forEach(item => tbody.appendChild(renderHandoffRow(item)));
}

function renderHandoffRow(item) {
  const tr = document.createElement("tr");

  const vocCell = document.createElement("td");
  vocCell.textContent = item.voc_number;
  tr.appendChild(vocCell);

  const composeCell = document.createElement("td");
  composeCell.textContent = item.compose || "—";
  tr.appendChild(composeCell);

  const mtimeCell = document.createElement("td");
  mtimeCell.className = "ts-cell";
  mtimeCell.textContent = item.mtime;
  tr.appendChild(mtimeCell);

  const sizeCell = document.createElement("td");
  sizeCell.textContent = item.size + " B";
  tr.appendChild(sizeCell);

  const bodyCell = document.createElement("td");
  bodyCell.className = "handoff-body-cell";
  const bodySpan = document.createElement("span");
  bodySpan.textContent = item.body_preview + (item.body_truncated ? "…" : "");
  bodyCell.appendChild(bodySpan);
  if (item.body_truncated) {
    const toggleBtn = document.createElement("button");
    toggleBtn.textContent = "전체보기";
    let expanded = false;
    toggleBtn.addEventListener("click", () => {
      expanded = !expanded;
      bodySpan.textContent = expanded ? item.body : (item.body_preview + "…");
      toggleBtn.textContent = expanded ? "접기" : "전체보기";
    });
    bodyCell.appendChild(document.createElement("br"));
    bodyCell.appendChild(toggleBtn);
  }
  tr.appendChild(bodyCell);

  return tr;
}

document.getElementById("handoff-refresh").addEventListener("click", () => loadHandoff());
loadHandoff();

async function openHandoffDir() {
  const input = document.getElementById("handoff-dir-input");
  const status = document.getElementById("handoff-dir-status");
  const path = input.value.trim();
  if (!path) return;
  status.className = "";
  status.textContent = "여는 중...";
  const res = await fetch("/api/handoff-source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    status.className = "error";
    let message = "열기에 실패했습니다 (HTTP " + res.status + ")";
    try {
      const errorBody = await res.json();
      if (errorBody && errorBody.message) message = errorBody.message;
    } catch (e) {
      // 본문이 JSON이 아니면 기본 메시지를 그대로 쓴다
    }
    status.textContent = message;
    return;
  }
  const data = await res.json();
  input.value = data.path;
  status.className = "ok";
  status.textContent = "열림 (" + data.exists_note + ")";
  await loadHandoff();
}

document.getElementById("handoff-dir-open").addEventListener("click", openHandoffDir);
document.getElementById("handoff-dir-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") openHandoffDir();
});
</script>
</body>
</html>
"""


def make_handler(jsonl_path: Path, handoff_dir: Path) -> type[BaseHTTPRequestHandler]:
    # 대시보드 UI의 "열기" 컨트롤(jsonl 파일·핸드오프 디렉터리 둘 다)이 런타임에
    # 대상을 바꿀 수 있도록, 클로저로 캡처한 고정값 대신 mutable 컨테이너에 담아
    # 모든 요청 핸들러가 항상 최신 값을 읽게 한다. 두 값은 서로 독립적으로
    # 바뀐다 — 하나를 바꿔도 다른 하나는 그대로 유지된다.
    state = {"jsonl_path": jsonl_path, "handoff_dir": handoff_dir}

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
                page = DASHBOARD_HTML.replace(
                    "__VOC_JSONL_PATH__", html.escape(str(state["jsonl_path"]))
                ).replace(
                    "__VOC_HANDOFF_DIR__", html.escape(str(state["handoff_dir"]))
                )
                self._send_html(200, page)
                return
            if self.path == "/api/entries":
                items, errors = parse_jsonl(state["jsonl_path"])
                self._send_json(200, {"items": items, "parse_errors": errors})
                return
            if self.path == "/api/handoff":
                items = list_handoff_files(state["handoff_dir"])
                self._send_json(200, {"items": items})
                return
            self._send_json(404, {"error": "not_found"})

        def _backup_failed(self) -> None:
            self._send_json(500, {
                "error": "backup_failed",
                "message": "백업 생성에 실패했습니다. 변경 사항이 저장되지 않았습니다.",
            })

        def do_PATCH(self) -> None:  # noqa: N802
            if self.path != "/api/entries":
                self._send_json(404, {"error": "not_found"})
                return
            try:
                body = self._read_json_body()
                original = body["original"]
                updated = body.get("updated", {})
            except ValueError:
                # json.JSONDecodeError(ValueError의 서브클래스)뿐 아니라, Content-Length
                # 헤더가 정수로 파싱 안 되는 경우(int() 예외)도 여기서 잡는다.
                self._bad_request("요청 본문이 올바른 JSON이 아닙니다")
                return
            except (KeyError, TypeError):
                # KeyError: "original" 키가 없음. TypeError: body가 dict가 아니어서
                # body["original"] 또는 body.get(...)이 실패(예: 리스트/문자열/null 본문).
                self._bad_request("'original' 필드가 필요합니다")
                return
            try:
                items = apply_patch(state["jsonl_path"], original, updated)
            except ConflictError:
                self._conflict()
                return
            except OSError:
                self._backup_failed()
                return
            self._send_json(200, {"items": items})

        def do_DELETE(self) -> None:  # noqa: N802
            if self.path != "/api/entries":
                self._send_json(404, {"error": "not_found"})
                return
            try:
                body = self._read_json_body()
                original = body["original"]
            except ValueError:
                self._bad_request("요청 본문이 올바른 JSON이 아닙니다")
                return
            except (KeyError, TypeError):
                self._bad_request("'original' 필드가 필요합니다")
                return
            try:
                items = apply_delete(state["jsonl_path"], original)
            except ConflictError:
                self._conflict()
                return
            except OSError:
                self._backup_failed()
                return
            self._send_json(200, {"items": items})

        def _read_new_path(self) -> Path | None:
            """요청 본문의 'path'를 읽어 절대경로로 정규화한다.

            실패하면 적절한 에러 응답을 직접 보내고 None을 반환한다 — 호출부는
            None이면 바로 return하면 된다.
            """
            try:
                body = self._read_json_body()
                raw_path = body["path"]
            except ValueError:
                self._bad_request("요청 본문이 올바른 JSON이 아닙니다")
                return None
            except (KeyError, TypeError):
                self._bad_request("'path' 필드가 필요합니다")
                return None
            if not isinstance(raw_path, str) or not raw_path.strip():
                self._bad_request("'path' 필드가 비어 있습니다")
                return None
            return Path(raw_path.strip()).expanduser().resolve()

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/source":
                new_path = self._read_new_path()
                if new_path is None:
                    return
                if new_path.is_dir():
                    self._bad_request("디렉터리가 아니라 파일 경로를 입력하세요: " + str(new_path))
                    return
                # 파일이 아직 없어도 받아준다 — parse_jsonl은 없는 파일을 에러가 아니라
                # "아직 이력 없음"(빈 목록)으로 취급한다(README 참고). 새 설치를 미리
                # 가리켜두는 것도 유효한 사용법이다.
                state["jsonl_path"] = new_path
                exists_note = "기존 파일" if new_path.exists() else "새 파일 — 아직 이력 없음"
                self._send_json(200, {"path": str(new_path), "exists_note": exists_note})
                return
            if self.path == "/api/handoff-source":
                new_dir = self._read_new_path()
                if new_dir is None:
                    return
                if new_dir.is_file():
                    self._bad_request("파일이 아니라 디렉터리 경로를 입력하세요: " + str(new_dir))
                    return
                # 디렉터리가 아직 없어도 받아준다 — list_handoff_files는 없는
                # 디렉터리를 에러가 아니라 빈 목록으로 취급한다(핸드오프가 아직
                # 한 번도 생긴 적 없는 최초 상태와 동일하게).
                state["handoff_dir"] = new_dir
                exists_note = "기존 디렉터리" if new_dir.exists() else "새 디렉터리 — 아직 핸드오프 없음"
                self._send_json(200, {"path": str(new_dir), "exists_note": exists_note})
                return
            self._send_json(404, {"error": "not_found"})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # 터미널 스팸 방지 — 필요하면 나중에 로깅으로 바꾼다

    return Handler


def build_server(
    jsonl_path: Path, port: int, handoff_dir: Path | None = None
) -> ThreadingHTTPServer:
    """포트가 이미 쓰이는 중이면 OSError를 그대로 전파한다 — 호출자(main)가
    "이미 실행 중일 수 있음" 메시지로 바꿔 보여준다.

    handoff_dir을 생략하면(기존 호출부 하위 호환) DEFAULT_HANDOFF_DIR을 쓴다.
    """
    if handoff_dir is None:
        handoff_dir = DEFAULT_HANDOFF_DIR
    handler_cls = make_handler(jsonl_path, handoff_dir)
    return ThreadingHTTPServer(("127.0.0.1", port), handler_cls)


def main(argv: list[str] | None = None, start_dir: Path | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="VoC Operator 이력 대시보드")
    parser.add_argument("--file", type=Path, default=DEFAULT_JSONL_PATH,
                         help="대상 JSONL 파일 경로")
    parser.add_argument("--handoff-dir", type=Path, default=DEFAULT_HANDOFF_DIR,
                         help="핸드오프 파일 디렉터리 경로")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--print-dir", action="store_true",
                         help="이 프로젝트가 쓸 ~/.voc-hub-<slug>/ 경로만 출력하고 종료한다"
                              "(서버를 띄우지 않는다 — 다른 프로세스가 같은 값을 읽을 때 쓴다)")
    args = parser.parse_args(argv)

    if args.print_dir:
        print(resolve_voc_hub_dir(start_dir))
        return 0

    try:
        server = build_server(args.file, args.port, args.handoff_dir)
    except OSError:
        print(
            f"포트 {args.port}가 이미 사용 중입니다. 이미 실행 중인 대시보드가 "
            f"있을 수 있습니다 — http://localhost:{args.port} 를 열어보세요.",
            file=sys.stderr,
        )
        return 1

    print(
        f"VoC Operator 대시보드: http://localhost:{args.port}  "
        f"(대상 파일: {args.file}, 핸드오프 디렉터리: {args.handoff_dir})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
