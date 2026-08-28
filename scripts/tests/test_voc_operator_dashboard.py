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
