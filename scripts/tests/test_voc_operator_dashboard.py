import json
import sys
import tempfile
import threading
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

    def test_unknown_path_returns_404(self):
        status, payload = self._request("GET", "/nope")
        self.assertEqual(status, 404)

    def test_root_html_contains_expected_markup_and_conflict_copy(self):
        with urllib.request.urlopen(self._url("/")) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn('id="entries-table"', html)
        self.assertIn('id="search-input"', html)
        self.assertIn("/api/entries", html)
        self.assertIn("새로고침 후 다시 시도", html)
        self.assertIn("향후 자동 판단의 선례로 쓰일 수 있습니다", html)

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
        self.assertIn('value="pr_delegate"', html)
        self.assertIn('value="hold"', html)
        # Confirm the JS for decision field creates input not textarea
        self.assertIn('if (field === "decision") {', html)
        self.assertIn('control = document.createElement("input");', html)
        self.assertIn('control.type = "text";', html)
        self.assertIn('control.list = "decision-options";', html)
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
