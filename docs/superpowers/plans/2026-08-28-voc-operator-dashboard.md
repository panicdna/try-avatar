# VoC Operator 이력 대시보드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `~/.voc-hub/operator-decisions.jsonl`(voc-avatar-operator의 human-in-the-loop 선례 이력)를 로컬 웹 대시보드에서 열람·검색·수정·삭제할 수 있게 한다.

**Architecture:** 외부 의존성 없는 단일 Python3 스크립트(`scripts/voc_operator_dashboard.py`)가 `http.server` 기반으로 HTML 뷰와 `/api/entries` REST 엔드포인트(GET/PATCH/DELETE)를 함께 서빙한다. JSONL 파일이 유일한 진실의 원천이며, 행 식별은 줄 번호가 아니라 **행 전체 내용 일치**로 한다(다른 프로세스의 동시 append에 안전하게). 수정/삭제 직전 자동 백업한다. `.claude/commands/voc-operator-dashboard.md` 슬래시 커맨드로 실행한다.

**Tech Stack:** Python 3.10 표준 라이브러리만(`http.server`, `json`, `shutil`, `pathlib`, `argparse`, `time`). 테스트는 `unittest`(표준 라이브러리) — pip 설치 불필요.

**Spec:** `docs/superpowers/specs/2026-08-28-voc-operator-dashboard-design.md`

## Global Constraints

- 외부 의존성 없이 `python3` 하나로 실행되어야 한다(pip install 금지) — spec "아키텍처"
- JSONL 경로는 함수 인자로 주고받고, 코드 안에 하드코딩하지 않는다(테스트가 임시 파일을 쓸 수 있도록) — 이 계획의 필수 요구사항
- **자동화 테스트는 절대 실제 `~/.voc-hub/operator-decisions.jsonl`을 건드리지 않는다.** 모든 테스트는 `tempfile.TemporaryDirectory()` 안의 파일을 대상으로 한다 — 이 계획의 필수 요구사항 (실제 이력 데이터 보호)
- `ts` 필드는 읽기 전용, 편집 가능한 필드는 `voc_number, decision, trigger_condition, human_instruction, precedent_used` 뿐이다 — spec "데이터 모델"
- 수정/삭제는 반드시 파일 전체 백업(`<path>.bak-<epoch>`) 후에만 실행한다. 백업 실패 시 쓰기 자체를 중단한다 — spec "백업"
- 행 식별은 요청 본문의 `original`(행 전체 JSON)과 현재 파일의 줄을 완전 비교해서 하고, 일치하는 줄이 없으면 409를 반환하며 자동 재시도하지 않는다 — spec "행 식별과 동시성"
- 손상된 JSONL 줄은 건너뛰고 `parse_errors`로 보고한다. 절대 전체 응답을 실패시키지 않는다 — spec "손상 복원력"
- 파일이 없으면 빈 목록으로 정상 처리한다(에러 아님) — spec "손상 복원력"
- 고정 포트(기본 8765). 포트가 이미 쓰이는 중이면 새 서버를 띄우지 않고 안내만 한다 — spec "실행 방법"

---

## 파일 구조

- Create: `scripts/voc_operator_dashboard.py` — 서버 전체(파싱/백업/패치/삭제 로직 + HTTP 핸들러 + 임베디드 HTML/JS + `main()`)
- Create: `scripts/tests/test_voc_operator_dashboard.py` — 위 스크립트의 unittest
- Create: `scripts/tests/__init__.py` — 빈 파일 (테스트 패키지 인식용)
- Create: `.claude/commands/voc-operator-dashboard.md` — 슬래시 커맨드

단일 파일로 서버를 구현하는 이유: 이 도구는 "개인용 로컬 스크립트 하나"로 배포·실행되어야 하고(spec의 zero-install 요구), HTML/JS를 별도 정적 파일로 분리하면 스크립트가 어디서 실행되든 상대 경로를 찾는 문제가 생긴다. 250줄 내외로 예상되어 파일 하나로도 책임이 과도하게 섞이지 않는다.

---

### Task 1: JSONL 파싱 (손상 복원력 포함)

**Files:**
- Create: `scripts/voc_operator_dashboard.py`
- Create: `scripts/tests/__init__.py`
- Test: `scripts/tests/test_voc_operator_dashboard.py`

