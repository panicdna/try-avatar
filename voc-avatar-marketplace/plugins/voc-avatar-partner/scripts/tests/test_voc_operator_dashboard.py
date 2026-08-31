import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
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

    def test_patch_can_set_evidence_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"ts": "t1", "voc_number": "V1", "decision": "resolver_delegate",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": "", "evidence": ""}
            path = self._make_file(tmp, [entry])
            items = dash.apply_patch(
                path, entry,
                {"decision": "reply", "evidence": "apps/server/src/api/items/router.py"},
            )
            self.assertEqual(items[0]["evidence"], "apps/server/src/api/items/router.py")

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

    def test_line_split_survives_unicode_line_separator_in_value(self):
        # Finding 1 재현: splitlines()는 \n 말고도 U+2028, \x0c 등에서도 쪼갠다.
        # ensure_ascii=False로 쓰인 JSONL 값 안에 이런 문자가 있으면 유효한 한 줄이
        # 두 조각으로 잘못 쪼개져 둘 다 파싱 실패가 되고, 그 항목은 원본과 다시는
        # 매칭되지 않아 영구히 수정/삭제 불가능해진다.
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            path = self._make_file(tmp, [entry])
            tricky_value = "고객 메시지 1줄 고객 메시지 2줄\x0c끝"

            items = dash.apply_patch(path, entry, {"human_instruction": tricky_value})
            self.assertEqual(items[0]["human_instruction"], tricky_value)

            parsed_items, errors = dash.parse_jsonl(path)
            self.assertEqual(errors, [])
            self.assertEqual(len(parsed_items), 1)
            self.assertEqual(parsed_items[0]["human_instruction"], tricky_value)

            # 다시 읽은 값으로 재매칭이 되어야 한다 — 영구히 매칭 불가능한 상태가 아님을 증명
            reread_original = parsed_items[0]
            items2 = dash.apply_patch(path, reread_original, {"decision": "reply"})
            self.assertEqual(items2[0]["decision"], "reply")
            self.assertEqual(items2[0]["human_instruction"], tricky_value)

            final_original = items2[0]
            items3 = dash.apply_delete(path, final_original)
            self.assertEqual(items3, [])

    def test_repeated_patches_do_not_accumulate_blank_lines(self):
        # Self-review 항목: _write_lines가 매번 정확히 엔트리당 한 줄만 쓰는지,
        # 반복 patch 후에도 빈 줄이 누적되지 않는지 확인한다.
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            path = self._make_file(tmp, [entry])

            items = dash.apply_patch(path, entry, {"decision": "reply"})
            self.assertEqual(path.read_text(encoding="utf-8").count("\n"), 1)
            items = dash.apply_patch(path, items[0], {"decision": "internal"})
            self.assertEqual(path.read_text(encoding="utf-8").count("\n"), 1)
            items = dash.apply_patch(path, items[0], {"decision": "hold"})
            self.assertEqual(path.read_text(encoding="utf-8").count("\n"), 1)
            self.assertEqual(len(items), 1)

    def test_write_backup_uses_nanosecond_suffix_no_collision_within_same_second(self):
        # Finding 4: 같은 초 안에 연속 write가 일어나도 백업 파일명이 겹치면 안 된다.
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
            path = self._make_file(tmp, [entry])
            content_before_first = path.read_text(encoding="utf-8")

            items = dash.apply_patch(path, entry, {"decision": "reply"})
            content_before_second = path.read_text(encoding="utf-8")
            dash.apply_patch(path, items[0], {"decision": "internal"})

            backups = sorted(Path(tmp).glob("operator-decisions.jsonl.bak-*"))
            self.assertEqual(len(backups), 2)
            self.assertNotEqual(backups[0].name, backups[1].name)
            contents = {b.name: b.read_text(encoding="utf-8") for b in backups}
            self.assertIn(content_before_first, contents.values())
            self.assertIn(content_before_second, contents.values())


