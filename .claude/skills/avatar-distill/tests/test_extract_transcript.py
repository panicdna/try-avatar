"""Tests for extract_transcript.py.

The whole point of this script is what it leaves OUT: tool results, file
contents, and tool inputs must never reach the conversation text a subagent
reads. Most tests here are negative assertions.
"""

import json
import string
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import extract_transcript as et  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_transcript.py"

# Built from parts, not written out — see the note in test_extract_digest.py.
_LOWER_DIGITS = string.ascii_lowercase + string.digits
FAKE_AFT = "aft_" + _LOWER_DIGITS[:16]
FAKE_GH = "ghp_" + _LOWER_DIGITS
FAKE_AWS = "AKIA" + (string.ascii_uppercase + string.digits)[:16]


def write_session(root, project, session_id, records):
    path = root / project / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def prompt(sid, text, **extra):
    rec = {"type": "user", "sessionId": sid, "timestamp": "2026-08-01T09:00:00.000Z",
           "cwd": "/home/u/proj", "message": {"role": "user", "content": text}}
    rec.update(extra)
    return rec


def title(sid, text):
    return {"type": "ai-title", "sessionId": sid, "aiTitle": text}


def assistant(sid, blocks):
    return {"type": "assistant", "sessionId": sid, "timestamp": "2026-08-01T09:01:00.000Z",
            "message": {"role": "assistant", "content": blocks}}


def test_includes_user_prompts_and_assistant_text(tmp_path):
    write_session(tmp_path, "-p", "s1", [
        title("s1", "설치 오류"),
        prompt("s1", "설치가 안 된다"),
        assistant("s1", [{"type": "text", "text": "먼저 설치 스크립트를 읽어보겠습니다"}]),
    ])

    out = et.render_transcripts(et.collect(tmp_path, titles=["설치 오류"]))

    assert "설치가 안 된다" in out
    assert "먼저 설치 스크립트를 읽어보겠습니다" in out


def test_excludes_tool_results_and_tool_inputs(tmp_path):
    write_session(tmp_path, "-p", "s1", [
        title("s1", "t"),
        prompt("s1", "확인해줘"),
        assistant("s1", [
            {"type": "text", "text": "확인합니다"},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/etc/SECRET_PATH"}},
        ]),
        {"type": "user", "sessionId": "s1", "timestamp": "2026-08-01T09:02:00.000Z",
         "cwd": "/home/u/proj", "toolUseResult": {"stdout": "LEAKED_OUTPUT"},
         "message": {"role": "user", "content": "LEAKED_OUTPUT"}},
    ])

    out = et.render_transcripts(et.collect(tmp_path, titles=["t"]))

    assert "LEAKED_OUTPUT" not in out
    assert "SECRET_PATH" not in out
    assert "확인합니다" in out


def test_excludes_thinking_blocks(tmp_path):
    write_session(tmp_path, "-p", "s1", [
        title("s1", "t"),
        prompt("s1", "가자"),
        assistant("s1", [
            {"type": "thinking", "thinking": "PRIVATE_REASONING"},
            {"type": "text", "text": "진행합니다"},
        ]),
    ])

    out = et.render_transcripts(et.collect(tmp_path, titles=["t"]))

    assert "PRIVATE_REASONING" not in out
    assert "진행합니다" in out


def test_excludes_subagent_and_system_injected_records(tmp_path):
    write_session(tmp_path, "-p", "s1", [
        title("s1", "t"),
        prompt("s1", "본문"),
        prompt("s1", "SIDECHAIN_TEXT", isSidechain=True),
        prompt("s1", "SYSTEM_TEXT", promptSource="system"),
        prompt("s1", "META_TEXT", isMeta=True),
        assistant("s1", [{"type": "text", "text": "응답"}]),
    ])

    out = et.render_transcripts(et.collect(tmp_path, titles=["t"]))

    assert "본문" in out
    for leaked in ("SIDECHAIN_TEXT", "SYSTEM_TEXT", "META_TEXT"):
        assert leaked not in out


@pytest.mark.parametrize("secret", [FAKE_AFT, FAKE_GH, FAKE_AWS])
def test_scrubs_secrets_from_both_speakers(tmp_path, secret):
    write_session(tmp_path, "-p", "s1", [
        title("s1", "t"),
        prompt("s1", f"키는 {secret} 이다"),
        assistant("s1", [{"type": "text", "text": f"확인된 키 {secret}"}]),
    ])

    out = et.render_transcripts(et.collect(tmp_path, titles=["t"]))

    assert secret not in out
    assert out.count("[redacted]") == 2


def test_selects_by_session_id(tmp_path):
    write_session(tmp_path, "-p", "wanted", [prompt("wanted", "이걸 원한다"),
                                             assistant("wanted", [{"type": "text", "text": "네"}])])
    write_session(tmp_path, "-p", "other", [prompt("other", "이건 아니다"),
                                            assistant("other", [{"type": "text", "text": "아니오"}])])

    out = et.render_transcripts(et.collect(tmp_path, sessions=["wanted"]))

    assert "이걸 원한다" in out
    assert "이건 아니다" not in out


def test_section_header_names_each_session(tmp_path):
    write_session(tmp_path, "-p", "s1", [title("s1", "첫 세션"), prompt("s1", "a"),
                                         assistant("s1", [{"type": "text", "text": "b"}])])
    write_session(tmp_path, "-p", "s2", [title("s2", "둘째 세션"), prompt("s2", "c"),
                                         assistant("s2", [{"type": "text", "text": "d"}])])

    out = et.render_transcripts(et.collect(tmp_path, titles=["첫 세션", "둘째 세션"]))

    assert "첫 세션" in out
    assert "둘째 세션" in out


def test_unmatched_title_exits_with_clear_message(tmp_path):
    write_session(tmp_path, "-p", "s1", [title("s1", "있는 제목"), prompt("s1", "a"),
                                         assistant("s1", [{"type": "text", "text": "b"}])])

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-dir", str(tmp_path),
         "--title", "없는 제목", "--stdout"], capture_output=True, text=True)

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "없는 제목" in result.stderr


def test_reports_size_so_the_cost_is_visible(tmp_path):
    write_session(tmp_path, "-p", "s1", [title("s1", "t"), prompt("s1", "가" * 300),
                                         assistant("s1", [{"type": "text", "text": "나" * 300}])])

    sessions = et.collect(tmp_path, titles=["t"])
    out = et.render_transcripts(sessions)

    assert et.estimate_tokens(out) > 100