**Interfaces:**
- Produces: `DEFAULT_JSONL_PATH: Path`, `DEFAULT_PORT: int = 8765`, `EDITABLE_FIELDS: tuple[str, ...]`, `parse_jsonl(path: Path) -> tuple[list[dict], list[dict]]` (반환: `(items, parse_errors)`, `parse_errors`의 각 원소는 `{"line_no": int, "raw": str}`)

- [ ] **Step 1: 빈 파일 생성 및 테스트 패키지 마커**

```bash
mkdir -p scripts/tests
touch scripts/tests/__init__.py
```

- [ ] **Step 2: 실패하는 테스트를 먼저 작성한다**

`scripts/tests/test_voc_operator_dashboard.py`:

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voc_operator_dashboard as dash  # noqa: E402


class ParseJsonlTests(unittest.TestCase):
    def test_missing_file_returns_empty_not_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operator-decisions.jsonl"
            items, errors = dash.parse_jsonl(path)
            self.assertEqual(items, [])
            self.assertEqual(errors, [])

    def test_parses_valid_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operator-decisions.jsonl"
            line1 = {"ts": "2026-08-28T09:28:09+09:00", "voc_number": "V260807",
                     "decision": "reply", "trigger_condition": "",
                     "human_instruction": "", "precedent_used": ""}
            path.write_text(json.dumps(line1, ensure_ascii=False) + "\n", encoding="utf-8")
            items, errors = dash.parse_jsonl(path)
            self.assertEqual(items, [line1])
            self.assertEqual(errors, [])

    def test_skips_corrupted_line_and_reports_it(self):
        # 실제 사고 재현: jq 변수 누락 에러 메시지가 JSON 라인 사이에 섞여 append된 상황
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operator-decisions.jsonl"
            good_line = json.dumps({"ts": "t1", "voc_number": "V1", "decision": "hold",
                                     "trigger_condition": "", "human_instruction": "",
                                     "precedent_used": ""}, ensure_ascii=False)
            corrupted = 'jq: error: $instruction is not defined at <top-level>, line 2:'
            path.write_text(good_line + "\n" + corrupted + "\n", encoding="utf-8")
            items, errors = dash.parse_jsonl(path)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["voc_number"], "V1")
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0]["line_no"], 2)
            self.assertEqual(errors[0]["raw"], corrupted)

    def test_blank_lines_are_ignored_not_treated_as_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operator-decisions.jsonl"
            path.write_text("\n\n", encoding="utf-8")
            items, errors = dash.parse_jsonl(path)
            self.assertEqual(items, [])
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'voc_operator_dashboard'` (아직 구현 파일이 없음)

- [ ] **Step 4: 최소 구현 작성**

`scripts/voc_operator_dashboard.py`:

```python
#!/usr/bin/env python3
"""VoC Operator 이력 대시보드 — 로컬 전용, 표준 라이브러리만 사용한다.

~/.voc-hub/operator-decisions.jsonl 을 웹 페이지로 열람·검색·수정·삭제한다.
이 파일은 voc-avatar-operator 에이전트가 human-in-the-loop 선례 재사용에
직접 읽는 실제 소스이므로, 수정/삭제는 항상 백업 후에만 실행한다.
"""
from __future__ import annotations

import json
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
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard -v`
Expected: PASS (4 tests)

- [ ] **Step 6: 커밋**

```bash
git add scripts/voc_operator_dashboard.py scripts/tests/__init__.py scripts/tests/test_voc_operator_dashboard.py
git commit -m "feat(voc-operator-dashboard): add resilient JSONL parsing

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: 행 식별 + 백업 + 수정/삭제 로직

**Files:**
- Modify: `scripts/voc_operator_dashboard.py`
- Test: `scripts/tests/test_voc_operator_dashboard.py`

**Interfaces:**
- Consumes: `parse_jsonl(path) -> tuple[list[dict], list[dict]]`, `EDITABLE_FIELDS`（Task 1）
- Produces: `class ConflictError(Exception)`, `write_backup(path: Path) -> Path | None`, `apply_patch(path: Path, original: dict, updated: dict) -> list[dict]`, `apply_delete(path: Path, original: dict) -> list[dict]`

- [ ] **Step 1: 실패하는 테스트를 먼저 작성한다**

`scripts/tests/test_voc_operator_dashboard.py`에 아래 클래스를 추가한다(파일 상단 import는 그대로 재사용):

