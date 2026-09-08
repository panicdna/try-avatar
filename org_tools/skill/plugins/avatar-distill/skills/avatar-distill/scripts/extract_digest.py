#!/usr/bin/env python3
"""Summarize local Claude Code transcripts into one line per session.

Read-only, no network. The digest carries only work-shape signals — never tool
results, file contents, diffs, or full prompts — so it can be reviewed and
clustered without pulling raw logs into a model context.

    extract_digest.py [--since YYYY-MM-DD] [--project SUBSTR] [--out PATH | --stdout]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

TITLE_MAX = 100
TOOL_MIX_TOP = 3
REDACTED = "[redacted]"

# Anything matching these never reaches the digest, even in a fallback title.
SECRET_PATTERNS = [
    re.compile(r"\b(?:aft|afd)_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]

# A slash command or `!` bash line is a real user action, but its raw markup
# makes a useless fallback title, so the command label is extracted instead.
ENVELOPE = re.compile(r"<(?:command-name|command-message|command-args|bash-input)>")

# Pure tooling output. It arrives as its own type=user record but the user never
# typed it, so it must not count as a turn or become a title.
OUTPUT_ENVELOPE = re.compile(
    r"<(local-command-stdout|bash-stdout|bash-stderr)>.*?</\1>", re.DOTALL
)
COMMAND_LABEL = [
    re.compile(r"<command-name>\s*/?([^<\s]+)\s*</command-name>"),
    re.compile(r"<command-message>\s*/?([^<\s]+)\s*</command-message>"),
]


def command_label(text: str) -> str | None:
    for pattern in COMMAND_LABEL:
        match = pattern.search(text)
        if match:
            return "/" + match.group(1)
    return None


@dataclass
class Session:
    session_id: str
    date: str
    cwd: str
    title: str
    title_is_fallback: bool
    turns: int
    tool_mix: list[tuple[str, int]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


def scrub(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def is_real_prompt(rec: dict) -> bool:
    """True only for text the user actually typed.

    Subagent turns, system-injected records (meta, background-task
    notifications), tool results, and command output all arrive as type=user and
    would otherwise inflate the turn count that decides whether a session is
    recurring work or a one-off question.
    """
    if rec.get("type") != "user":
        return False
    if rec.get("isSidechain") or rec.get("isMeta") or "toolUseResult" in rec:
        return False
    if rec.get("promptSource") == "system":
        return False
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        return False
    return OUTPUT_ENVELOPE.sub("", content).strip() != ""


def _iter_records(path: Path):
    with path.open(errors="ignore") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue


def read_session(path: Path) -> Session | None:
    """One transcript file -> one Session.

    Returns None for a session where nothing happened — no `ai-title` and no tool
    call. Real histories are full of these (`hi`, `test`, a bare `/model`), and
    they crowd out actual work in the digest.
    """
    first_prompt = None
    first_substantive = None
    first_command = None
    first_ts = None
    cwd = ""
    turns = 0
    ai_title = None
    tools: Counter[str] = Counter()
    skills: set[str] = set()

    for rec in _iter_records(path):
        rec_type = rec.get("type")
        if rec_type == "ai-title" and rec.get("aiTitle"):
            ai_title = rec["aiTitle"]
        elif is_real_prompt(rec):
            turns += 1
            text = (rec.get("message") or {}).get("content", "")
            if first_prompt is None:
                first_prompt = text
                first_ts = rec.get("timestamp") or ""
                cwd = rec.get("cwd") or ""
            if ENVELOPE.search(text):
                if first_command is None:
                    first_command = command_label(text)
            elif first_substantive is None:
                first_substantive = text
        elif rec_type == "assistant":
            for block in (rec.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name") or "?"
                tools[name] += 1
                if name == "Skill":
                    skill = (block.get("input") or {}).get("skill")
                    if skill:
                        skills.add(skill)

    if first_prompt is None:
        return None
    if not ai_title and not tools:
        return None

    if ai_title:
        title, fallback = ai_title, False
    else:
        raw = first_substantive or first_command or first_prompt
        title, fallback = scrub(raw)[:TITLE_MAX], True

    return Session(
        session_id=path.stem,
        date=(first_ts or "")[:10],
        cwd=cwd,
        title=re.sub(r"\s+", " ", title).strip(),
        title_is_fallback=fallback,
        turns=turns,
        tool_mix=tools.most_common(TOOL_MIX_TOP),
        skills=sorted(skills),
    )


def collect_sessions(
    projects_dir: Path, since: str | None = None, project: str | None = None
) -> list[Session]:
    """Top-level session transcripts only.

    The `*/*.jsonl` depth is deliberate: `*/*/subagents/*.jsonl` holds delegated
    subagent work, which is not the user's own and must not shape a Card.
    """
    sessions = []
    for path in sorted(Path(projects_dir).glob("*/*.jsonl")):
        session = read_session(path)
        if session is None:
            continue
        if since and session.date < since:
            continue
        if project and project not in session.cwd:
            continue
        sessions.append(session)
    return sorted(sessions, key=lambda s: (s.date, s.cwd), reverse=True)


def render_digest(sessions: list[Session]) -> str:
    dates = sorted(s.date for s in sessions if s.date)
    span = f"{dates[0]} ~ {dates[-1]}" if dates else "(no dates)"
    paths = {s.cwd for s in sessions}
    skill_calls: Counter[str] = Counter()
    for session in sessions:
        skill_calls.update(session.skills)
    ranked = ", ".join(f"{name} {count}" for name, count in skill_calls.most_common()) or "none"

    lines = [
        f"# avatar-distill digest — {span}",
        f"# sessions: {len(sessions)} | paths: {len(paths)} | skill calls: {ranked}",
        "date\tcwd\ttitle\tturns\ttool_mix\tskills",
    ]
    for s in sessions:
        title = f"~ {s.title}" if s.title_is_fallback else s.title
        tool_mix = "/".join(f"{name} {count}" for name, count in s.tool_mix) or "-"
        lines.append(
            "\t".join([s.date, s.cwd, title, str(s.turns), tool_mix, ",".join(s.skills) or "-"])
        )
    return "\n".join(lines) + "\n"


def default_out() -> Path:
    stamp = date.today().strftime("%Y%m%d")
    return Path.home() / ".agent-factory" / "avatar-distill" / f"digest-{stamp}.tsv"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-dir", default=str(Path.home() / ".claude" / "projects"))
    parser.add_argument("--since", metavar="YYYY-MM-DD")
    parser.add_argument("--project", metavar="SUBSTR", help="match against session cwd")
    parser.add_argument("--out", metavar="PATH")
    parser.add_argument("--stdout", action="store_true", help="print instead of writing a file")
    args = parser.parse_args(argv)

    projects_dir = Path(args.projects_dir).expanduser()
    if not projects_dir.is_dir():
        print(f"error: projects directory not found: {projects_dir}", file=sys.stderr)
        return 2

    sessions = collect_sessions(projects_dir, since=args.since, project=args.project)
    if not sessions:
        print(f"error: no sessions matched under {projects_dir}", file=sys.stderr)
        return 3

    digest = render_digest(sessions)
    if args.stdout:
        sys.stdout.write(digest)
        return 0

    out = Path(args.out).expanduser() if args.out else default_out()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(digest)
    print(f"wrote {len(sessions)} sessions to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