class HandoffFileTests(unittest.TestCase):
    def test_missing_dir_returns_empty_not_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp) / "handoff"  # 만든 적 없음
            self.assertEqual(dash.list_handoff_files(dir_path), [])

    def test_parses_compose_and_delimited_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "V1.md"
            path.write_text(
                "compose: reply\n--- 본문 시작 ---\n실제 본문\n두 번째 줄\n--- 본문 끝 ---\n",
                encoding="utf-8",
            )
            item = dash.parse_handoff_file(path)
            self.assertEqual(item["voc_number"], "V1")
            self.assertEqual(item["compose"], "reply")
            self.assertEqual(item["body"], "실제 본문\n두 번째 줄")
            self.assertFalse(item["body_truncated"])

    def test_missing_compose_and_delimiters_falls_back_to_whole_text(self):
        # 형식을 안 지킨 파일이 와도 죽지 않고 전체 텍스트를 본문으로 취급한다 —
        # 이 대시보드는 읽기 전용 현황판이지 형식 검증기가 아니다.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "V2.md"
            path.write_text("그냥 자유 텍스트", encoding="utf-8")
            item = dash.parse_handoff_file(path)
            self.assertIsNone(item["compose"])
            self.assertEqual(item["body"], "그냥 자유 텍스트")

    def test_long_body_is_truncated_in_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "V3.md"
            long_body = "가" * (dash.HANDOFF_BODY_PREVIEW_LEN + 50)
            path.write_text(
                f"compose: internal\n--- 본문 시작 ---\n{long_body}\n--- 본문 끝 ---\n",
                encoding="utf-8",
            )
            item = dash.parse_handoff_file(path)
            self.assertTrue(item["body_truncated"])
            self.assertEqual(len(item["body_preview"]), dash.HANDOFF_BODY_PREVIEW_LEN)
            self.assertEqual(item["body"], long_body)  # 전체 본문은 안 잘림

    def test_list_only_shows_files_currently_on_disk(self):
        # 지운 파일은 다시 나타나지 않는다 — 별도 삭제 이력을 두지 않는다.
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            (dir_path / "V1.md").write_text("compose: reply\n본문", encoding="utf-8")
            (dir_path / "V2.md").write_text("compose: internal\n본문", encoding="utf-8")
            items = dash.list_handoff_files(dir_path)
            self.assertEqual({item["voc_number"] for item in items}, {"V1", "V2"})

            (dir_path / "V1.md").unlink()
            items_after_delete = dash.list_handoff_files(dir_path)
            self.assertEqual({item["voc_number"] for item in items_after_delete}, {"V2"})

    def test_list_ignores_non_markdown_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            (dir_path / "V1.md").write_text("compose: reply\n본문", encoding="utf-8")
            (dir_path / "V1.md.bak-123").write_text("옛 버전", encoding="utf-8")
            items = dash.list_handoff_files(dir_path)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["voc_number"], "V1")


class HttpServerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "operator-decisions.jsonl"
        self.handoff_dir = Path(self.tmpdir.name) / "handoff"
        self.entry = {"ts": "t1", "voc_number": "V1", "decision": "hold",
                      "trigger_condition": "", "human_instruction": "",
                      "precedent_used": ""}
        self.path.write_text(json.dumps(self.entry, ensure_ascii=False) + "\n", encoding="utf-8")
        self.server = dash.build_server(self.path, port=0, handoff_dir=self.handoff_dir)  # 0 = OS가 빈 포트 할당
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

    def _raw_request(self, method: str, path: str, raw_body: bytes):
        req = urllib.request.Request(self._url(path), data=raw_body, method=method,
                                      headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_patch_entries_missing_original_returns_400(self):
        status, payload = self._request(
            "PATCH", "/api/entries",
            {"updated": {"decision": "reply"}},  # "original" 키 없음
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "bad_request")

    def test_patch_entries_malformed_json_returns_400(self):
        status, payload = self._raw_request("PATCH", "/api/entries", b"{not valid json")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "bad_request")

    def test_delete_entries_missing_original_returns_400(self):
        status, payload = self._request("DELETE", "/api/entries", {})  # "original" 키 없음
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "bad_request")

    def test_delete_entries_malformed_json_returns_400(self):
        status, payload = self._raw_request("DELETE", "/api/entries", b"{not valid json")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "bad_request")

    def test_patch_entries_non_dict_body_returns_400(self):
        # Finding 2: body가 유효한 JSON이지만 dict가 아니면 body["original"]에서
        # KeyError가 아니라 TypeError가 난다 — 이것도 잡아서 400으로 응답해야 한다.
        status, payload = self._raw_request("PATCH", "/api/entries", b"[1, 2]")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "bad_request")

    def test_delete_entries_non_dict_body_returns_400(self):
        status, payload = self._raw_request("DELETE", "/api/entries", b"[1, 2]")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "bad_request")

    def test_patch_entries_null_body_returns_400(self):
        status, payload = self._raw_request("PATCH", "/api/entries", b"null")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "bad_request")

    def test_patch_entries_malformed_content_length_returns_400_not_dropped_connection(self):
        # Finding 2: Content-Length 헤더가 정수로 파싱이 안 되면(int() -> ValueError)
        # 커넥션을 끊지 말고 400을 깔끔하게 응답해야 한다. urllib은 Content-Length를
        # 스스로 계산해 버리므로 raw socket으로 직접 헤더를 조작한다.
        body = b'{"original": {}}'
        request = (
            "PATCH /api/entries HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: abc\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii") + body
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(request)
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
        status_line = response.split(b"\r\n", 1)[0].decode("ascii")
        self.assertIn("400", status_line)
        response_body = response.split(b"\r\n\r\n", 1)[1]
        payload = json.loads(response_body.decode("utf-8"))
        self.assertEqual(payload["error"], "bad_request")

    def test_patch_entries_backup_failure_returns_500_and_leaves_file_unchanged(self):
        # Finding 2: write_backup(→shutil.copy2)이 실패하면 커넥션을 끊지 말고
        # 깔끔한 500 응답을 보내야 하며, 파일은 그대로여야 한다.
        import unittest.mock as mock
        original_text = self.path.read_text(encoding="utf-8")
        with mock.patch("voc_operator_dashboard.shutil.copy2", side_effect=OSError("disk full")):
            status, payload = self._request(
                "PATCH", "/api/entries",
                {"original": self.entry, "updated": {"decision": "reply"}},
            )
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "backup_failed")
        self.assertEqual(self.path.read_text(encoding="utf-8"), original_text)

    def test_delete_entries_backup_failure_returns_500_and_leaves_file_unchanged(self):
        import unittest.mock as mock
        original_text = self.path.read_text(encoding="utf-8")
        with mock.patch("voc_operator_dashboard.shutil.copy2", side_effect=OSError("disk full")):
            status, payload = self._request("DELETE", "/api/entries", {"original": self.entry})
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "backup_failed")
        self.assertEqual(self.path.read_text(encoding="utf-8"), original_text)

    def test_frontend_handles_non_409_failures_explicitly(self):
        # Finding 5: 409 이외의 실패(400/500)도 loadEntries()로 조용히 넘어가지 않고
        # 사용자에게 알려야 한다. JS가 HTML 문자열에 임베드되어 있으므로 소스 존재
        # 여부로 확인하는 스모크 테스트다 (기존 테스트들과 같은 패턴).
        with urllib.request.urlopen(self._url("/")) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn("async function reportFailure(res)", html)
        self.assertIn("if (!res.ok) {", html)
        self.assertIn("await reportFailure(res);", html)

    def test_unknown_path_returns_404(self):
        status, payload = self._request("GET", "/nope")
        self.assertEqual(status, 404)

    def test_get_handoff_returns_empty_when_dir_missing(self):
        status, payload = self._request("GET", "/api/handoff")
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"], [])

    def test_get_handoff_returns_parsed_files_sorted_newest_first(self):
        self.handoff_dir.mkdir(parents=True)
        (self.handoff_dir / "V1.md").write_text(
            "compose: reply\n--- 본문 시작 ---\n첫 번째\n--- 본문 끝 ---\n", encoding="utf-8"
        )
        time.sleep(0.01)  # mtime이 확실히 갈리도록
        (self.handoff_dir / "V2.md").write_text(
            "compose: internal\n--- 본문 시작 ---\n두 번째\n--- 본문 끝 ---\n", encoding="utf-8"
        )
        status, payload = self._request("GET", "/api/handoff")
        self.assertEqual(status, 200)
        voc_numbers = [item["voc_number"] for item in payload["items"]]
        self.assertEqual(voc_numbers, ["V2", "V1"])  # 최신 수정 순

    def test_root_html_contains_handoff_section(self):
        with urllib.request.urlopen(self._url("/")) as resp:
            page_html = resp.read().decode("utf-8")
        self.assertIn('id="handoff-table"', page_html)
        self.assertIn('id="handoff-refresh"', page_html)
        self.assertIn("/api/handoff", page_html)
        self.assertIn(str(self.handoff_dir), page_html)

    def test_root_html_contains_expected_markup_and_conflict_copy(self):
        with urllib.request.urlopen(self._url("/")) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn('id="entries-table"', html)
        self.assertIn('id="search-input"', html)
        self.assertIn("/api/entries", html)
        self.assertIn("새로고침 후 다시 시도", html)
        self.assertIn("향후 자동 판단의 선례로 쓰일 수 있습니다", html)

    def test_evidence_column_present_in_table_and_editable_fields(self):
        with urllib.request.urlopen(self._url("/")) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn("<th>evidence</th>", html)
        self.assertIn('"evidence"', html)  # EDITABLE_FIELDS JS array

    def test_decision_field_uses_input_with_datalist_not_textarea(self):
        """Verify the decision field's edit control uses <input type="text"> with list attr.

        The HTML spec only allows list attribute on <input>, not <textarea>.
        This test confirms the fix for the datalist support defect.
        """
        with urllib.request.urlopen(self._url("/")) as resp:
            html = resp.read().decode("utf-8")
        # Confirm the datalist exists
        self.assertIn('id="decision-options"', html)
        self.assertIn('value="reply"', html)
        self.assertIn('value="internal"', html)
        self.assertIn('value="resolver_delegate"', html)
        self.assertIn('value="hold"', html)
        # Confirm the JS for decision field creates input not textarea
        self.assertIn('if (field === "decision") {', html)
        self.assertIn('control = document.createElement("input");', html)
        self.assertIn('control.type = "text";', html)
        # control.list는 읽기 전용 IDL 속성이라 대입은 조용히 no-op된다 —
        # setAttribute("list", ...)를 써야 실제로 datalist에 바인딩된다.
        self.assertIn('control.setAttribute("list", "decision-options");', html)
        # Confirm other fields still use textarea
        self.assertIn('control = document.createElement("textarea");', html)


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


if __name__ == "__main__":
    unittest.main()