```python
class ApplyPatchDeleteTests(unittest.TestCase):
    def _make_file(self, tmp: str, entries: list[dict]) -> Path:
        path = Path(tmp) / "operator-decisions.jsonl"
        lines = [json.dumps(e, ensure_ascii=False) for e in entries]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path

    def test_patch_updates_matching_line_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            path = self._make_file(tmp, [entry])
            items = dash.apply_patch(path, entry, {"decision": "reply"})
            self.assertEqual(items[0]["decision"], "reply")
            self.assertEqual(items[0]["ts"], "t1")  # ts는 절대 안 바뀐다
            backups = list(Path(tmp).glob("operator-decisions.jsonl.bak-*"))
            self.assertEqual(len(backups), 1)

    def test_patch_conflict_when_original_does_not_match_current_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            path = self._make_file(tmp, [entry])
            stale_original = dict(entry, decision="already_changed_elsewhere")
            with self.assertRaises(dash.ConflictError):
                dash.apply_patch(path, stale_original, {"decision": "reply"})
            # 실패 시 파일도 백업도 생기지 않아야 한다
            items, _ = dash.parse_jsonl(path)
            self.assertEqual(items[0]["decision"], "hold")
            backups = list(Path(tmp).glob("operator-decisions.jsonl.bak-*"))
            self.assertEqual(backups, [])

    def test_patch_ignores_fields_outside_editable_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            path = self._make_file(tmp, [entry])
            items = dash.apply_patch(path, entry, {"ts": "hacked", "decision": "reply"})
            self.assertEqual(items[0]["ts"], "t1")

    def test_delete_removes_matching_line_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry1 = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            entry2 = {"ts": "t2", "voc_number": "V2", "decision": "reply",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            path = self._make_file(tmp, [entry1, entry2])
            items = dash.apply_delete(path, entry1)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["voc_number"], "V2")
            backups = list(Path(tmp).glob("operator-decisions.jsonl.bak-*"))
            self.assertEqual(len(backups), 1)

    def test_delete_conflict_when_line_already_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            path = self._make_file(tmp, [])  # 이미 삭제된 상태를 흉내
            with self.assertRaises(dash.ConflictError):
                dash.apply_delete(path, entry)

    def test_write_backup_returns_none_when_no_file_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operator-decisions.jsonl"
            self.assertIsNone(dash.write_backup(path))

    def test_backup_failure_aborts_write_and_leaves_file_unchanged(self):
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            path = self._make_file(tmp, [entry])
            original_text = path.read_text(encoding="utf-8")
            with mock.patch("voc_operator_dashboard.shutil.copy2", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    dash.apply_patch(path, entry, {"decision": "reply"})
            # 백업이 실패했으니 원본 파일도 절대 바뀌면 안 된다
            self.assertEqual(path.read_text(encoding="utf-8"), original_text)
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard -v`
Expected: FAIL — `AttributeError: module 'voc_operator_dashboard' has no attribute 'apply_patch'` (그리고 나머지 신규 테스트도 실패)

- [ ] **Step 3: 최소 구현 작성**

`scripts/voc_operator_dashboard.py`에 `parse_jsonl` 함수 뒤에 이어서 추가한다:

```python
import shutil
import time


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
```

`Path` import는 이미 Task 1에서 파일 상단에 있으므로 그대로 쓴다. `import shutil`/`import time`은 파일 최상단 import 블록으로 옮겨 정리한다(다른 `import json`/`from pathlib import Path` 옆).

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard -v`
Expected: PASS (11 tests)

- [ ] **Step 5: 커밋**

```bash
git add scripts/voc_operator_dashboard.py scripts/tests/test_voc_operator_dashboard.py
git commit -m "feat(voc-operator-dashboard): add content-match patch/delete with auto-backup

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: HTTP 서버 (GET/PATCH/DELETE, 포트 충돌 처리)

**Files:**
- Modify: `scripts/voc_operator_dashboard.py`
- Test: `scripts/tests/test_voc_operator_dashboard.py`

**Interfaces:**
- Consumes: `parse_jsonl`, `apply_patch`, `apply_delete`, `ConflictError`（Task 1–2）, `DASHBOARD_HTML: str`（Task 4에서 정의 — 이 태스크에서는 임시 플레이스홀더 상수로 둔다: `DASHBOARD_HTML = "<html><body>placeholder</body></html>"`, Task 4에서 실제 내용으로 교체）
- Produces: `make_handler(jsonl_path: Path) -> type[BaseHTTPRequestHandler]`, `build_server(jsonl_path: Path, port: int) -> ThreadingHTTPServer`（포트가 이미 쓰이는 중이면 `OSError`를 그대로 전파한다）

