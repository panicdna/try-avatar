#!/usr/bin/env python3
"""Extract conversation text only, for one cluster's sessions.

The digest gives session titles; titles alone make thin Task text. This produces
the *conversation* — user prompts and assistant prose — so a subagent can read a
cluster and extract the procedure actually followed.

Measured on real sessions: conversation text is about 3% of the raw transcript,
because tool results are the bulk. Six sessions came to ~24k tokens. Read a
cluster, not a whole history, and delegate the read to a subagent so the text
never enters the main context.

    extract_transcript.py --title "…" [--title "…"] [--session ID] [--stdout]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from extract_digest import OUTPUT_ENVELOPE, is_real_prompt, scrub, _iter_records

USER = "[사용자]"
ASSISTANT = "[어시스턴트]"


@dataclass
class Transcript:
    session_id: str
    title: str
    turns: list[tuple[str, str]] = field(default_factory=list)


def read_transcript(path: Path) -> Transcript:
    """Conversation only.

    Tool results, tool_use inputs, and thinking blocks are skipped: they hold
    file contents, command output, and private reasoning that must not travel
    into a shared Card.
    """
    t = Transcript(session_id=path.stem, title="")
    for rec in _iter_records(path):
        kind = rec.get("type")
        if kind == "ai-title" and rec.get("aiTitle"):
            t.title = rec["aiTitle"]
        elif is_real_prompt(rec):
            text = (rec.get("message") or {}).get("content", "")
            text = OUTPUT_ENVELOPE.sub("", text).strip()
            if text:
                t.turns.append((USER, scrub(text)))
        elif kind == "assistant" and not rec.get("isSidechain"):
            for block in (rec.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = (block.get("text") or "").strip()
                    if text:
                        t.turns.append((ASSISTANT, scrub(text)))
    return t


def collect(projects_dir: Path, titles=None, sessions=None) -> list[Transcript]:
    wanted_titles = list(titles or [])
    wanted_sessions = set(sessions or [])
    found: list[Transcript] = []
    matched_titles: set[str] = set()

    for path in sorted(Path(projects_dir).glob("*/*.jsonl")):
        if wanted_sessions and path.stem in wanted_sessions:
            found.append(read_transcript(path))
            continue
        if not wanted_titles:
            continue
        t = read_transcript(path)
        if t.title in wanted_titles:
            found.append(t)
            matched_titles.add(t.title)

    missing = [x for x in wanted_titles if x not in matched_titles]
    missing += [s for s in wanted_sessions if s not in {t.session_id for t in found}]
    if missing:
        raise LookupError(missing)

    order = {title: i for i, title in enumerate(wanted_titles)}
    return sorted(found, key=lambda t: order.get(t.title, len(order)))


def render_transcripts(transcripts: list[Transcript]) -> str:
    parts = []
    for t in transcripts:
        parts.append("=" * 70)
        parts.append(f"## 세션: {t.title or t.session_id}")
        parts.append("=" * 70)
        for speaker, text in t.turns:
            parts.append(f"{speaker} {text}")
    return "\n\n".join(parts) + "\n"


def estimate_tokens(text: str) -> int:
    return len(text) // 3


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-dir", default=str(Path.home() / ".claude" / "projects"))
    parser.add_argument("--title", action="append", default=[], help="ai-title, repeatable")
    parser.add_argument("--session", action="append", default=[], help="session id, repeatable")
    parser.add_argument("--out", metavar="PATH")
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args(argv)

    if not args.title and not args.session:
        print("error: pass at least one --title or --session", file=sys.stderr)
        return 2

    projects_dir = Path(args.projects_dir).expanduser()
    if not projects_dir.is_dir():
        print(f"error: projects directory not found: {projects_dir}", file=sys.stderr)
        return 2

    try:
        transcripts = collect(projects_dir, titles=args.title, sessions=args.session)
    except LookupError as exc:
        for item in exc.args[0]:
            print(f"error: no session matched: {item}", file=sys.stderr)
        return 3

    text = render_transcripts(transcripts)
    if args.stdout:
        sys.stdout.write(text)
    else:
        out = Path(args.out).expanduser() if args.out else Path("/tmp/avatar-distill-cluster.md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"wrote {out}")
    print(
        f"{len(transcripts)} sessions · {len(text) // 1024}KB · ~{estimate_tokens(text):,} tokens",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
