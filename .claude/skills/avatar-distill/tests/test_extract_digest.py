"""Tests for extract_digest.py.

Fixtures are synthetic. Never put real transcript content here — it would pull
internal project names into the repo and make the tests non-reproducible.
"""

import json
import string
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import extract_digest as ed  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_digest.py"

# Synthetic credentials, built from parts rather than written out. Only the
# prefix and length matter — the tests check that scrub()'s regexes fire — but a
# complete key-shaped literal in the source reads as a real leak to a secret
# scanner, which is what Agent Factory's scan reported for the `ghp_` one.
_LOWER_DIGITS = string.ascii_lowercase + string.digits
FAKE_AFT = "aft_" + _LOWER_DIGITS[:16]
FAKE_AFD = "afd_" + _LOWER_DIGITS[:16]
FAKE_SK = "sk-" + _LOWER_DIGITS[:20]
FAKE_GH = "ghp_" + _LOWER_DIGITS
FAKE_BEARER = "Bearer " + _LOWER_DIGITS[:16]
FAKE_AWS = "AKIA" + (string.ascii_uppercase + string.digits)[:16]


def write_session(root, project, session_id, records, *, subagent=False):
    """Create one transcript file. subagent=True nests it under subagents/."""
    if subagent:
        path = root / project / session_id / "subagents" / "agent-abc123.jsonl"
    else:
        path = root / project / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def prompt(session_id, text, *, ts="2026-08-01T09:00:00.000Z", cwd="/home/u/proj", **extra):
    rec = {
        "type": "user",
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": cwd,
        "message": {"role": "user", "content": text},
    }
    rec.update(extra)
    return rec


def title(session_id, text):
    return {"type": "ai-title", "sessionId": session_id, "aiTitle": text}


def tool_call(session_id, name, tool_input=None, *, ts="2026-08-01T09:01:00.000Z"):
    return {
        "type": "assistant",
        "sessionId": session_id,
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": tool_input or {}}],
        },
    }


def rows(digest):
    """Data rows only — drop the '#' aggregate header and the column header."""
    lines = [ln for ln in digest.splitlines() if ln and not ln.startswith("#")]
    return [ln.split("\t") for ln in lines[1:]]


def test_excludes_subagent_transcripts(tmp_path):
    write_session(tmp_path, "-home-u-proj", "s1", [prompt("s1", "hi"), title("s1", "real work")])
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [prompt("sub", "delegated"), title("sub", "delegated work")],
        subagent=True,
    )

    sessions = ed.collect_sessions(tmp_path)

    assert [s.title for s in sessions] == ["real work"]


def test_turns_counts_only_real_user_prompts(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt("s1", "first"),
            prompt("s1", "second"),
            prompt("s1", "sidechain", isSidechain=True),
            prompt("s1", "meta", isMeta=True),
            prompt("s1", "tool output", toolUseResult={"stdout": "..."}),
            title("s1", "t"),
        ],
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert session.turns == 2


def test_falls_back_to_first_prompt_and_marks_it(tmp_path):
    long_prompt = "가" * 150
    write_session(tmp_path, "-home-u-proj", "s1", [prompt("s1", long_prompt), tool_call("s1", "Bash")])

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title_is_fallback is True
    assert len(session.title) == 100
    assert session.title == "가" * 100


def test_ai_title_wins_over_first_prompt(tmp_path):
    write_session(tmp_path, "-home-u-proj", "s1", [prompt("s1", "raw prompt"), title("s1", "Nice Title")])

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title == "Nice Title"
    assert session.title_is_fallback is False