- [ ] **Step 1: 실패하는 테스트를 먼저 작성한다**

`scripts/tests/test_voc_operator_dashboard.py`에 추가(파일 상단에 `import threading`, `import urllib.request`, `import urllib.error` 추가):

```python
import threading
import urllib.error
import urllib.request


class HttpServerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "operator-decisions.jsonl"
        self.entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
        self.path.write_text(json.dumps(self.entry, ensure_ascii=False) + "\n", encoding="utf-8")
        self.server = dash.build_server(self.path, port=0)  # 0 = OS가 빈 포트 할당
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self._url(path), data=data, method=method,
                                      headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_get_root_returns_html(self):
        with urllib.request.urlopen(self._url("/")) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))

    def test_get_entries_returns_items_and_empty_parse_errors(self):
        status, payload = self._request("GET", "/api/entries")
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"], [self.entry])
        self.assertEqual(payload["parse_errors"], [])

    def test_patch_entries_success(self):
        status, payload = self._request(
            "PATCH", "/api/entries",
            {"original": self.entry, "updated": {"decision": "reply"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"][0]["decision"], "reply")

    def test_patch_entries_conflict_returns_409(self):
        stale = dict(self.entry, decision="wrong")
        status, payload = self._request(
            "PATCH", "/api/entries",
            {"original": stale, "updated": {"decision": "reply"}},
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "conflict")

    def test_delete_entries_success(self):
        status, payload = self._request("DELETE", "/api/entries", {"original": self.entry})
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"], [])

    def test_unknown_path_returns_404(self):
        status, payload = self._request("GET", "/nope")
        self.assertEqual(status, 404)


class BuildServerPortConflictTests(unittest.TestCase):
    def test_second_server_on_same_port_raises_oserror(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operator-decisions.jsonl"
            first = dash.build_server(path, port=0)
            port = first.server_address[1]
            try:
                with self.assertRaises(OSError):
                    dash.build_server(path, port=port)
            finally:
                first.server_close()
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard -v`
Expected: FAIL — `AttributeError: module 'voc_operator_dashboard' has no attribute 'build_server'`

- [ ] **Step 3: 최소 구현 작성**

`scripts/voc_operator_dashboard.py` 최상단 import 블록을 정리하고(`json`, `shutil`, `time`, `from pathlib import Path`에 이어서), 파일 끝에 아래를 추가한다:

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

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
            body = self._read_json_body()
            try:
                items = apply_patch(jsonl_path, body["original"], body.get("updated", {}))
            except ConflictError:
                self._conflict()
                return
            self._send_json(200, {"items": items})

        def do_DELETE(self) -> None:  # noqa: N802
            if self.path != "/api/entries":
                self._send_json(404, {"error": "not_found"})
                return
            body = self._read_json_body()
            try:
                items = apply_delete(jsonl_path, body["original"])
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
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard -v`
Expected: PASS (18 tests)

- [ ] **Step 5: 커밋**

```bash
git add scripts/voc_operator_dashboard.py scripts/tests/test_voc_operator_dashboard.py
git commit -m "feat(voc-operator-dashboard): add HTTP server with GET/PATCH/DELETE

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: 프론트엔드 (테이블/검색/편집/삭제/손상 배너)

**Files:**
- Modify: `scripts/voc_operator_dashboard.py`
- Test: `scripts/tests/test_voc_operator_dashboard.py`

**Interfaces:**
- Consumes: `/api/entries`의 GET/PATCH/DELETE 응답 스키마(Task 3), `EDITABLE_FIELDS`(Task 1)
- Produces: `DASHBOARD_HTML`의 최종 내용(Task 3의 placeholder를 교체)

- [ ] **Step 1: 실패하는 테스트를 먼저 작성한다(마크업 스모크 테스트)**

`scripts/tests/test_voc_operator_dashboard.py`의 `HttpServerTests`에 추가:

```python
    def test_root_html_contains_expected_markup_and_conflict_copy(self):
        with urllib.request.urlopen(self._url("/")) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn('id="entries-table"', html)
        self.assertIn('id="search-input"', html)
        self.assertIn("/api/entries", html)
        self.assertIn("새로고침 후 다시 시도", html)
        self.assertIn("향후 자동 판단의 선례로 쓰일 수 있습니다", html)
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard.HttpServerTests.test_root_html_contains_expected_markup_and_conflict_copy -v`
Expected: FAIL — placeholder HTML에는 위 문자열들이 없으므로 `AssertionError`

