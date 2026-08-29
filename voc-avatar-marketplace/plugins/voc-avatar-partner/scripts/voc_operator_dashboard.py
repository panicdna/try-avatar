#!/usr/bin/env python3
"""VoC Operator 이력 대시보드 — 로컬 전용, 표준 라이브러리만 사용한다.

~/.voc-hub/operator-decisions.jsonl 을 웹 페이지로 열람·검색·수정·삭제한다.
이 파일은 voc-avatar-operator 에이전트가 human-in-the-loop 선례 재사용에
직접 읽는 실제 소스이므로, 수정/삭제는 항상 백업 후에만 실행한다.
"""
from __future__ import annotations

import html
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
  #source-path { color: #666; font-size: 0.85em; margin-bottom: 0.5rem; }
  #source-path code { background: #f5f5f5; padding: 0.1rem 0.3rem; border-radius: 3px; }
</style>
</head>
<body>
<div id="source-path">참고 파일: <code>__VOC_JSONL_PATH__</code></div>
<h1>VoC Operator 이력 대시보드</h1>
<div id="parse-error-banner"></div>
<input id="search-input" type="text" placeholder="voc_number 또는 decision 검색">
<table id="entries-table">
  <thead>
    <tr>
      <th>ts</th><th>voc_number</th><th>decision</th><th>trigger_condition</th>
      <th>human_instruction</th><th>precedent_used</th><th></th>
    </tr>
  </thead>
  <tbody id="entries-body"></tbody>
</table>

<datalist id="decision-options">
  <option value="reply"><option value="internal">
  <option value="pr_delegate"><option value="hold">
</datalist>

<script>
const EDITABLE_FIELDS = ["voc_number", "decision", "trigger_condition", "human_instruction", "precedent_used"];
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
</script>
</body>
</html>
"""


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
                page = DASHBOARD_HTML.replace(
                    "__VOC_JSONL_PATH__", html.escape(str(jsonl_path))
                )
                self._send_html(200, page)
                return
            if self.path == "/api/entries":
                items, errors = parse_jsonl(jsonl_path)
                self._send_json(200, {"items": items, "parse_errors": errors})
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
                items = apply_patch(jsonl_path, original, updated)
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
                items = apply_delete(jsonl_path, original)
            except ConflictError:
                self._conflict()
                return
            except OSError:
                self._backup_failed()
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


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="VoC Operator 이력 대시보드")
    parser.add_argument("--file", type=Path, default=DEFAULT_JSONL_PATH,
                         help="대상 JSONL 파일 경로")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    try:
        server = build_server(args.file, args.port)
    except OSError:
        print(
            f"포트 {args.port}가 이미 사용 중입니다. 이미 실행 중인 대시보드가 "
            f"있을 수 있습니다 — http://localhost:{args.port} 를 열어보세요.",
            file=sys.stderr,
        )
        return 1

    print(f"VoC Operator 대시보드: http://localhost:{args.port}  (대상 파일: {args.file})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