@pytest.mark.parametrize(
    "secret", [FAKE_AFT, FAKE_AFD, FAKE_SK, FAKE_GH, FAKE_BEARER, FAKE_AWS]
)
def test_redacts_secrets_in_fallback_title(tmp_path, secret):
    write_session(
        tmp_path, "-home-u-proj", "s1", [prompt("s1", f"key is {secret} ok"), tool_call("s1", "Bash")]
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert secret not in session.title
    assert "[redacted]" in session.title


def test_digest_never_contains_tool_results_or_file_content(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt("s1", "read the config"),
            title("s1", "config work"),
            tool_call("s1", "Read", {"file_path": "/etc/SUPER_SECRET_PATH"}),
            {
                "type": "user",
                "sessionId": "s1",
                "timestamp": "2026-08-01T09:02:00.000Z",
                "cwd": "/home/u/proj",
                "toolUseResult": {"stdout": "LEAKED_FILE_CONTENT"},
                "message": {"role": "user", "content": "LEAKED_FILE_CONTENT"},
            },
        ],
    )

    digest = ed.render_digest(ed.collect_sessions(tmp_path))

    assert "LEAKED_FILE_CONTENT" not in digest
    assert "SUPER_SECRET_PATH" not in digest
    assert "Read" in digest  # the tool name itself is a wanted signal


def test_skips_malformed_lines(tmp_path):
    path = write_session(tmp_path, "-home-u-proj", "s1", [prompt("s1", "hi"), title("s1", "good")])
    with path.open("a") as fh:
        fh.write("{not json at all\n")
        fh.write("\n")

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title == "good"


def test_tool_mix_keeps_top_three_by_count(tmp_path):
    records = [prompt("s1", "hi"), title("s1", "t")]
    records += [tool_call("s1", "Bash") for _ in range(5)]
    records += [tool_call("s1", "Edit") for _ in range(3)]
    records += [tool_call("s1", "Read") for _ in range(2)]
    records += [tool_call("s1", "Write") for _ in range(1)]
    write_session(tmp_path, "-home-u-proj", "s1", records)

    (session,) = ed.collect_sessions(tmp_path)

    assert session.tool_mix == [("Bash", 5), ("Edit", 3), ("Read", 2)]


def test_collects_skill_names_from_skill_tool(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt("s1", "hi"),
            title("s1", "t"),
            tool_call("s1", "Skill", {"skill": "plugin-packager"}),
            tool_call("s1", "Skill", {"skill": "plugin-packager"}),
            tool_call("s1", "Skill", {"skill": "agent-factory-api"}),
        ],
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert sorted(session.skills) == ["agent-factory-api", "plugin-packager"]


def test_since_filter_drops_older_sessions(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "old",
        [prompt("old", "x", ts="2026-01-05T09:00:00.000Z"), tool_call("old", "Bash")],
    )
    write_session(
        tmp_path,
        "-home-u-proj",
        "new",
        [prompt("new", "y", ts="2026-08-05T09:00:00.000Z"), tool_call("new", "Bash")],
    )

    sessions = ed.collect_sessions(tmp_path, since="2026-06-01")

    assert [s.session_id for s in sessions] == ["new"]


def test_project_filter_matches_cwd_substring(tmp_path):
    write_session(
        tmp_path, "-home-u-a", "s1", [prompt("s1", "x", cwd="/home/u/WORK/skill"), tool_call("s1", "Bash")]
    )
    write_session(
        tmp_path, "-home-u-b", "s2", [prompt("s2", "y", cwd="/home/u/WORK/other"), tool_call("s2", "Bash")]
    )

    sessions = ed.collect_sessions(tmp_path, project="skill")

    assert [s.session_id for s in sessions] == ["s1"]