- [ ] **Step 3: `DASHBOARD_HTML`을 실제 내용으로 교체**

`scripts/voc_operator_dashboard.py`의 `DASHBOARD_HTML = "<html>...placeholder..."` 줄을 아래로 통째로 교체한다:

```python
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
</style>
</head>
<body>
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
        const textarea = document.createElement("textarea");
        textarea.value = item[field] || "";
        if (field === "decision") textarea.setAttribute("list", "decision-options");
        td.appendChild(textarea);
        editors[field].textarea = textarea;
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
  await loadEntries();
}

document.getElementById("search-input").addEventListener("input", () => renderTable(allItems));
loadEntries();
</script>
</body>
</html>
"""
```

- [ ] **Step 4: 테스트 실행 — 전체 통과 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard -v`
Expected: PASS (19 tests)

- [ ] **Step 5: 커밋**

```bash
git add scripts/voc_operator_dashboard.py scripts/tests/test_voc_operator_dashboard.py
git commit -m "feat(voc-operator-dashboard): add table/search/edit/delete frontend

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `main()` 진입점 + 슬래시 커맨드

**Files:**
- Modify: `scripts/voc_operator_dashboard.py`
- Create: `.claude/commands/voc-operator-dashboard.md`
- Test: `scripts/tests/test_voc_operator_dashboard.py`

**Interfaces:**
- Consumes: `build_server`, `DEFAULT_JSONL_PATH`, `DEFAULT_PORT`（Task 1, 3）
- Produces: `main(argv: list[str] | None = None) -> int`（종료 코드를 반환 — `sys.exit`는 `if __name__ == "__main__":` 블록에서만 호출해 테스트 가능하게 한다）

- [ ] **Step 1: 실패하는 테스트를 먼저 작성한다**

`scripts/tests/test_voc_operator_dashboard.py`에 추가:

```python
class MainEntrypointTests(unittest.TestCase):
    def test_main_reports_already_running_when_port_busy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operator-decisions.jsonl"
            occupied = dash.build_server(path, port=0)
            port = occupied.server_address[1]
            try:
                exit_code = dash.main(["--file", str(path), "--port", str(port)])
                self.assertEqual(exit_code, 1)
            finally:
                occupied.server_close()
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard.MainEntrypointTests -v`
Expected: FAIL — `AttributeError: module 'voc_operator_dashboard' has no attribute 'main'`

- [ ] **Step 3: 최소 구현 작성**

`scripts/voc_operator_dashboard.py` 파일 맨 끝에 추가한다:

```python
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
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `cd /mnt/c/work/skill_on_boarding && python3 -m unittest scripts.tests.test_voc_operator_dashboard -v`
Expected: PASS (20 tests)

- [ ] **Step 5: 슬래시 커맨드 작성**

`.claude/commands/voc-operator-dashboard.md`:

```markdown
---
description: VoC Operator 이력(~/.voc-hub/operator-decisions.jsonl) 대시보드를 로컬에 띄운다
---

`scripts/voc_operator_dashboard.py`를 백그라운드로 실행해 VoC Operator 이력
대시보드를 띄운다.

1. Bash로 다음을 백그라운드 실행한다(`run_in_background: true`):
   ```bash
   python3 scripts/voc_operator_dashboard.py
   ```
2. 몇 초 뒤 해당 백그라운드 프로세스의 출력을 확인한다.
   - `VoC Operator 대시보드: http://localhost:8765 ...` 가 보이면 그 URL을
     사용자에게 그대로 알려준다.
   - `포트 8765가 이미 사용 중입니다 ...` 가 보이면(대상 파일: `~/.voc-hub/operator-decisions.jsonl`
     읽기 전용 안내), 새로 띄우려 하지 말고 이미 다른 인스턴스가 떠 있을 수
     있다는 그 안내를 그대로 전달한다 — `http://localhost:8765` 를 열어보라고
     안내한다.
3. 대상 파일은 `~/.voc-hub/operator-decisions.jsonl`이 기본값이다 — 이
   커맨드는 인자를 받지 않으며 항상 기본 경로를 그대로 쓴다.
4. 사용자가 "종료해줘"라고 하면 해당 백그라운드 프로세스를 정리한다(상시
   구동 데몬이 아니다).
```

- [ ] **Step 6: 커밋**

```bash
git add scripts/voc_operator_dashboard.py scripts/tests/test_voc_operator_dashboard.py .claude/commands/voc-operator-dashboard.md
git commit -m "feat(voc-operator-dashboard): add main() entrypoint and slash command

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: 수동 종단 검증 (실제 데이터는 읽기 전용으로만 사용)

**Files:** (변경 없음 — 검증만)

**Interfaces:**
- Consumes: `scripts/voc_operator_dashboard.py`의 `main`(Task 5), `.claude/commands/voc-operator-dashboard.md`(Task 5)

이 태스크는 자동화 테스트가 아니라, spec의 "테스트 계획"에 있던 시나리오를 사람이
직접(또는 조정자가 curl로) 확인하는 절차다. **실제 `~/.voc-hub/operator-decisions.jsonl`에는
절대 PATCH/DELETE를 실행하지 않는다** — 실제 파일 검증은 GET(읽기)까지만 한다.

- [ ] **Step 1: 임시 복사본으로 편집/삭제/충돌 시나리오 검증**

```bash
cp ~/.voc-hub/operator-decisions.jsonl /tmp/claude-1000/-mnt-c-work-skill-on-boarding/32ce16c5-0363-4d02-a6a6-640cf6ef9900/scratchpad/operator-decisions-verify.jsonl
python3 scripts/voc_operator_dashboard.py \
  --file /tmp/claude-1000/-mnt-c-work-skill-on-boarding/32ce16c5-0363-4d02-a6a6-640cf6ef9900/scratchpad/operator-decisions-verify.jsonl \
  --port 8766 &
sleep 1
curl -s http://localhost:8766/api/entries | jq .
# 브라우저로 http://localhost:8766 를 열어: 검색, 수정 저장, 삭제(확인창)를 각각 한 번씩 실행
kill %1
```

Expected: `/api/entries`가 임시 복사본의 실제 항목을 그대로 반환한다. 브라우저에서
수정하면 `operator-decisions-verify.jsonl.bak-*` 백업이 생기고 내용이 갱신된다.
삭제도 동일하게 백업 후 반영된다.

- [ ] **Step 2: 손상 라인 처리 확인**

```bash
printf '%s\n' 'jq: error: $instruction is not defined at <top-level>, line 2:' \
  >> /tmp/claude-1000/-mnt-c-work-skill-on-boarding/32ce16c5-0363-4d02-a6a6-640cf6ef9900/scratchpad/operator-decisions-verify.jsonl
python3 scripts/voc_operator_dashboard.py \
  --file /tmp/claude-1000/-mnt-c-work-skill-on-boarding/32ce16c5-0363-4d02-a6a6-640cf6ef9900/scratchpad/operator-decisions-verify.jsonl \
  --port 8766 &
sleep 1
curl -s http://localhost:8766/api/entries | jq '.parse_errors'
kill %1
```

Expected: `parse_errors`에 방금 추가한 손상 줄이 1개 보고되고, 나머지 정상 항목은
`items`에 그대로 남는다. 브라우저에서 페이지가 깨지지 않고 배너만 뜬다.

- [ ] **Step 3: 실제 파일로 읽기 전용 스모크 테스트**

```bash
/voc-operator-dashboard
```

Expected: 슬래시 커맨드가 `http://localhost:8765`를 알려준다. 브라우저로 열어
`~/.voc-hub/operator-decisions.jsonl`의 실제 항목(V260807 등)이 표시되는지만
확인한다 — **이 단계에서 수정/삭제 버튼을 누르지 않는다.**

- [ ] **Step 4: 포트 충돌 안내 확인**

대시보드가 이미 떠 있는 상태에서 `/voc-operator-dashboard`를 다시 호출한다.

Expected: 새 서버를 띄우지 않고 "포트 8765가 이미 사용 중입니다 ... 이미 열어보세요"
안내가 그대로 전달된다.

- [ ] **Step 5: 정리**

```bash
rm -f /tmp/claude-1000/-mnt-c-work-skill-on-boarding/32ce16c5-0363-4d02-a6a6-640cf6ef9900/scratchpad/operator-decisions-verify.jsonl*
```

임시 검증 파일과 그 백업들을 지운다(scratchpad라 세션 종료 시 자동 정리되지만
명시적으로 지워 흔적을 남기지 않는다).