def test_missing_projects_dir_exits_with_clear_message(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-dir", str(tmp_path / "nope"), "--stdout"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "not found" in result.stderr.lower()


def test_empty_projects_dir_exits_with_clear_message(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-dir", str(tmp_path), "--stdout"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "no sessions" in result.stderr.lower()


def test_digest_has_aggregate_header_and_column_header(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [prompt("s1", "hi"), title("s1", "t"), tool_call("s1", "Skill", {"skill": "brainstorming"})],
    )

    digest = ed.render_digest(ed.collect_sessions(tmp_path))
    lines = digest.splitlines()

    assert lines[0].startswith("#")
    assert "sessions: 1" in digest
    assert "brainstorming 1" in digest
    assert "date\tcwd\ttitle\tturns\ttool_mix\tskills" in lines


def test_system_injected_record_is_not_a_turn(tmp_path):
    """Background-task notifications arrive as type=user with promptSource=system."""
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt("s1", "start the job"),
            prompt(
                "s1",
                "<task-notification>\n<task-id>abc</task-id>\n<status>completed</status>",
                promptSource="system",
            ),
            title("s1", "t"),
            tool_call("s1", "Bash"),
        ],
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert session.turns == 1


def test_task_notification_never_becomes_a_title(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt("s1", "<task-notification>\n<task-id>abc</task-id>", promptSource="system"),
            prompt("s1", "이어서 진행해줘"),
            tool_call("s1", "Bash"),
        ],
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title == "이어서 진행해줘"
    assert "task-notification" not in session.title


@pytest.mark.parametrize(
    "content",
    [
        "<local-command-stdout>Catch you later!</local-command-stdout>",
        "<bash-stdout>Desktop\nWORK</bash-stdout><bash-stderr></bash-stderr>",
    ],
)
def test_command_output_only_record_is_not_a_turn(tmp_path, content):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [prompt("s1", "run it"), prompt("s1", content), title("s1", "t"), tool_call("s1", "Bash")],
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert session.turns == 1


def test_command_args_envelope_unwraps_to_the_command_label(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt(
                "s1",
                "<command-name>/loop</command-name> <command-args>5m check</command-args>",
            ),
            tool_call("s1", "Bash"),
        ],
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title == "/loop"


def test_drops_session_with_no_title_and_no_tool_calls(tmp_path):
    """Nothing happened: no ai-title, no tool ran. Real histories are full of these."""
    write_session(tmp_path, "-home-u-proj", "noise", [prompt("noise", "hi"), prompt("noise", "hi")])
    write_session(tmp_path, "-home-u-proj", "work", [prompt("work", "do it"), tool_call("work", "Bash")])

    sessions = ed.collect_sessions(tmp_path)

    assert [s.session_id for s in sessions] == ["work"]


def test_keeps_untitled_session_when_a_tool_ran(tmp_path):
    write_session(tmp_path, "-home-u-proj", "s1", [prompt("s1", "hi"), tool_call("s1", "Bash")])

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title == "hi"


def test_keeps_titled_session_even_with_no_tool_calls(tmp_path):
    write_session(tmp_path, "-home-u-proj", "s1", [prompt("s1", "why?"), title("s1", "A real question")])

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title == "A real question"


def test_prefers_substantive_prompt_over_slash_command_envelope(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt("s1", "<command-name>/model</command-name> <command-message>model</command-message>"),
            prompt("s1", "이제 릴리즈 태그를 만들어줘"),
            tool_call("s1", "Bash"),
        ],
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title == "이제 릴리즈 태그를 만들어줘"
    assert session.turns == 2


def test_falls_back_to_command_name_when_every_prompt_is_an_envelope(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt("s1", "<command-name>/plugin</command-name> <command-message>plugin</command-message>"),
            tool_call("s1", "Bash"),
        ],
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title == "/plugin"


def test_uses_command_message_when_command_name_is_absent(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt("s1", "<command-message>claude-hud:setup</command-message> <foo>x</foo>"),
            tool_call("s1", "Read"),
        ],
    )

    (session,) = ed.collect_sessions(tmp_path)

    assert session.title == "/claude-hud:setup"


def test_envelope_markup_never_survives_into_the_digest(tmp_path):
    write_session(
        tmp_path,
        "-home-u-proj",
        "s1",
        [
            prompt("s1", "<command-name>/model</command-name> <bash-input>pwd</bash-input>"),
            tool_call("s1", "Bash"),
        ],
    )

    digest = ed.render_digest(ed.collect_sessions(tmp_path))

    assert "<command-name>" not in digest
    assert "<bash-input>" not in digest


def test_fallback_titles_are_marked_in_rendered_row(tmp_path):
    write_session(tmp_path, "-home-u-proj", "s1", [prompt("s1", "no ai title here"), tool_call("s1", "Bash")])

    digest = ed.render_digest(ed.collect_sessions(tmp_path))
    (row,) = rows(digest)

    assert row[2].startswith("~ ")
