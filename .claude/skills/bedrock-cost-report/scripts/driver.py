#!/usr/bin/env python3
"""Monthly Claude Code / AWS Bedrock cost report generator.

Primary input is `--fetch`, which pulls your own usage row from the DS Bedrock
dashboard's JSON API (see fetch_usage.py). Fallback is the AICM per-user CSV export
(same fields: total_cost + per-model tokens + calls/sessions/commits/PR/lines in one
row), pasted by hand. Local Claude Code session logs
(~/.claude/projects/**/*.jsonl) add a per-project / per-day breakdown that the CSV
does not contain. The output is a self-contained HTML report: cost breakdown,
methodology, cross-check, and cost-saving insights.

Rates and model names are NOT hardcoded. They live in rates.json (user-maintained,
because models and prices change). Each token type is weighted by its model's Bedrock
rate to get a "cost proxy", then normalized to the actual billed total. Local-log
attribution reads each message's own model, so mixed-model usage is handled -- there
is no all-Opus fallback. A model with no rate entry is reported, never guessed.

Usage:
  driver.py --fetch                              # you, this month -- the usual call
  driver.py --fetch --month 2026-07
  driver.py --month 2026-08 --csv aicm-export.csv
  driver.py --month 2026-08 --csv aicm-export.csv --employee jibin.sung
  driver.py --month 2026-08 --cost 701.24        # no CSV: local logs only
  driver.py --month 2026-08 --csv x.csv --rates /path/rates.json --out report.html
"""
import argparse, csv, datetime as dt, glob, html, io, json, os, re, subprocess, sys, time
from collections import defaultdict

FIELDS = ("in", "cache_read", "cache_write", "out")  # canonical token-type order


def load_rates(path: str) -> dict:
    """Load {model_substring: {in,cache_read,cache_write,out}} from rates.json."""
    with open(path) as fh:
        raw = json.load(fh)
    return {k.lower(): v for k, v in raw.items() if not k.startswith("_")}


def caching_1h_enabled() -> bool:
    """True if THIS machine already has the 1-hour cache TTL beta turned on.

    Checked so the cache-miss insight doesn't recommend a setting the user
    already has. Same precedence Claude Code itself uses: an exported env var
    wins, otherwise fall back to the user settings.json `env` block. Self-only
    by the same design as --fetch -- it reads this machine's own config.
    """
    if os.environ.get("ENABLE_PROMPT_CACHING_1H"):
        return True
    try:
        with open(os.path.expanduser("~/.claude/settings.json")) as fh:
            return bool(json.load(fh).get("env", {}).get("ENABLE_PROMPT_CACHING_1H"))
    except (OSError, json.JSONDecodeError):
        return False


def _norm(s: str) -> str:
    """Lowercase and drop every non-alphanumeric character.

    The same model arrives with different separators depending on the source:
    `sonnet_5` as a CSV column suffix, `claude-sonnet-5-20260514` in a local log.
    Collapsing separators lets one rates.json key match both.
    """
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def rate_for(model_name: str, rates: dict):
    """Return the rate dict whose key is a substring of model_name, else None.

    Keys are tried in rates.json order and the first match wins, which is why
    that file lists generations separately instead of one `opus` catch-all --
    Opus 4.1 is still served on Bedrock at 3x the Opus 4.5+ price. No default
    tier: an unknown model is surfaced, not silently priced as Opus.
    """
    n = _norm(model_name)
    for key, r in rates.items():
        k = _norm(key)
        if k and k in n:
            return r
    return None


def family_rate(family: str, rates: dict):
    """Cheapest rate entry belonging to `family` (e.g. "sonnet"), else None.

    The model-shift simulation names a family while rates.json keys name
    generations, so `rate_for("sonnet", ...)` finds nothing. Cheapest is also
    the realistic choice: someone moving work off Opus lands on the current
    Sonnet, which is the least expensive entry in the family.
    """
    f = _norm(family)
    hits = [r for k, r in rates.items() if f in _norm(k)]
    return min(hits, key=lambda r: r["out"]) if hits else None


CACHE_MISS_FAST_MIN = 5   # shortest prompt-cache TTL, so gaps under this can't be expiry


def hm(tokens: float) -> str:
    n = float(tokens)
    if n >= 1e6:
        return f"{n/1e6:.1f}M"
    if n >= 1e3:
        return f"{n/1e3:.0f}K"
    return f"{int(n)}"


def cost_of(tokens_by_type: dict, rate: dict) -> float:
    """USD for a {in,cache_read,cache_write,out} token dict given a per-1M rate."""
    return sum(tokens_by_type.get(t, 0) * rate[t] for t in FIELDS) / 1e6


def _ts(s: str):
    """Parse a log timestamp, or None when it is missing/unparseable."""
    try:
        return dt.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except Exception:
        return None


def scan_logs(month: str, cwd: str):
    """Aggregate the month's local usage, split BY MODEL.

    Returns (proj, day, proj_day, sessions, vers) where:
      proj     = {project_dir: {model: {in,cache_read,cache_write,out}}}
      day      = {YYYY-MM-DD: {model: {...}}}   (ALL projects, not just cwd)
      proj_day = {project_dir: {YYYY-MM-DD: {model: {...}}}}  (per-project drill-down)
      sessions = [{turns, cache_read, cache_write, ctx_max, miss_write,
                   miss_n, miss_fast}]  per session file
      vers     = {claude_code_version: [miss_write, cache_write]}

    **Observed cache misses.** A turn that reports `cache_read == 0` while
    writing cache re-established the whole prefix instead of extending it: per
    the documented `tools -> system -> messages` hierarchy, nothing at any level
    hit, so every cached token was paid for a second time. Two exclusions keep
    this honest -- a session's first turn (its write is the initial one, not a
    re-write) and sidechain turns (a subagent starts with a fresh context by
    design, so its opening write is the price of delegation, not waste).
    `miss_fast` counts misses that follow a gap shorter than the shortest cache
    TTL, which therefore cannot be expiry and point at an invalidation instead.
    """
    root = os.path.expanduser("~/.claude/projects")
    proj: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    day: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    proj_day: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(int))))
    sessions = []
    vers: dict = defaultdict(lambda: [0, 0])
    fast_sec = CACHE_MISS_FAST_MIN * 60
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
        project = os.path.basename(os.path.dirname(f))
        s = {"turns": 0, "cache_read": 0, "cache_write": 0, "ctx_max": 0,
             "miss_write": 0, "miss_n": 0, "miss_fast": 0}
        prev, first = None, True
        with open(f, errors="ignore") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                ts = o.get("timestamp", "")
                if not ts.startswith(month):
                    continue
                msg = o.get("message") or {}
                u = msg.get("usage") or {}
                if not u:
                    continue
                model = msg.get("model") or "unknown"
                rec = {
                    "in": u.get("input_tokens", 0),
                    "cache_read": u.get("cache_read_input_tokens", 0),
                    "cache_write": u.get("cache_creation_input_tokens", 0),
                    "out": u.get("output_tokens", 0),
                }
                day_key = ts[:10]
                for t in FIELDS:
                    proj[project][model][t] += rec[t]
                    day[day_key][model][t] += rec[t]
                    proj_day[project][day_key][model][t] += rec[t]
                s["turns"] += 1
                s["cache_read"] += rec["cache_read"]
                s["cache_write"] += rec["cache_write"]
                # cache_read + cache_write on one call ~ context size that turn
                s["ctx_max"] = max(s["ctx_max"], rec["cache_read"] + rec["cache_write"])
                now = _ts(ts)
                ver = o.get("version") or "?"
                vers[ver][1] += rec["cache_write"]
                if not first and not o.get("isSidechain") \
                        and rec["cache_read"] == 0 and rec["cache_write"] > 0:
                    s["miss_write"] += rec["cache_write"]
                    s["miss_n"] += 1
                    vers[ver][0] += rec["cache_write"]
                    if prev and now and (now - prev).total_seconds() <= fast_sec:
                        s["miss_fast"] += rec["cache_write"]
                first = False
                prev = now or prev
        if s["turns"]:
            sessions.append(s)
    return proj, day, proj_day, sessions, dict(vers)


def bucket_cost(by_model: dict, rates: dict, unpriced: set) -> float:
    """Total USD-proxy for {model: {tokens}}, recording models lacking a rate."""
    total = 0.0
    for model, toks in by_model.items():
        if not any(toks.values()):
            continue
        r = rate_for(model, rates)
        if r is None:
            unpriced.add(model)
            continue
        total += cost_of(toks, r)
    return total


def git_day_themes(month: str, repo_path: str) -> dict:
    """Map YYYY-MM-DD -> commit subjects (first few) from repo_path's own git log.

    Called once per project (repo_path = unmangle(project)) so each project's
    drill-down shows ITS OWN commits, not whichever repo the report happened to
    run from -- a project with no resolvable/git repo just gets no themes.
    """
    since = month + "-01"          # month is validated /\d{4}-\d{2}/ in main()
    until = month + "-31"          # built outside the call so no format string
    argv = ["git", "-C", repo_path, "log", "--since", since, "--until", until,
            "--date=short", "--pretty=format:%ad|%s"]
    try:
        out = subprocess.run(
            argv, capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return {}
    themes = defaultdict(list)
    for line in out.splitlines():
        if "|" in line:
            d, subj = line.split("|", 1)
            themes[d].append(subj)
    return {d: " | ".join(s[:70] for s in subs[:4]) for d, subs in themes.items()}


def smooth_path(pts, lo: float, hi: float) -> str:
    """Catmull-Rom through `pts`, emitted as cubic beziers.

    A polyline made every day look like a corner. Control points are pulled from
    each point's neighbours at 1/6 tension, and their y is clamped to the plot
    band so a steep day cannot bow the curve outside the chart.
    """
    if len(pts) < 2:
        return f"M {pts[0][0]:.1f},{pts[0][1]:.1f}" if pts else ""
    clamp = lambda y: min(max(y, lo), hi)
    d = [f"M {pts[0][0]:.1f},{pts[0][1]:.1f}"]
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, clamp(p1[1] + (p2[1] - p0[1]) / 6))
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, clamp(p2[1] - (p3[1] - p1[1]) / 6))
        d.append(f"C {c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} "
                 f"{p2[0]:.1f},{p2[1]:.1f}")
    return " ".join(d)


def day_chart_svg(day_billed: dict, refs=(), width=880, height=260, pad=30) -> str:
    """Inline SVG line+area chart of cost by day -- flow only, no exact numbers.

    No JS, no charting library: just a path computed in Python. Exact per-day
    figures live in each project's drill-down table.

    The aspect ratio is preserved. Stretching it to the container was squashing
    the labels horizontally, which is why they were hard to read; the chart now
    scales as a whole, so text keeps its shape.

    `refs` draws dashed horizontal reference lines as (value, label). This is how
    the published benchmarks are shown: the daily series already exists, so a
    comparison belongs on it rather than in an average. An average would have
    needed an active-day count, and the only one available comes from THIS
    machine's logs while the bill covers every environment -- a denominator too
    small for its numerator, which inflates the result.
    """
    days = sorted(day_billed)
    if not days:
        return '<p class="note">데이터 없음</p>'
    vals = [day_billed[d] for d in days]
    vmax = max(vals) or 1.0
    n = len(days)
    step = (width - 2 * pad) / max(n - 1, 1)

    def y_of(v):
        return height - pad - (v / vmax) * (height - 2 * pad)

    pts = [(pad + i * step, y_of(v)) for i, v in enumerate(vals)]
    line = smooth_path(pts, pad, height - pad)
    base = height - pad
    area = f"{line} L {pts[-1][0]:.1f},{base:.1f} L {pts[0][0]:.1f},{base:.1f} Z"
    peak_i = vals.index(vmax)
    # A line above the peak would sit off-chart, so skip it rather than clamp it
    # to the top edge, where it would read as "you are at the benchmark".
    ref_svg = "".join(
        f'<line x1="{pad}" y1="{y_of(v):.1f}" x2="{width - pad}" y2="{y_of(v):.1f}" '
        f'stroke="#93a0b8" stroke-width="1" stroke-dasharray="5 4" opacity=".6"/>'
        f'<text x="{pad + 5}" y="{y_of(v) - 5:.1f}" class="axis">{esc(lab)}</text>'
        for v, lab in refs if 0 < v < vmax)
    return (
        f'<svg viewBox="0 0 {width} {height}" class="daychart" role="img" '
        f'aria-label="날짜별 비용 흐름">'
        f'<path d="{area}" fill="#4f7cff1f"/>'
        f'{ref_svg}'
        f'<path d="{line}" fill="none" stroke="#4f7cff" stroke-width="2.5" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{pts[peak_i][0]:.1f}" cy="{pts[peak_i][1]:.1f}" r="3.5" '
        f'fill="#4f7cff"/>'
        f'<text x="{pad}" y="{height - 6}" class="axis">{esc(days[0])}</text>'
        f'<text x="{width - pad}" y="{height - 6}" text-anchor="end" class="axis">{esc(days[-1])}</text>'
        f'<text x="{pts[peak_i][0]:.1f}" y="{max(pts[peak_i][1] - 8, 10):.1f}" '
        f'text-anchor="middle" class="axis">${vmax:,.0f}</text>'
        f'</svg>'
    )


# --- AICM CSV ingestion -------------------------------------------------------
# type token -> substrings that identify a column's token type. Adjust if AICM
# renames columns; nothing else in the code assumes specific column names.
COLPATS = {
    "cache_read": ("cache_read", "cache_rea"),
    "cache_write": ("cache_write", "cache_writ", "cache_creation"),
    "in": ("input", "prompt"),
    "out": ("output", "completion"),
}


def _first_col(row: dict, needles):
    for c in row:
        if any(n in c.lower() for n in needles):
            return c
    return None


def _to_float(v):
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


# generic column words to strip; whatever remains is the model key
GENERIC = {"input", "output", "cache", "read", "write", "creation", "tokens",
           "token", "num", "cnt", "count", "of", "total", "prompt", "completion"}


def _row_to_capture(row: dict) -> dict:
    models: dict = defaultdict(lambda: {t: 0.0 for t in FIELDS})
    for col, val in row.items():
        cl = col.lower()
        ttype = next((t for t, pats in COLPATS.items() if any(p in cl for p in pats)), None)
        if ttype is None:
            continue
        # model = column words minus generic ones (input_tokens_opus -> opus)
        parts = [p for p in re.split(r"[^a-z0-9]+", cl) if p and p not in GENERIC]
        suffix = "_".join(parts) or "unknown"
        models[suffix][ttype] += _to_float(val) / 1e6  # store in M tokens
    total_col = _first_col(row, ("total_cost", "total cost"))
    def col(*needles):
        return _to_float(row.get(_first_col(row, needles) or ""))
    return {
        "total_cost": _to_float(row.get(total_col)) if total_col else None,
        "calls": col("call_count", "call count"),
        "sessions": col("session"),
        "commit": col("commit"),
        "prs": col("pull_request", "pull request"),
        "lines_added": col("lines_added", "lines added"),
        "lines_removed": col("lines_removed", "lines removed"),
        "cli_sec": col("cli_active_sec", "cli active"),
        "user_sec": col("user_active_sec", "user active"),
        "models": {m: v for m, v in models.items() if any(v.values())},
    }


def parse_aicm_csv(source: str, employee):
    """Parse AICM data from a file, or from stdin when source is '-'.

    Corp exports are often DRM-locked, so the usual path is: user pastes the
    header + their row (Excel copy = tab-delimited, CSV = comma) and we read it
    via stdin. Delimiter is auto-detected (tab / comma / semicolon).
    """
    text = sys.stdin.read() if source == "-" else \
        open(source, encoding="utf-8-sig").read()
    return parse_aicm_text(text, employee)


def parse_aicm_text(text: str, employee):
    text = text.lstrip("\ufeff").strip("\n")
    if not text.strip():
        raise ValueError("empty CSV input")
    header = text.splitlines()[0]
    delim = "\t" if "\t" in header else (";" if ";" in header and "," not in header else ",")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
    if not rows:
        raise ValueError("no data rows in CSV input")
    row = rows[0]
    if employee:
        idc = _first_col(row, ("employee", "user", "name", "id"))
        match = [r for r in rows if idc and employee.lower() in (r.get(idc) or "").lower()]
        if match:
            row = match[0]
    return _row_to_capture(row)


# --- report assembly ----------------------------------------------------------
def esc(s) -> str:
    return html.escape(str(s or ""))


def bar(pct: float, color: str) -> str:
    return f'<div class="bar"><span style="width:{max(1,round(pct))}%;background:{color}"></span></div>'


def breakdown(models_M: dict, rates: dict, total_cost: float):
    """Model + token-type cost rows (billed) from {model:{type:tokens_M}}.

    Returns (model_rows, type_rows, scale, unpriced). Models without a rate are
    returned in `unpriced` and excluded from the $ split (never priced as Opus).
    """
    unpriced: set = set()
    priced = {}
    type_list = [0.0, 0.0, 0.0, 0.0]
    for m, tk in models_M.items():
        r = rate_for(m, rates)
        if r is None:
            if any(tk.values()):
                unpriced.add(m)
            continue
        list_c = sum(tk[t] * r[t] for t in FIELDS)
        priced[m] = (sum(tk.values()), list_c)
        for i, t in enumerate(FIELDS):
            type_list[i] += tk[t] * r[t]
    list_sum = sum(c for _, c in priced.values()) or 1.0
    scale = total_cost / list_sum
    model_rows = sorted(
        ((m, tok, c * scale, c * scale / total_cost * 100 if total_cost else 0)
         for m, (tok, c) in priced.items()), key=lambda x: -x[2])
    labels = {"in": "Input", "cache_read": "Cache Read",
              "cache_write": "Cache Write", "out": "Output"}
    type_tok = {t: sum(tk.get(t, 0) for tk in models_M.values()) for t in FIELDS}
    order = ["cache_read", "cache_write", "out", "in"]
    ti = {t: i for i, t in enumerate(FIELDS)}
    type_rows = [(labels[t], type_tok[t], type_list[ti[t]] * scale,
                  type_list[ti[t]] * scale / total_cost * 100 if total_cost else 0)
                 for t in order]
    return model_rows, type_rows, scale, unpriced


def unmangle(name: str, root="/"):
    """Recover a real path from a `~/.claude/projects` dir name, or None.

    The log dir name is the project path with every non-alphanumeric character
    replaced by `-`, so `/home/u/WORK/alpha-agent-v3` and `/home/u/.config/x`
    both collapse into strings that cannot be split back on `-`. Walk the real
    filesystem instead and, at each level, take the child whose own mangled name
    matches the remaining prefix (longest first, so `alpha-agent-v3` wins over a
    sibling `alpha`). The replacement is 1:1, so mangled and real names have the
    same length and the consumed prefix is just `len(mangled_child)`.
    """
    def cut(s, n):            # drop the consumed name + exactly ONE separator,
        s = s[n:]             # so a leading `-` standing in for `.` survives
        return s[1:] if s.startswith("-") else s

    rest, path = cut(name, 0), root
    while rest:
        try:
            children = sorted(os.listdir(path), key=len, reverse=True)
        except OSError:
            return None
        for child in children:
            m = re.sub(r"[^A-Za-z0-9]", "-", child)
            if rest == m or rest.startswith(m + "-"):
                path, rest = os.path.join(path, child), cut(rest, len(m))
                break
        else:
            return None
    return path


def session_stats(sessions: list) -> dict:
    """Context-hygiene aggregates from local session files.

    ctx_per_turn is a ratio, so session resume/fork message duplication inflates
    numerator and denominator alike -- it survives the local-log caveat that makes
    absolute counts untrustworthy.
    """
    turns = sum(s["turns"] for s in sessions)
    cr = sum(s["cache_read"] for s in sessions)
    if not turns or not cr:
        return {}
    top = sorted(sessions, key=lambda s: -s["cache_read"])[:8]
    longs = [s for s in sessions if s["turns"] >= 50]
    cw = sum(s["cache_write"] for s in sessions)
    miss_w = sum(s["miss_write"] for s in sessions)
    return {
        "n": len(sessions), "turns": turns, "ctx_per_turn": cr / turns,
        "top_n": len(top), "top_share": sum(s["cache_read"] for s in top) / cr,
        "long_n": len(longs), "long_share": sum(s["cache_read"] for s in longs) / cr,
        "ctx_max": max(s["ctx_max"] for s in sessions),
        "cache_write": cw, "miss_write": miss_w,
        "miss_n": sum(s["miss_n"] for s in sessions),
        "miss_share": (miss_w / cw) if cw else 0.0,
        # Share of the misses that a cache expiry cannot explain, so the cause is
        # an invalidation (tool definitions, MCP connecting mid-session, thinking
        # config, model switch) rather than an idle gap.
        "miss_fast_share": (sum(s["miss_fast"] for s in sessions) / miss_w) if miss_w else 0.0,
    }


def shift_sim(models_M: dict, rates: dict, total_cost: float, frac=0.7,
              target="sonnet"):
    """Bill if `frac` of Opus token volume had run on `target` instead.

    Ratio-based, so it inherits the report's normalization to the real bill --
    it is a scale estimate, not a quote. Two reasons it is an upper bound on the
    saving: a cheaper model may need more turns, and models from the 4.7
    generation on use a tokenizer that produces ~30% more tokens for the same
    text, so token volume does not carry across a switch unchanged.
    """
    tr = family_rate(target, rates)
    if not tr:
        return None
    base = new = 0.0
    for m, tk in models_M.items():
        r = rate_for(m, rates)
        if r is None:
            continue
        base += cost_of(tk, r)
        if "opus" in m.lower():
            new += cost_of({t: tk[t] * (1 - frac) for t in FIELDS}, r)
            new += cost_of({t: tk[t] * frac for t in FIELDS}, tr)
        else:
            new += cost_of(tk, r)
    return total_cost * new / base if base else None


# Anthropic's published enterprise averages, for a comparison line that does not
# depend on this org. Source: https://code.claude.com/docs/en/costs --
# "around $13 per developer per active day and $150-250 per developer per month,
#  with costs remaining below $30 per active day for 90% of users".
BENCH = {"day_avg": 13, "day_p90": 30, "month_lo": 150, "month_hi": 250}

CTX = "컨텍스트 효율"      # why the bill is this size
YIELD = "산출 대비 비용"   # what the money turned into
GROUP_HINT = {
    CTX: "비용이 왜 이만큼 나왔는지, 어디를 줄일 수 있는지",
    YIELD: "그 돈이 무엇으로 바뀌었는지. 좋고 나쁨의 공개된 기준이 없어 판정은 비워둠",
}

GOOD, OK, CHECK = "양호", "보통", "점검"


def rate_high(v, cuts):
    """Bigger is better, banded by measured tercile cut points (lower, upper)."""
    return GOOD if v >= cuts[1] else (OK if v >= cuts[0] else CHECK)


# Claude Code's own /usage raises a cache-miss behaviour flag at this share, so it
# is the one published line available for that metric. There is no documented
# second cut point, and inventing one would put a made-up number next to a real
# one -- so this metric gets two states, not three.
MISS_FLAG_PCT = 10

RATING_CLS = {GOOD: "good", OK: "ok", CHECK: "check"}


def rate_trend(now: float, before: float, lower_is_better=True, tol=0.10) -> str:
    """양호/보통/점검 against the same metric last month.

    Deliberately the same three words the other rows use. A rising number is
    점검 (worth a look), not 악화 -- whether the rise was bad depends on what the
    month was spent on, which this cannot know. The two figures being compared
    are printed in the value cell so the reader can judge for themselves.

    For the two context metrics there is no peer to compare against -- nobody
    else's session logs are on this machine -- and no published threshold either.
    Your own previous month is the one honest yardstick left, and it happens to
    be the one you can actually move. Inside +/-10% is called flat.
    """
    if not before or not now:
        return ""
    ch = (now - before) / before
    if abs(ch) < tol:
        return OK
    return GOOD if ((ch < 0) == lower_is_better) else CHECK


def prev_month(m: str) -> str:
    y, mo = (int(x) for x in m.split("-"))
    return f"{y - 1:04d}-12" if mo == 1 else f"{y:04d}-{mo - 1:02d}"


def _pct_change(cur, prev, tol=0.10):
    """(pct, direction) with direction in up/down/flat, same +/-10% flat band as
    `rate_trend`. Deliberately NOT `rate_trend` itself: there is no published
    or measured basis for whether more cost, calls, sessions, or commits is
    "good" -- the same reason 산출 대비 비용 rows carry no 판정. This reports
    the arithmetic direction only, never a grade.
    """
    if not cur or not prev:
        return None, None
    pct = (cur - prev) / prev * 100
    if abs(pct) / 100 < tol:
        return pct, "flat"
    return pct, ("up" if pct > 0 else "down")


def delta_html(cur, prev) -> str:
    """Small 전월 대비 chip for a top-card number. Red/blue follow the Korean
    stock-ticker convention (상승 red, 하락 blue) -- a direction, not a grade."""
    pct, direction = _pct_change(cur, prev)
    if direction is None:
        return ""
    if direction == "flat":
        return '<span class="delta d-flat">&#65293; 전월과 비슷</span>'
    arrow, cls = ("&#9650;", "d-up") if direction == "up" else ("&#9660;", "d-down")
    return f'<span class="delta {cls}">{arrow} {abs(pct):.0f}% 전월 대비</span>'


def terciles(values):
    """(lower, upper) cut points splitting `values` into three equal groups.

    Used so a rating comes from the org's measured distribution instead of a
    number someone picked because it looked reasonable. Returns None when there
    is not enough data to split.
    """
    v = sorted(x for x in values if x is not None)
    if len(v) < 9:          # too few to call anything a tercile
        return None
    return v[len(v) // 3], v[2 * len(v) // 3]


def org_bands(users, rates: dict) -> dict:
    """Tercile cut points for the org, for the metrics every row can supply.

    Only ratios computed identically for everyone are eligible, and only the two
    cut points leave this function -- no individual's figures reach the report.
    The three local-log metrics (context per turn, long-session share, cache
    misses) have no counterpart here because nobody else's logs are on this
    machine, which is exactly why they are left unrated.
    """
    reuse, out_share = [], []
    for u in users or []:
        cwt, crt = u.get("cacheWriteTokens") or 0, u.get("cacheReadTokens") or 0
        if cwt > 0 and crt > 0:
            reuse.append(crt / cwt)
        proxy = {t: 0.0 for t in FIELDS}
        for m, td in (u.get("modelDetails") or {}).items():
            r = rate_for(m, rates)
            if not r:
                continue
            for t, key in (("in", "inputTokens"), ("cache_read", "cacheReadTokens"),
                           ("cache_write", "cacheWriteTokens"), ("out", "outputTokens")):
                proxy[t] += (td.get(key) or 0) * r[t]
        tot = sum(proxy.values())
        if tot > 0:
            out_share.append(proxy["out"] / tot * 100)
    return {k: v for k, v in (("reuse", terciles(reuse)),
                              ("out_share", terciles(out_share))) if v}


def band_note(name: str, cuts, unit: str, n: int) -> str:
    return (f"{name} 판정은 조직 {n}명의 실제 분포를 셋으로 나눈 값을 씁니다 &mdash; "
            f"{cuts[1]:,.1f}{unit} 이상이 상위 3분의 1(양호), "
            f"{cuts[0]:,.1f}{unit} 미만이 하위 3분의 1(점검)입니다.")


def efficiency(cap: dict, total_cost: float, org: dict, stats: dict,
               models_M: dict, rates: dict, type_rows=(), bands=None, prev=None):
    """(group, label, value, meaning) rows for the 효율 지표 table.

    Every `meaning` is a full sentence: what the number measures, how to read it,
    and where it misleads. A metric whose input is missing is skipped rather than
    printed as a zero, so a --csv-only run simply shows fewer rows.
    """
    cap = cap or {}
    rows = []
    cr = sum(v["cache_read"] for v in models_M.values())
    cw = sum(v["cache_write"] for v in models_M.values())
    out = sum(v["out"] for v in models_M.values())
    share = {n: s for n, _, _, s in type_rows}

    # "얼마나 크게" 들고 다니는지와 "얼마나 오래" 들고 다니는지는 짝을 이루는 질문이라
    # 나란히 둔다. 둘 중 하나만 커도 비용은 오르고, 손대는 방법이 서로 다르다.
    bands, n, prev = bands or {}, org.get("users") or 0, prev or {}
    NO_BANDS = ("판정은 조직 전체의 분포와 견주는데, 이번 실행에서는 그 값을 받지 못했습니다. "
                "<code>--fetch</code>로 돌리면 채워집니다.")

    def vs_last(now, before, unit, lower_is_better=True):
        """(판정, 값에 붙일 지난달 표시, 근거 문장).

        지난달 수치를 값 칸에 같이 보여준다 -- 판정만 있으면 무엇과 견줬는지 알 수 없다.
        """
        v = rate_trend(now, before, lower_is_better)
        if not v:
            return "", "", ("남과 견줄 기준이 없어 지난달과 비교하는 값입니다. "
                            "이번이 첫 달이면 비교할 대상이 없어 판정을 비워둡니다.")
        pct = (now - before) / before * 100
        arrow = "&#9650;" if pct > 0 else "&#9660;"
        sub = (f'<span class="sub">지난달 {before:,.0f}{unit} {arrow}'
               f'{abs(pct):,.0f}%</span>')
        return v, sub, (f"지난달 {before:,.0f}{unit}과 견준 판정입니다. 남의 세션 로그가 이 "
                        "컴퓨터에 없으니 남과 비교할 수 없고, 공개된 기준선도 없습니다. "
                        "본인이 직접 움직일 수 있는 값이라 자기 추세를 잣대로 삼았습니다. "
                        "값이 늘었다고 무조건 나쁜 것은 아니니, 그 달에 무슨 일을 했는지와 "
                        "같이 보세요.")

    if stats:
        v, sub, why = vs_last(stats["ctx_per_turn"] / 1000,
                              (prev.get("ctx_per_turn") or 0) / 1000, "k")
        rows.append((CTX, v, "턴당 평균 컨텍스트", f"{stats['ctx_per_turn']/1000:,.0f}k{sub}",
                     "한 번 답할 때마다 다시 읽는 문맥의 평균 크기입니다. "
                     f"세션 {stats['n']}개에서 {stats['turns']:,}턴을 주고받았고, 가장 컸을 때는 "
                     f"{stats['ctx_max']/1000:,.0f}k까지 갔습니다. "
                     "비용은 문맥 크기에 턴 수를 곱한 만큼 늘어납니다. 턴을 아끼기보다 이 값을 줄이는 "
                     f"쪽이 효과가 큽니다. 줄이는 방법은 아래 플레이북 1&middot;2번에 있습니다. {why}"))
    if cw:
        v = cr / cw
        note = (band_note("이 줄의", bands["reuse"], "배", n) if bands.get("reuse")
                else NO_BANDS)
        rows.append((CTX, rate_high(v, bands["reuse"]) if bands.get("reuse") else "",
                     "컨텍스트 재사용 배수", f"{v:,.1f}배",
                     f"한 번 올린 문맥을 평균 {v:,.1f}번 다시 읽었습니다. 한 번만 다시 읽어도 캐시는 "
                     "이득이니, 이 값이 크면 캐시가 제 역할을 하고 있다는 뜻입니다. "
                     "같은 문맥을 그만큼 오래 들고 다녔다는 뜻도 됩니다. 위 '턴당 평균 컨텍스트'와 "
                     f"함께 보세요. 둘이 같이 크면 세션을 더 자주 끊을 여지가 있습니다. {note}"))
    if stats:
        v, sub, why = vs_last(stats["long_share"] * 100,
                              (prev.get("long_share") or 0) * 100, "%")
        if stats["long_n"]:
            head = (f"50턴을 넘긴 세션 {stats['long_n']}개가 문맥 비용의 "
                    f"{stats['long_share']*100:.0f}%를 씁니다. 한 세션에서 여러 단계를 "
                    "이어가면 앞 단계 대화가 그 뒤 모든 턴에 다시 청구됩니다. "
                    "작업이 바뀔 때 세션을 끊는 것이 가장 효과가 큽니다.")
        else:
            head = ("50턴을 넘긴 세션이 없습니다. 세션을 짧게 유지하고 있다는 뜻이라 "
                    "이 항목은 신경 쓰지 않으셔도 됩니다.")
        rows.append((CTX, v, "50턴 이상 세션 비중", f"{stats['long_share']*100:.0f}%{sub}",
                     f"{head} {why}"))
        if stats.get("miss_share"):
            pct = stats["miss_share"] * 100
            rows.append((CTX, GOOD if pct < MISS_FLAG_PCT else CHECK,
                         "캐시 미스로 다시 쓴 몫", f"{pct:.0f}%",
                         f"이미 값을 치른 문맥을 다시 올린 비율입니다. {stats['miss_n']:,}턴이 문맥을 "
                         "처음부터 새로 썼습니다. "
                         f"이 중 {stats['miss_fast_share']*100:.0f}%는 5분도 지나지 않아 생겼으니 "
                         "캐시가 만료된 게 아니라 세션 중에 무언가 바뀐 쪽입니다. "
                         "원인과 대처는 플레이북 7번에 있습니다. "
                         f"판정 기준은 Claude Code가 <code>/usage</code>에서 캐시 미스를 경고로 "
                         f"띄우는 선인 {MISS_FLAG_PCT}%를 그대로 썼습니다."))
    # 캐시가 아껴준 금액은 성능 지표가 아니다 -- 항상 양수이고 재사용 배수를 금액으로
    # 다시 말한 값이라 판정할 대상이 없다. 캐시 경제를 설명하는 용어 사전으로 옮겼다.
    if share.get("Output"):
        note = (band_note("이 줄의", bands["out_share"], "%", n)
                if bands.get("out_share") else NO_BANDS)
        rows.append((CTX, rate_high(share["Output"], bands["out_share"])
                     if bands.get("out_share") else "", "Output 비중",
                     f"{share['Output']:.1f}%",
                     "청구액 가운데 Claude가 답을 쓰는 데 들어간 몫입니다. 나머지는 문맥을 읽고 "
                     "유지하는 데 나갔습니다. 코드를 고치려면 먼저 읽어야 하니 문맥 쪽이 보통 더 "
                     "크게 나옵니다. 달마다 이 비중이 계속 낮아진다면 세션이 길어지고 있다는 "
                     f"신호입니다. {note}"))

    if cap.get("sessions"):
        rows.append((YIELD, "", "$ / 세션", f"${total_cost/cap['sessions']:,.2f}",
                     f"세션 {int(cap['sessions']):,}개를 열어 평균 이만큼 썼습니다. "
                     "총액보다 체감이 쉬워서 세션을 끊을 시점을 가늠할 때 쓰기 좋습니다."))
    if cap.get("calls"):
        rows.append((YIELD, "", "$ / 호출", f"${total_cost/cap['calls']:,.3f}",
                     f"한 번 주고받는 값입니다(총 {int(cap['calls']):,}회). "
                     "문맥이 커지면 이 값도 같이 오릅니다."))
    if cap.get("commit"):
        rows.append((YIELD, "", "$ / 커밋", f"${total_cost/cap['commit']:,.2f}",
                     f"Claude Code가 만든 커밋 {int(cap['commit']):,}건 기준입니다. "
                     "직접 만든 커밋은 여기 들어가지 않습니다."))
    if cap.get("prs"):
        rows.append((YIELD, "", "$ / PR", f"${total_cost/cap['prs']:,.2f}",
                     f"PR {int(cap['prs']):,}건 기준입니다. "
                     "건수가 적으면 한 건이 값을 크게 흔들니 추세로만 보시면 됩니다."))
    lines = (cap.get("lines_added") or 0) + (cap.get("lines_removed") or 0)
    if lines:
        rows.append((YIELD, "", "$ / 1k 라인", f"${total_cost/(lines/1000):,.2f}",
                     f"Claude Code가 코드 1,000줄을 쓰는 데 든 값입니다. 이번 달은 "
                     f"+{int(cap.get('lines_added') or 0):,} / &minus;{int(cap.get('lines_removed') or 0):,}, "
                     f"합쳐서 {int(lines):,}줄입니다. 직접 쓴 코드는 빠집니다. "
                     "설계나 디버깅이 많았던 달은 자연히 커지니 달 간 추세로 보세요."))
    if cap.get("cli_sec"):
        h = cap["cli_sec"] / 3600
        uh = (cap.get("user_sec") or 0) / 3600
        rows.append((YIELD, "", "$ / CLI 활동시간", f"${total_cost/h:,.2f} /h",
                     f"CLI가 켜져 있던 {h:,.1f}시간 기준이고, 그중 직접 입력한 시간은 {uh:,.1f}시간입니다. "
                     "기다린 시간까지 들어가니 시급으로 읽으면 안 됩니다."))
    if org.get("users") and org.get("cost"):
        avg = org["cost"] / org["users"]
        rows.append((YIELD, "", f"{org.get('name') or '조직'} 대비",
                     f"{total_cost/avg:.1f}배 &middot; 조직의 {total_cost/org['cost']*100:.1f}%",
                     f"{org['users']}명의 1인 평균이 ${avg:,.2f}입니다. 조직 합계만 쓰고 "
                     "다른 사람의 개별 값은 이 리포트에 들어오지 않습니다. "
                     "많이 썼다는 게 잘못은 아닙니다. 무엇을 만들었는지와 같이 보세요."))
    sim = shift_sim(models_M, rates, total_cost)
    if sim and sim < total_cost:
        rows.append((YIELD, "", "opus 70% -> sonnet 환산",
                     f"${sim:,.2f} (&minus;{(1-sim/total_cost)*100:.0f}%)",
                     "지금 쓴 토큰을 그대로 sonnet 단가로 바꿔 계산한 값이라 절감의 상한선입니다. "
                     "실제로는 싼 모델이 턴을 더 쓸 수 있고, 4.7 세대 이후 모델은 같은 글에서 "
                     "토큰이 30%쯤 더 나오는 방식을 쓰기 때문에 토큰 수가 그대로 옮겨가지 않습니다."))
    return rows


def render(month, total_cost, proj, day, proj_day, capture, rates, out_path,
           sessions=(), org=None, vers=None, bands=None, prev=None, who="",
           prev_capture=None):
    cwd_unpriced: set = set()
    proj_proxy = {p: bucket_cost(mm, rates, cwd_unpriced) for p, mm in proj.items()}
    proxy_sum = sum(proj_proxy.values()) or 1.0
    scale_local = total_cost / proxy_sum
    proj_billed = {p: c * scale_local for p, c in proj_proxy.items()}
    day_billed = {d: bucket_cost(mm, rates, cwd_unpriced) * scale_local
                  for d, mm in day.items()}

    # model source: CSV if given (authoritative), else local logs (approx)
    if capture and capture.get("models"):
        models_M, badge = capture["models"], '<span class="badge b-auth">AICM 기준</span>'
    else:
        local = defaultdict(lambda: {t: 0.0 for t in FIELDS})
        for mm in proj.values():
            for m, tk in mm.items():
                for t in FIELDS:
                    local[m][t] += tk[t] / 1e6
        models_M, badge = local, '<span class="badge b-approx">로컬 로그 근사</span>'
    model_rows, type_rows, scale_auth, unpriced = breakdown(models_M, rates, total_cost)
    unpriced |= cwd_unpriced

    def short(p):
        real = unmangle(p)
        if real:
            return os.path.basename(real) or real
        # fall back to the whole path minus the home prefix, NOT the last "-"
        # segment -- that used to turn `alpha-agent-v3` into `v3`
        return re.sub(r"^-home-[^-]+-", "", p) or p

    def project_detail(p: str) -> str:
        """This project's own day-by-day cost + ITS OWN git log (not cwd's)."""
        pd = proj_day.get(p) or {}
        if not pd:
            return ""
        real = unmangle(p)
        themes_p = git_day_themes(month, real) if real else {}
        rows = "".join(
            f'<tr><td class="name">{d}</td><td class="theme">{esc(themes_p.get(d, ""))}</td>'
            f'<td class="num">${bucket_cost(mm, rates, cwd_unpriced) * scale_local:,.2f}</td></tr>'
            for d, mm in sorted(pd.items()))
        return (f'<table class="subtable"><thead><tr><th>날짜</th>'
                f'<th>작업 테마 (이 프로젝트 자신의 git log)</th><th class="num">비용</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>')

    maxp = max(proj_billed.values(), default=1) or 1
    proj_rows = "".join(
        f'<details class="projrow"><summary><span class="name">{esc(short(p))}</span>'
        f'<span class="num">${c:,.2f}</span><span class="pct">{c/total_cost*100:.1f}%</span>'
        f'<span class="barcell">{bar(c/maxp*100,"#4f7cff")}</span></summary>{project_detail(p)}</details>'
        for p, c in sorted(proj_billed.items(), key=lambda kv: -kv[1]))
    day_chart = day_chart_svg(day_billed, refs=(
        (BENCH["day_avg"], f'공식 평균 ${BENCH["day_avg"]}/일'),
        (BENCH["day_p90"], f'사용자 90%가 이 아래 ${BENCH["day_p90"]}/일'),
    ))
    model_html = "".join(
        f'<tr><td class="name"><span class="tag">{esc(m)}</span></td><td class="mono">{tok:.2f}M</td>'
        f'<td class="num">${c:,.2f}</td><td class="pct">{s:.1f}%</td>'
        f'<td class="barcell">{bar(s,"#a06bff")}</td></tr>' for m, tok, c, s in model_rows)
    type_html = "".join(
        f'<tr><td class="name">{esc(n)}</td><td class="mono">{tok:.2f}M</td>'
        f'<td class="num">${c:,.2f}</td><td class="pct">{s:.1f}%</td>'
        f'<td class="barcell">{bar(s,"#22a06b")}</td></tr>' for n, tok, c, s in type_rows)

    warn = ""
    if unpriced:
        warn = (f'<p class="note" style="border-left-color:#e0725f"><b>단가 미등록 모델:</b> '
                f'{esc(", ".join(sorted(unpriced)))} &mdash; <code>rates.json</code>에 추가하세요. '
                f'해당 모델은 비용 배분에서 제외됨(임의 추정 안 함).</p>')

    stats = session_stats(list(sessions))
    eff = efficiency(capture, total_cost, org or {}, stats, models_M, rates,
                     type_rows, bands, prev)
    eff_html = ""
    # One table per group with its own heading, rather than a band row inside a
    # single table: the two groups answer different questions, and a shared header
    # row made them read as one list with a divider.
    # `meaning` is emitted as markup (it carries <b>/<code>) -- every string is
    # authored above and interpolates only numbers, never API or log text. Label
    # and value stay escaped.
    for g in (CTX, YIELD):
        grp = [r for r in eff if r[0] == g]
        if not grp:
            continue
        # The 판정 column only appears when the group has something to judge, so
        # the 산출 대비 비용 table stays three columns instead of carrying a row
        # of dashes for metrics nobody has published a threshold for.
        rated = any(r[1] for r in grp)
        body = ""
        for _, rt, l, v, n in grp:
            cell = ""
            if rated:
                pill = (f'<span class="pill p-{RATING_CLS[rt]}">{esc(rt)}</span>' if rt
                        else '<span class="pill p-none" title="비교 기준이 없어 판정하지 않음">&mdash;</span>')
                cell = f'<td class="verdict">{pill}</td>'
            body += (f'<tr>{cell}<td class="name">{esc(l)}</td>'
                     f'<td class="num">{v}</td><td class="theme">{n}</td></tr>')
        head = '<th class="verdict">판정</th>' if rated else ""
        eff_html += (
            f'<h3 class="grp">{esc(g)}'
            f'<span class="ghint">{esc(GROUP_HINT.get(g, ""))}</span></h3>'
            f'<table class="eff"><thead><tr>{head}<th>지표</th><th class="num">값</th>'
            f'<th>의미 &middot; 읽는 법</th></tr></thead><tbody>{body}</tbody></table>')
    if eff_html:
        eff_html = "<h2>효율 지표</h2>" + eff_html

    # --- insights: 진단(수치) -> 메커니즘(왜) -> 처방(무엇을 얼마나) -------------
    ins = []   # (kind, eyebrow, [(label, text), ...]) -- kind picks the card colour

    def add(kind, eyebrow, situation, reason="", todo=""):
        blocks = [(l, t) for l, t in (("상황", situation), ("이유", reason),
                                      ("해볼 것", todo)) if t]
        ins.append((kind, eyebrow, blocks))

    share = {n: p for n, _, _, p in type_rows}   # "Cache Read" -> % of bill
    cr_M = sum(v["cache_read"] for v in models_M.values())
    out_M = sum(v["out"] for v in models_M.values())
    if share.get("Cache Read") and out_M:
        ctx = f" 턴당 평균 {stats['ctx_per_turn']/1000:,.0f}k를 다시 읽었습니다." if stats else ""
        add("ctx", "컨텍스트",
            f"이번 달 비용의 {share['Cache Read']+share.get('Cache Write',0):.0f}%가 문맥을 읽고 "
            f"유지하는 데 나갔습니다. Cache Read {share['Cache Read']:.0f}%에 Cache Write "
            f"{share.get('Cache Write',0):.0f}%, 정작 답을 쓴 Output은 "
            f"{share.get('Output',0):.0f}%입니다.{ctx}",
            "Cache Write는 문맥에 처음 넣을 때 한 번 냅니다. Cache Read는 그 뒤로 턴마다 계속 나갑니다. "
            "<b>문맥을 몇 턴이나 끌고 다녔는지가 금액을 정합니다.</b>",
            "구현 중에 에이전트가 설계 문서를 다시 읽는다면 대체로 세션 구조 문제입니다. 파일을 "
            "어떻게 읽을지 일일이 지시할 일은 아닙니다. 직접 손댈 수 있는 것은 세 가지입니다. "
            "<b>참조 문서를 짧게 유지하면</b> 매 턴 따라오는 크기가 그만큼 줄어듭니다. "
            "<b>설계와 구현은 세션을 나누세요.</b> 구현 세션이 설계 대화 전체를 끌고 가지 "
            "않습니다. <b>넓게 훑어야 할 때는 서브에이전트에 맡기라고 시키세요.</b> "
            "파일 내용은 그쪽 문맥에서 끝나고 요약만 돌아옵니다.")
    if stats.get("miss_share", 0) >= 0.15:
        lost = stats["miss_share"] * (share.get("Cache Write", 0) / 100) * total_cost
        todo = (f"툴 정의가 바뀌면 캐시 전체가 무효화됩니다. {cite(DOC_CACHE)} 세션 중간에 MCP 서버를 "
                "붙이거나 떼는 것이 여기 해당합니다. 플러그인&middot;스킬을 켜고 끄거나 thinking&middot;모델을 "
                "바꾸는 것도 마찬가지입니다. 이 현상을 일으키던 버그가 여러 번 고쳐졌으니 "
                "Claude Code 버전도 확인해보세요. 버전별 정리는 플레이북 7번에 있습니다.")
        if stats["miss_fast_share"] < 0.7 and not caching_1h_enabled():
            # 남는 몫은 응답 사이 공백이 기본 TTL(5분)보다 길어서 만료된 쪽일 수 있다 -- 이때만
            # 1시간 캐시가 도움이 되므로, 용어 사전이 아니라 실제로 미스가 나는 여기서 알려준다.
            todo += (' 나머지는 응답 사이 공백이 캐시 기본 유지 시간(5분)보다 길어서 만료된 쪽일 '
                     '수 있습니다. 그렇다면 <code>settings.json</code>의 <code>env</code>에 '
                     '<code>"ENABLE_PROMPT_CACHING_1H": "1"</code>을 추가해 1시간짜리 캐시로 늘릴 '
                     '수 있습니다 &mdash; write 단가는 오르지만(1.25배&rarr;2배) 만료로 놓치는 read가 줄어듭니다.')
        add("waste", "낭비",
            f"cache_write의 {stats['miss_share']*100:.0f}%, 금액으로 약 ${lost:,.2f}가 이미 값을 "
            f"치른 문맥을 다시 올리는 데 쓰였습니다. {stats['miss_n']:,}턴이 문맥을 처음부터 "
            "새로 썼습니다.",
            f"<code>cache_read = 0</code>은 <code>tools &rarr; system &rarr; messages</code> 계층에서 맨 위까지 "
            f"캐시가 깨졌다는 뜻입니다. 원인은 캐시 만료 아니면 툴 정의 변경입니다. 이 중 "
            f"{stats['miss_fast_share']*100:.0f}%가 5분도 안 돼서 생겼으니 만료 쪽은 아닙니다.",
            todo)
    if stats:
        add("hygiene", "세션 위생",
            f"50턴을 넘긴 세션 {stats['long_n']}개가 문맥 비용의 {stats['long_share']*100:.0f}%를 "
            f"씁니다. 상위 {stats['top_n']}개 세션만 봐도 {stats['top_share']*100:.0f}%이고 "
            f"가장 컸던 문맥은 {stats['ctx_max']/1000:,.0f}k였습니다.",
            "한 세션에서 설계부터 구현과 리뷰까지 이어가면 단계가 끝난 뒤에도 그 대화가 문맥에 남아 "
            "이후 모든 턴에 다시 청구됩니다.",
            "끊는 기준은 공식 문서가 <i>\"when switching to unrelated work\"</i>, 무관한 작업으로 "
            "넘어갈 때라고 적어뒀습니다. 끊기 전에 <code>/rename</code>을 해두면 나중에 "
            "<code>/resume</code>으로 찾아올 수 있습니다. <code>/compact</code>를 대신 쓰는 건 "
            "별로입니다. 압축하는 것 자체가 큰 요청이라서요. 이어갈 일이 없는 세션은 "
            "<code>/clear</code>가 공짜입니다. 탐색을 서브에이전트에 맡기면 파일 내용은 그쪽 "
            f"문맥에서 끝납니다. {cite(DOC_COSTS)}")
    if model_rows:
        tm = model_rows[0]
        sim = shift_sim(models_M, rates, total_cost)
        cut = (f" 지금 쓴 opus 토큰의 70%를 sonnet으로 옮기면 ${sim:,.2f}, "
               f"{(1-sim/total_cost)*100:.0f}%가 줄어듭니다."
               if sim and sim < total_cost else "")
        rr = family_rate("opus", rates), family_rate("sonnet", rates)
        ratio = (f" opus의 cache_read 단가가 sonnet의 {rr[0]['cache_read']/rr[1]['cache_read']:,.1f}배니 "
                 f"문맥이 큰 단계일수록 모델을 내리는 효과가 큽니다." if all(rr) else "")
        add("model", "모델",
            f"{esc(tm[0])}이 비용의 {tm[3]:.0f}%를 씁니다.",
            f"같은 토큰이라도 어느 모델에서 쓰였는지에 따라 금액이 크게 달라집니다.{ratio}",
            "공식 문서는 <i>\"Sonnet handles most coding tasks well and costs less than Opus\"</i>라며 "
            "상위 모델은 아키텍처 판단이나 여러 단계 추론에 남겨두라고 적습니다. 대화 중간에 손으로 "
            "바꾸면 지금까지의 대화를 캐시 없이 처음부터 다시 읽으니 피하세요. 세션 시작 때 정해두는 "
            "편이 낫습니다. 단계마다 다르게 쓰려면 <code>/model opusplan</code>이 있습니다. "
            "plan mode에서 opus로 설계하고 실행으로 넘어가면 sonnet으로 알아서 바뀌니 캐시가 "
            f"깨지지 않습니다.{cut} {cite(DOC_COSTS)}")
    if proj_billed:
        tp = max(proj_billed.items(), key=lambda kv: kv[1])
        add("proj", "프로젝트",
            f"비용이 {esc(short(tp[0]))} 한 곳에 몰려 있습니다. ${tp[1]:,.2f}로 전체의 "
            f"{tp[1]/total_cost*100:.0f}%입니다.",
            "",
            "위의 것들을 전 프로젝트에 한꺼번에 적용하기보다 여기서만 먼저 시험해보세요. 효과가 가장 "
            "빨리 드러납니다. 프로젝트별 금액은 로컬 로그의 비율로 나눈 근사값입니다.")
    if scale_auth < 0.9 or scale_auth > 1.1:
        add("note", "참고",
            f"실청구액이 <code>rates.json</code> 정가 프록시의 {scale_auth*100:.0f}%로 나옵니다.",
            "1배에서 크게 벗어나면 계약 단가가 정가와 다르거나, 단가표가 실제 사용 모델의 세대와 "
            "맞지 않는 것입니다.",
            "후자라면 모델별 배분과 모델 이전 추정이 함께 틀어지니 <code>rates.json</code>을 먼저 "
            "갱신하세요.")
    else:
        add("note", "참고",
            f"실청구액이 정가 프록시와 {scale_auth*100:.0f}%로 맞습니다.",
            "대시보드가 공식 정가로 비용을 계산한다는 뜻이고, 따로 깎여 있는 단가는 없습니다.",
            "절감은 단가가 아니라 위에 적은 사용 방식에서 나옵니다. 턴당 문맥, 캐시 미스, 모델 선택입니다.")
    # 손댈 순서대로 정렬한다. 코드가 만든 순서가 아니라 읽는 사람이 먼저 볼 것 순서다.
    # 색은 이 리포트가 이미 그 축에 쓰고 있는 색을 그대로 재사용한다 -- 파랑은 문맥,
    # 보라는 모델, 초록은 프로젝트, 주황은 세션, 빨강은 낭비.
    order = ("ctx", "waste", "hygiene", "model", "proj", "note")
    ins.sort(key=lambda t: order.index(t[0]) if t[0] in order else len(order))
    insights = "".join(
        f'<div class="ins ins-{k}"><div class="eyebrow">{esc(eb)}</div>'
        + "".join(f'<dl class="blk"><dt>{esc(l)}</dt><dd>{t}</dd></dl>' for l, t in blocks)
        + '</div>' for k, eb, blocks in ins)

    cards = (f'<div class="card"><div class="k">실 청구액</div><div class="v">${total_cost:,.2f}</div>'
             f'{delta_html(total_cost, (prev_capture or {}).get("total_cost"))}</div>')
    if capture:
        for k, lab in (("calls", "총 호출"), ("sessions", "세션"), ("commit", "커밋")):
            if capture.get(k):
                cards += (f'<div class="card"><div class="k">{lab}</div>'
                          f'<div class="v">{int(capture[k]):,}</div>'
                          f'{delta_html(capture[k], (prev_capture or {}).get(k))}</div>')

    def summary_html() -> str:
        """3-4 sentence lead, before any table: headline number and its trend,
        then where the cost concentrates. Every fact is already computed above
        -- this only orders and phrases them. No 판정, same reason the 산출
        대비 비용 rows carry none: there's no published basis for whether more
        cost, calls, sessions, or commits is "good".
        """
        lines = []
        pct, dirn = _pct_change(total_cost, (prev_capture or {}).get("total_cost"))
        if dirn is None:
            lines.append(f"이번 달 실청구액은 ${total_cost:,.2f}입니다.")
        elif dirn == "flat":
            lines.append(f"이번 달 실청구액은 ${total_cost:,.2f}로 전월과 비슷합니다.")
        else:
            word = "늘었습니다" if dirn == "up" else "줄었습니다"
            lines.append(f"이번 달 실청구액은 ${total_cost:,.2f}로 전월보다 "
                         f"{abs(pct):.0f}% {word}.")

        if capture and prev_capture:
            cands = []
            for k, lab in (("calls", "호출"), ("sessions", "세션"), ("commit", "커밋")):
                if capture.get(k) and prev_capture.get(k):
                    p, d = _pct_change(capture[k], prev_capture[k])
                    if d and d != "flat":
                        cands.append((abs(p), lab, capture[k], p, d))
            if cands:
                _, lab, val, p, d = max(cands)
                word = "늘었습니다" if d == "up" else "줄었습니다"
                lines.append(f"{lab}은 {int(val):,}건으로 전월보다 {abs(p):.0f}% {word}.")

        bits = []
        if model_rows:
            m, _, _, s = model_rows[0]
            bits.append(f"{esc(m)} 모델이 {s:.0f}%")
        if proj_billed:
            p, c = max(proj_billed.items(), key=lambda kv: kv[1])
            bits.append(f"{esc(short(p))} 프로젝트가 {c / total_cost * 100:.0f}%")
        if bits:
            lines.append("비용은 " + ", ".join(bits) + "를 차지합니다.")

        if stats and prev:
            _, d = _pct_change(stats.get("ctx_per_turn", 0), prev.get("ctx_per_turn"))
            if d and d != "flat":
                word = "늘었습니다" if d == "up" else "줄었습니다"
                lines.append(f"세션당 평균 컨텍스트는 지난달보다 {word}.")

        return f'<p class="summary">{" ".join(lines)}</p>'

    doc = HTML_TMPL.format(
        month=esc(month), total_cost=total_cost, cards=cards, badge=badge,
        who=(f'{esc(who)} &middot; ' if who else ''), summary=summary_html(),
        model_rows=model_html, type_rows=type_html, proj_rows=proj_rows,
        day_chart=day_chart, insights=insights, warn=warn, eff=eff_html,
        glossary=glossary_html(type_rows, models_M, rates, total_cost),
        playbook=playbook_html(stats, vers or {}), docs_asof=esc(DOCS_ASOF),
        bench_avg=BENCH["day_avg"], bench_p90=BENCH["day_p90"],
        bench_lo=BENCH["month_lo"], bench_hi=BENCH["month_hi"],
        scale_local=scale_local, proxy_sum=proxy_sum, scale_auth=scale_auth)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(doc)
    return out_path


# Every recommendation in the report carries its source. These are NOT rendered as
# links: the corp network cannot reach either docs host, and a link that times out
# reads as a broken report. Inline citations show the page title only; the full
# URLs are listed once, at the bottom of the playbook, for anyone checking from an
# external machine. Shipping the docs themselves is not an option -- the two
# llms-full.txt dumps are ~41 MB of third-party content.
DOC_CACHE = ("Prompt caching", "platform.claude.com/docs/en/build-with-claude/prompt-caching")
DOC_CTXWIN = ("Context windows", "platform.claude.com/docs/en/build-with-claude/context-windows")
DOC_PRICING = ("Pricing", "platform.claude.com/docs/en/about-claude/pricing")
DOC_COSTS = ("Manage costs effectively", "code.claude.com/docs/en/costs")
DOC_MEMORY = ("Memory", "code.claude.com/docs/en/memory")
DOC_SUBAGENT = ("Subagents", "code.claude.com/docs/en/sub-agents")
DOC_MODEL = ("Model configuration", "code.claude.com/docs/en/model-config")
DOC_MCP = ("MCP", "code.claude.com/docs/en/mcp")
DOC_CMDS = ("Slash commands", "code.claude.com/docs/en/commands")
DOC_BEDROCK = ("Amazon Bedrock", "code.claude.com/docs/en/amazon-bedrock")
DOCS_ALL = (DOC_COSTS, DOC_CMDS, DOC_MEMORY, DOC_SUBAGENT, DOC_MODEL, DOC_MCP,
            DOC_BEDROCK, DOC_CACHE, DOC_CTXWIN, DOC_PRICING)

# Date the quoted wording was last read out of the official docs. Hardcoded ON
# PURPOSE -- never today(), which would claim freshness the text hasn't earned.
# Bump it only after actually re-reading the pages (see SKILL.md).
DOCS_ASOF = "2026-08-21"


def cite(doc, label: str = "") -> str:
    """Inline attribution: page title as plain text, never a hyperlink."""
    return f'<span class="cite">(공식 문서 &ldquo;{esc(label or doc[0])}&rdquo;)</span>'


def sources_html() -> str:
    items = "".join(f'<li>{esc(t)} &mdash; <code>{esc(u)}</code></li>' for t, u in DOCS_ALL)
    return ('<p class="note"><b>출처 &middot; 인용 기준 시점 '
            f'<code>{esc(DOCS_ASOF)}</code>.</b> 위 인용은 모두 Anthropic 공식 문서에서 그대로 '
            '옮긴 것이며, <b>그 날짜에 읽은 문안</b>이다. 공식 문서는 계속 갱신되므로 시간이 지나면 '
            '표현이나 권고가 달라질 수 있다 &mdash; 이 날짜가 오래됐다고 느껴지면 원문을 다시 확인할 것. '
            '<b>사내망에서는 두 도메인 모두 접속되지 않으니</b> 확인은 외부망에서 아래 주소로 '
            f'(제목으로 검색해도 찾을 수 있다).</p><ul class="src">{items}</ul>')


TOK_COLOR = {"base": "#333b4d", "in": "#93a0b8", "cache_write": "#d98b2b",
             "cache_read": "#4f7cff", "out": "#22a06b"}


def context_diagram() -> str:
    """Three turns of one session: request bar, response, and what gets cached.

    A turn's own Output is drawn separate from its request bar -- it is NOT
    cache-written the moment it's generated. Only on the NEXT turn, once that
    Output is resent as part of the new request, does it (together with the
    new turn's Input) become the Cache Write delta. Cache Read always covers
    exactly the *previous* turn's full request bar, since that whole prefix is
    what got written to cache last time.

    So per turn i (i>1): CR span == turn (i-1)'s full bar, CW span == the last
    two segments (Output i-1 + Input i). Turn 1 has no CR; its whole (short)
    bar is CW. `test_driver.py` asserts these spans, so don't hand-tune widths.

    The right-hand "Cached Prefix" panel is drawn as its own bordered/tinted
    track (like the page's other capacity bars) so it reads as storage
    managed separately from the request/response flow on the left, not a
    continuation of it. Each turn fills more of that fixed-width track from
    the left, its blocks labelled the same as the left side (Base/Input
    1/Output 1/...) -- never that turn's own Output, since Output hasn't been
    resent yet and so isn't in the cache. No line connects Output to it.

    A concept sketch, not this month's figures.
    """
    BASE_W, IN_W, OUT_W, GAP, BAR_H = 24, 40, 50, 4, 18
    x0, y0, row_h = 50, 38, 64
    cache_x0, CAP_W, PAD = 424, 330, 12

    def bracket(b0, b1, by, color):
        return (f'<path d="M{b0},{by} L{b0},{by + 4} L{b1},{by + 4} L{b1},{by}" '
                f'fill="none" stroke="{color}" stroke-width="1.2"/>')

    def bracket_label(b0, b1, by, color, text):
        return (f'<text x="{(b0 + b1) / 2:.0f}" y="{by + 13}" class="dseg2" '
                f'text-anchor="middle" fill="{color}">{text}</text>')

    def block(x, y, w, label, kind, stroke=""):
        # Base is dark, so it needs light text and its own outline to read as
        # a distinct block instead of blending into Input's similar gray-blue.
        if kind == "base":
            cls, stroke = "dsegl", (stroke or ' stroke="#5b6784" stroke-width="1"')
        else:
            cls = "dseg"
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{BAR_H}" rx="3" '
                f'fill="{TOK_COLOR[kind]}" opacity=".95"{stroke}/>'
                f'<text x="{x + w / 2:.0f}" y="{y + BAR_H - 6}" class="{cls}" '
                f'text-anchor="middle">{label}</text>')

    panel_top, panel_bot = y0 - 30, y0 + 2 * row_h + BAR_H + 6
    body = (f'<rect x="{cache_x0 - PAD}" y="{panel_top}" width="{CAP_W + 2 * PAD}" '
            f'height="{panel_bot - panel_top}" rx="10" fill="#11172a" stroke="#26314a"/>'
            f'<text x="{cache_x0}" y="{panel_top + 14}" class="dhdr">Cached Prefix</text>'
            f'<text x="{cache_x0}" y="{panel_top + 25}" class="dlab">다음 요청에서 재사용되는 문맥</text>')

    segs = []
    for i in range(1, 4):
        y = y0 + (i - 1) * row_h
        body += f'<text x="0" y="{y + BAR_H - 5}" class="dlab">턴 {i}</text>'
        if i == 1:
            segs = [("Base", BASE_W, "base"), (f"Input {i}", IN_W, "in")]
        else:               # 직전 Output + 이번 Input이 이번 턴의 새 CW 영역
            segs = segs + [(f"Output {i - 1}", OUT_W, "out"), (f"Input {i}", IN_W, "in")]
        cr_n = len(segs) - 2 if i > 1 else 0        # 나머지 전부가 CR 영역

        seg_x, x = [], x0
        for label, w, kind in segs:
            seg_x.append((label, x, w, kind))
            x += w + GAP
        req_end = x - GAP

        for label, sx, w, kind in seg_x:
            body += block(sx, y, w, label, kind)

        by = y + BAR_H + 4
        if cr_n:
            b0, (_, sx1, w1, _) = seg_x[0][1], seg_x[cr_n - 1]
            b1 = sx1 + w1
            body += bracket(b0, b1, by, TOK_COLOR["cache_read"])
            if i == 2:      # 첫 등장에만 이름을 달아 이후 턴에서는 겹치지 않게
                body += bracket_label(b0, b1, by, TOK_COLOR["cache_read"], "Cache Read")
        b0 = seg_x[cr_n][1]
        b1 = seg_x[-1][1] + seg_x[-1][2]
        body += bracket(b0, b1, by, TOK_COLOR["cache_write"])
        if i == 1:
            body += bracket_label(b0, b1, by, TOK_COLOR["cache_write"], "Cache Write")

        ax = req_end + 8       # Output은 요청 막대와 분리해 그린다 -- 아직 캐시 밖이다
        body += f'<text x="{ax}" y="{y + BAR_H - 5}" class="dlab">&rarr;</text>'
        ox = ax + 16
        body += block(ox, y, OUT_W, f"Output {i}", "out")

        # Cache track: a fixed-width slot (like a context-window budget) with
        # the used prefix filled from the left; the rest stays empty track.
        body += (f'<rect x="{cache_x0}" y="{y}" width="{CAP_W}" height="{BAR_H}" '
                 f'rx="3" fill="#0c1220"/>')
        cw_ids = set(id(s) for s in segs[-2:])
        cx = cache_x0
        for seg in segs:
            label, w, kind = seg
            stroke = (f' stroke="{TOK_COLOR["cache_write"]}" stroke-width="1.3"'
                      if id(seg) in cw_ids else '')
            body += block(cx, y, w, label, kind, stroke)
            cx += w + GAP
        if i == 2:
            body += (f'<text x="{cache_x0}" y="{y + BAR_H + 17}" class="dlab">'
                     f'굵은 테두리 = 이번 턴에 새로 추가(CW)</text>')

    return (f'<svg viewBox="0 0 800 {panel_bot + 10}" class="ctxdiag" role="img" '
            f'aria-label="턴마다 이전 문맥은 Cache Read로 재사용하고, 직전 Output과 이번 Input만 '
            f'Cache Write로 저장하는 모양. 오른쪽 패널은 그 결과로 쌓이는 Cached Prefix">{body}</svg>')


def glossary_html(type_rows, models_M: dict, rates: dict, total_cost: float) -> str:
    """Folded explainer for the four token types -- VOC asked for exactly this.

    The numbers are pulled from this report rather than hardcoded, so the worked
    example always matches the tables above it.
    """
    share = {n: (tok, c, s) for n, tok, c, s in type_rows}
    rep = next((rate_for(m, rates) for m, _ in
                sorted(models_M.items(), key=lambda kv: -sum(kv[1].values()))
                if rate_for(m, rates)), None)
    ratio = (rep["cache_write"] / rep["cache_read"]) if rep and rep["cache_read"] else 12.5
    rows = "".join(
        f'<tr><td class="name"><span class="swatch" style="background:{TOK_COLOR[k]}{border}"></span>'
        f'{esc(n)}</td><td class="theme">{w}</td>'
        f'<td class="num">{p}</td></tr>'
        for k, n, w, p, border in (
            ("base", "Base Context", "System prompt&middot;도구(MCP 서버 포함) 정의&middot;CLAUDE.md처럼 매 턴 "
                                      "다시 보내는 바탕 문맥입니다. 그 자체로 단가가 있는 게 아니라, "
                                      "그때그때 Input/Cache Write/Cache Read 중 하나로 과금됩니다.",
             "&mdash;", ";border:1px solid #5b6784"),
            ("in", "Input", "Cache Write나 Cache Read로 처리되지 않은 <b>일반 입력 토큰</b>입니다. "
                            "새 내용이라고 해서 항상 Input으로 과금되는 것은 아닙니다.", "1배 (기준)", ""),
            ("cache_write", "Cache Write", "이번 요청에서 새로 처리되어 <b>cached prefix에 저장되는</b> "
                                           "입력 토큰입니다. 이후 같은 prefix가 유지되면 Cache Read로 "
                                           "재사용됩니다.",
             "<div>1.25배 (5분)</div><div>2배 (1시간)</div>", ""),
            ("cache_read", "Cache Read", "이전 요청에서 캐시해 둔 <b>동일한 prefix를 다시 읽은</b> "
                                         "입력 토큰입니다.", "0.1배", ""),
            ("out", "Output", "Claude가 이번 요청에서 <b>새로 생성한</b> 토큰입니다. 이 Output은 "
                              "다음 턴부터 대화 문맥에 포함되어 Cache Write/Read 대상이 될 수 "
                              "있습니다.", "5배", ""),
        ))
    cw = share.get("Cache Write", (0, 0, 0))
    crd = share.get("Cache Read", (0, 0, 0))
    # 캐시 덕분에 아낀 금액. 성능 지표가 아니라 캐시 구조를 실감하게 하는 숫자라
    # 효율 지표 표가 아니라 이 설명 안에 둔다.
    saved = 0.0
    for m, tk in models_M.items():
        r = rate_for(m, rates)
        if r:
            saved += tk["cache_read"] * (r["in"] - r["cache_read"])
    saving = ""
    if saved and total_cost:
        saving = (f'<p><b>캐시가 아껴준 금액은 ${saved:,.2f}입니다.</b> 같은 문맥을 캐시 없이 '
                  f'매 턴 Input 단가로 냈다면 그만큼 더 냈을 텐데, 실제 청구액의 '
                  f'{saved/total_cost:,.1f}배에 해당합니다. 캐시는 이미 최대로 일하고 있으니 '
                  f'남은 절감은 캐시 설정이 아니라 문맥 크기를 줄이는 쪽에서 나옵니다.</p>')
    twist = ""
    if cw[0] and crd[0] and cw[1] and crd[1]:
        twist = (
            f'<p class="note"><b>토큰이 {crd[0]/cw[0]:,.0f}배 많은 Cache Read가 왜 Cache Write보다 '
            f'싼가요?</b> 단가가 다릅니다. 위 표대로 write는 기준의 1.25배, read는 0.1배라 '
            f'<b>write 1토큰이 read {ratio:,.1f}토큰</b>에 해당합니다. 이번 달만 봐도 Cache Write '
            f'{cw[0]:,.1f}M이 ${cw[1]:,.2f}인데 Cache Read {crd[0]:,.1f}M이 ${crd[1]:,.2f}입니다. '
            f'토큰 수가 아니라 단가가 곱해진 결과입니다. {cite(DOC_CACHE)}</p>')
    return (
        '<details class="gloss"><summary>용어 사전 &mdash; Input / Cache Write / Cache Read / Output이 '
        '무슨 뜻인가요? (펼쳐보기)</summary>'
        '<p>위 네 값은 서로 다른 <b>내용</b>의 토큰이라기보다, <b>이번 요청에서 토큰이 어떻게 '
        '처리됐는지에 따른 과금 구분</b>입니다. 같은 대화 내용도 처음 캐시에 들어갈 때는 '
        'Cache Write, 다음 턴에 다시 쓰일 때는 Cache Read로 계산됩니다.</p>'
        f'{context_diagram()}'
        '<p class="dcap"><b>이전 턴까지 동일한 문맥은 Cache Read(파란 밑줄)로 재사용</b>하고, '
        '<b>직전 Output과 이번 Input처럼 새로 늘어난 부분만 Cache Write(주황 밑줄)</b>로 캐시에 '
        '추가됩니다. 이번 Output은 아직 캐시 밖에 있다가, 다음 턴부터 입력 문맥의 일부가 됩니다. '
        '회색 <b>Base</b>는 아래 표에서 설명합니다.</p>'
        '<table class="subtable"><thead><tr><th>종류</th><th>언제 돈을 내나요</th>'
        '<th class="num">단가(Input=1)</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        f'{twist}'
        '<p><b>그래서 큰 파일 하나를 읽는 값은 write 한 번으로 끝나지 않습니다.</b> '
        'write 한 번에, 그 세션에 남은 턴만큼 read가 붙습니다. 정리하면 '
        '<b>비용 &asymp; 문맥 크기 &times; 남은 턴 수</b>입니다.</p>'
        '<p>다만 끝없이 늘지는 않습니다. 문맥이 한계에 가까워지면 자동 압축이 오래된 대화를 '
        '요약해 덜어내기 때문에, 턴당 비용은 오르다가 압축 시점에 한 번 내려갑니다'
        f'{cite(DOC_COSTS)}. 그래서 <b>파일을 언제 읽느냐보다 세션을 얼마나 오래 끌고 가느냐가 '
        '실제로 손댈 수 있는 부분입니다.</b> 읽어야 할 때 읽는 것은 미룰 수 없으니까요.</p>'
        f'{saving}'
        '<p><b>그래도 캐시는 확실히 이득입니다.</b> 공식 문서도 '
        '<i>"caching pays off after one cache read"</i>라고 적습니다. 이는 이 리포트가 다루는 '
        '<b>5분 캐시(write 1.25배)</b> 기준으로, read 한 번만 있어도 write 프리미엄을 상쇄하고 '
        '남습니다. write가 2배인 <b>1시간 캐시</b>는 그보다 조금 더 필요해서, read 1~2회부터 '
        f'이득이 납니다. {cite(DOC_CACHE)}</p>'
        '<p><b>다만 캐시가 문맥을 줄여주지는 않습니다.</b> '
        '<i>"prompt caching changes what you pay for those tokens, not whether they count"</i> &mdash; '
        f'캐시에 들어간 부분도 컨텍스트 창은 그대로 차지합니다. {cite(DOC_CTXWIN)}</p>'
        '</details>')


def playbook_html(stats: dict, vers: dict) -> str:
    """Folded playbook. Every item is a documented recommendation with its source.

    Nothing here is inferred: if the official docs do not say it, it is not in
    this list. The English quotes live in plain string literals rather than
    inside f-string replacement fields, because nesting same-type quotes in a
    replacement field is a syntax error before Python 3.12.
    """
    def item(pre, quote=None, doc=None, post=""):
        mid = '<i>"' + quote + '"</i> ' + cite(doc) + " " if quote else ""
        return "<li>" + pre + mid + post + "</li>"

    def block(title, items):
        return "<h4>" + title + "</h4><ul>" + "".join(items) + "</ul>"

    clear_q = ("Use /clear to start fresh when switching to unrelated work. Stale "
               "context wastes tokens on every subsequent message. Use /rename before "
               "clearing so you can easily find the session later, then /resume to "
               "return to it.")
    compact_q = ("/compact reads the conversation it summarizes, so compacting a large "
                 "context is itself a large request. When you want a fresh start instead "
                 "of continuity, /clear costs nothing")
    spend_q = ("Unexpectedly high spend ... usually traces back to long sessions that "
               "were never cleared or to Opus left as the default model. The "
               "highest-impact habits to share are clearing between unrelated tasks and "
               "matching the model to the job")
    sub_q = ("Running tests, fetching documentation, or processing log files can consume "
             "significant context. Delegate these to subagents so the verbose output "
             "stays in the subagent's context while only a summary returns to your main "
             "conversation.")
    haiku_q = ("For simple subagent tasks, specify model: haiku in your subagent "
               "configuration")
    subbad_q = ("Running many subagents that each return detailed results can consume "
                "significant context.")
    team_q = ("Agent teams use approximately 7x more tokens than standard sessions when "
              "teammates run in plan mode")
    md_q = "Aim to keep CLAUDE.md under 200 lines by including only essentials."
    hook_q = ("Instead of Claude reading a 10,000-line log file to find errors, a hook "
              "can grep for ERROR and return only matching lines, reducing context from "
              "tens of thousands of tokens to hundreds.")
    mcp_defer_q = ("MCP tool definitions are deferred by default, so only tool names "
                   "enter context until Claude uses a specific tool.")
    mcp_cli_q = ("Tools like gh, aws, gcloud, and sentry-cli are still more "
                 "context-efficient than MCP servers because they don't add any per-tool "
                 "listing.")
    think_q = ("Thinking tokens are billed as output tokens, and the default budget can "
               "be tens of thousands of tokens per request depending on the model. For "
               "simpler tasks where deep reasoning isn't needed, you can reduce costs by "
               "lowering the effort level with /effort or in /model, disabling thinking "
               "in /config, or ... setting the MAX_THINKING_TOKENS environment variable, "
               "for example MAX_THINKING_TOKENS=8000.")
    sonnet_q = ("Sonnet handles most coding tasks well and costs less than Opus. Reserve "
                "Opus for complex architectural decisions or multi-step reasoning.")
    switch_q = ("the picker asks for confirmation when the conversation has prior output, "
                "since the next response re-reads the full history without cached context")
    opusplan_q = ("uses opus during plan mode, then switches to sonnet for execution")
    bedrock_q = ("a deployment that doesn't pin a primary model is billed at the Opus rate")
    plan_q = ("Claude explores the codebase and proposes an approach for your approval, "
              "preventing expensive re-work when the initial direction is wrong.")
    vague_q = ("Vague requests like 'improve this codebase' trigger broad scanning. "
               "Specific requests like 'add input validation to the login function in "
               "auth.ts' let Claude work efficiently with minimal file reads.")
    rot_q = ("As token count grows, accuracy and recall degrade, a phenomenon known as "
             "context rot. This makes curating what's in context just as important as "
             "how much space is available.")
    tool_q = ("Modifying tool definitions (names, descriptions, parameters) invalidates "
              "the entire cache")
    usage_q = ("computes the dollar figure locally from token counts priced at standard "
               "list rates, so it doesn't reflect promotional pricing or contracted "
               "discounts and may differ from your actual bill")

    out = [
        '<details class="play"><summary>절감 플레이북 &mdash; 공식 문서에 실제로 있는 권고만 '
        '(펼쳐보기)</summary>',
        '<p class="note">아래는 전부 Anthropic 공식 문서의 권고이고 각 항목에 출처 문서명을 달았다. '
        '문서에 없는 조언은 넣지 않았다 &mdash; 예를 들어 <b>&ldquo;어떤 작업엔 어떤 모델&rdquo;의 상세 기준</b>은 '
        '문서에 없어서 빠져 있다. 사내 Bedrock 특이사항은 따로 표시했다.</p>',

        block("1. 세션을 끊는 시점", [
            item("<b><code>/clear</code>는 무관한 작업으로 넘어갈 때.</b> ", clear_q, DOC_COSTS),
            item("<b><code>/compact</code>는 공짜가 아니다.</b> ", compact_q, DOC_COSTS,
                 "연속성이 꼭 필요할 때만 압축하고, 그때는 <code>/compact Focus on ...</code>으로 "
                 "남길 것을 지정한다. CLAUDE.md에 <code># Compact instructions</code> 절을 두면 "
                 "매번 적용된다."),
            item("<b>고액 지출의 전형적 원인이 바로 이 두 가지다.</b> ", spend_q, DOC_COSTS),
        ]),

        block("2. 탐색은 서브에이전트에 위임", [
            item("", sub_q, DOC_COSTS),
            item("단순 작업은 모델을 내려서: ", haiku_q, DOC_COSTS,
                 "전역으로는 <code>CLAUDE_CODE_SUBAGENT_MODEL</code>."),
            item("<b>다만 남용하면 역효과다.</b> ", subbad_q, DOC_SUBAGENT,
                 "에이전트 팀은 더 비싸다 &mdash; <i>&ldquo;" + team_q + "&rdquo;</i>."),
        ]),

        block("3. 매 세션 깔려 있는 상시 비용 줄이기", [
            item("<b>CLAUDE.md는 200줄 미만.</b> ", md_q, DOC_COSTS,
                 "세션 시작마다 전량 로드되므로 무관한 작업 중에도 계속 값을 낸다. 절차성 내용은 "
                 "skill이나 <code>.claude/rules/</code>로 옮기고, <code>/doctor</code>가 잘라낼 "
                 "후보를 제안해준다."),
            item("<b>훅으로 미리 걸러라.</b> ", hook_q, DOC_COSTS),
            item("<b>MCP는 문서가 두 가지를 말한다 &mdash; 둘 다 옮긴다.</b> 오버헤드는 이미 작다: ",
                 mcp_defer_q, DOC_COSTS,
                 "그래도 CLI 쪽을 권한다 &mdash; <i>&ldquo;" + mcp_cli_q + "&rdquo;</i>. 안 쓰는 서버는 "
                 "<code>/mcp</code>로 끄고, <code>/context</code>로 무엇이 자리를 먹는지 확인할 것."),
        ]),

        block("4. 출력과 thinking", [item("", think_q, DOC_COSTS)]),

        block("5. 모델", [
            item("", sonnet_q, DOC_COSTS),
            item("<b>다만 대화 중간에 손으로 바꾸는 것은 대가가 있다:</b> ", switch_q, DOC_MODEL,
                 "단계별 자동 전환은 <code>opusplan</code>이 한다 &mdash; <i>&ldquo;" + opusplan_q
                 + "&rdquo;</i>."),
            item("<b>Bedrock 특이사항:</b> ", bedrock_q, DOC_BEDROCK,
                 "기본 모델을 명시하지 않으면 Opus 요율이 붙는다."),
        ]),

        block("6. 잘못된 방향으로 가는 비용을 먼저 막기", [
            item("<b>plan mode.</b> ", plan_q, DOC_COSTS,
                 "방향이 틀렸으면 Escape로 즉시 중단하고 <code>/rewind</code>로 되돌린다."),
            item("<b>구체적으로 요청.</b> ", vague_q, DOC_COSTS),
            item("<b>컨텍스트를 줄이는 이유는 비용만이 아니다.</b> ", rot_q, DOC_CTXWIN),
        ]),
    ]

    if stats.get("miss_share", 0) >= 0.15:
        hot = sorted(((v[0], k) for k, v in (vers or {}).items() if v[0]),
                     reverse=True)[:2]
        tail = ""
        if hot:
            names = ", ".join("<code>" + esc(v) + "</code>" for _, v in hot)
            tail = ("이 리포트에서 미스가 가장 몰린 Claude Code 버전은 " + names + "이다. "
                    "changelog에는 세션 중 MCP 연결&middot;툴 스키마 변경&middot;language server 재연결이 "
                    "프롬프트 캐시를 깨던 버그가 여러 번 수정된 기록이 있으니 <b>먼저 최신 버전으로 "
                    "올리고 다음 달 이 값을 다시 볼 것</b>. 버전과 사용 습관은 같은 기간에 섞여 있어 "
                    "원인을 단정할 수는 없다.")
        out.append(block("7. 캐시 미스 &mdash; 이미 낸 컨텍스트를 다시 쓰는 비용", [
            item("공식 문서가 드는 전체 무효화 원인은 툴 정의 변경이다: ", tool_q, DOC_CACHE,
                 "Claude Code에서는 <b>세션 중간에 MCP 서버를 붙이거나 떼는 것</b>, 플러그인&middot;스킬 "
                 "토글, thinking/effort 설정 변경, 모델 전환이 여기 해당한다. 세션 시작 전에 "
                 "붙여두고 중간에 건드리지 않는 편이 싸다."),
            item(tail) if tail else "",
        ]))

    out.append(block("8. 스스로 확인하는 방법", [
        item("<code>/context</code>는 무엇이 컨텍스트를 차지하는지 분해해 보여주고, "
             "<code>/usage</code>(별칭 <code>/cost</code>)는 세션 비용과 skill&middot;subagent&middot;plugin&middot;"
             "MCP별 귀속을 보여준다. cache miss가 최근 사용량의 10% 이상이면 behavior flag로 "
             "표시된다. ", None, None, cite(DOC_CMDS)),
        item("<code>/insights</code>는 토큰이 아니라 <b>일하는 방식</b>을 분석한 HTML 리포트를 "
             "<code>~/.claude/usage-data/report.html</code>에 남긴다. 이 리포트와 상호보완이다. ",
             None, None, cite(DOC_COSTS)),
        item("<b>주의 &mdash; <code>/usage</code>의 금액과 이 리포트의 금액은 다르다.</b> ", usage_q,
             DOC_COSTS, "이 리포트가 대시보드 실청구액에 정규화하는 이유다."),
    ]))
    out.append(sources_html())
    out.append("</details>")
    return "".join(out)


HTML_TMPL = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{month} Claude Code &middot; Bedrock 비용 리포트</title>
<style>
:root{{--bg:#0f1420;--card:#171e2e;--line:#26314a;--tx:#e7ecf5;--mut:#93a0b8;--accent:#4f7cff;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--tx);font:15px/1.6 -apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;padding:32px}}
.wrap{{max-width:940px;margin:0 auto}} h1{{font-size:26px;margin:0 0 4px}} .sub{{color:var(--mut);margin:0 0 26px}}
h2{{font-size:18px;margin:36px 0 12px;border-left:3px solid var(--accent);padding-left:10px}}
.badge{{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px;margin-left:8px;vertical-align:middle}}
.b-auth{{background:#12351f;color:#5fd39a;border:1px solid #1f5c37}} .b-approx{{background:#3a2a12;color:#e0a95f;border:1px solid #6b4a1f}}
.cards{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:8px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;flex:1;min-width:130px}}
.card .k{{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.5px}} .card .v{{font-size:24px;font-weight:700;margin-top:4px}}
.card .delta{{display:block;font-size:12px;font-weight:600;margin-top:4px}}
.d-up{{color:#e0725f}} .d-down{{color:#4f7cff}} .d-flat{{color:var(--mut);font-weight:400}}
.summary{{font-size:15px;line-height:1.75;margin:2px 0 22px;color:var(--tx)}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-bottom:4px}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:14px}}
th{{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px}} tr:last-child td{{border-bottom:none}}
.num{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}} .pct{{text-align:right;color:var(--mut);font-variant-numeric:tabular-nums}}
.mono{{text-align:right;font-family:ui-monospace,monospace;color:var(--mut);font-size:13px}} .name{{font-weight:600;white-space:nowrap}}
.theme{{color:var(--mut);font-size:13px}} .barcell{{width:160px}}
.bar{{background:#0c1220;border-radius:6px;height:14px;overflow:hidden}} .bar span{{display:block;height:100%;border-radius:6px}}
.tag{{background:#0c1220;border:1px solid var(--line);padding:2px 8px;border-radius:20px;font-size:12px}}
.note{{background:var(--card);border:1px solid var(--line);border-left:3px solid #d98b2b;border-radius:10px;padding:14px 18px;color:var(--mut);font-size:13.5px}} .note b{{color:var(--tx)}}
ul{{padding-left:20px}} li{{margin:6px 0}} code{{background:#0c1220;padding:2px 6px;border-radius:5px;font-size:13px}}
.formula{{background:#0c1220;border:1px solid var(--line);border-radius:10px;padding:14px 18px;font-family:ui-monospace,monospace;font-size:13px;color:#cdd7ea;overflow-x:auto;line-height:1.9}}
.foot{{color:var(--mut);font-size:12px;margin-top:36px;border-top:1px solid var(--line);padding-top:14px}}
.scroll{{max-height:360px;overflow-y:auto;border:1px solid var(--line);border-radius:10px}}
.scroll table{{margin:0}} .scroll thead th{{position:sticky;top:0;background:var(--card);z-index:1}}
details{{margin-top:34px;border-top:1px solid var(--line);padding-top:10px}}
details summary{{cursor:pointer;font-size:17px;font-weight:600;padding:8px 0;color:var(--mut)}}
details[open] summary{{color:var(--tx)}}
.cite{{color:var(--mut);font-size:12px}}
h3.grp{{font-size:13px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--tx);margin:26px 0 8px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}}
h3.grp::before{{content:"";width:14px;height:2px;background:var(--accent);flex:0 0 14px}}
.ghint{{color:var(--mut);font-weight:400;font-size:12px;text-transform:none;letter-spacing:0}}
.eff .theme{{line-height:1.7}}
.eff .name{{white-space:normal;width:208px;line-height:1.45}}
.eff td.num{{width:120px;white-space:nowrap;vertical-align:top}}
.eff .sub{{display:block;font-size:11px;font-weight:400;color:var(--mut);margin-top:3px}}
.swatch{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:7px;vertical-align:baseline}}
.ctxdiag{{width:100%;max-width:800px;height:auto;display:block;margin:4px 0 14px}}
.dcap{{color:var(--mut);font-size:12.5px;margin:-6px 0 8px}}
.gloss table.subtable{{margin-top:16px}}
.gloss table.subtable .num div{{white-space:nowrap}}
.gloss table.subtable .num div+div{{margin-top:2px}}
.ctxdiag .dlab{{fill:var(--mut);font-size:9px}}
.ctxdiag .dhdr{{fill:var(--tx);font-size:9.5px;font-weight:700}}
.ctxdiag .dseg{{fill:#0c1220;font-size:8.5px;font-weight:700}}
.ctxdiag .dsegl{{fill:var(--tx);font-size:8.5px;font-weight:700}}
.ctxdiag .dseg2{{font-size:8px;font-weight:700}}
th.verdict,td.verdict{{width:62px;text-align:center;padding-left:14px;padding-right:6px}}
.pill{{display:inline-block;font-size:11px;font-weight:700;padding:3px 9px;border-radius:20px;white-space:nowrap}}
.p-good{{background:#12351f;color:#5fd39a;border:1px solid #1f5c37}}
.p-ok{{background:#1b2437;color:#93a0b8;border:1px solid #2e3a53}}
.p-check{{background:#3a2418;color:#f0907e;border:1px solid #6b3327}}
.p-none{{color:#566178;border:1px dashed #2e3a53;background:none}}
.ins .blk{{display:grid;grid-template-columns:66px 1fr;gap:0 12px;margin-top:8px}}
.ins .blk:first-of-type{{margin-top:2px}}
.ins .blk dt{{font-size:11px;font-weight:700;color:var(--mut);letter-spacing:.4px;padding-top:3px}}
.ins .blk dd{{margin:0}}
@media (max-width:620px){{.ins .blk{{grid-template-columns:1fr;gap:2px}}}}
.inswrap{{display:flex;flex-direction:column;gap:12px}}
.ins{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--mut);border-radius:12px;padding:14px 18px;font-size:14px;line-height:1.75}}
.ins .eyebrow{{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;margin-bottom:6px}}
.ins-ctx{{border-left-color:#4f7cff}} .ins-ctx .eyebrow{{color:#7d9dff}}
.ins-waste{{border-left-color:#e0725f}} .ins-waste .eyebrow{{color:#f0907e}}
.ins-hygiene{{border-left-color:#d98b2b}} .ins-hygiene .eyebrow{{color:#e0a95f}}
.ins-model{{border-left-color:#a06bff}} .ins-model .eyebrow{{color:#bd94ff}}
.ins-proj{{border-left-color:#22a06b}} .ins-proj .eyebrow{{color:#5fd39a}}
.ins-note{{border-left-color:#3b475f}} .ins-note .eyebrow{{color:var(--mut)}}
summary:focus-visible{{outline:2px solid var(--accent);outline-offset:3px;border-radius:6px}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
.gloss,.play{{margin:12px 0 18px;border:1px solid var(--line);border-radius:12px;background:var(--card);padding:0 18px 8px}}
.gloss summary,.play summary{{font-size:14px;padding:12px 0}}
.gloss h4,.play h4{{font-size:14px;margin:20px 0 6px;color:var(--tx)}}
.play li,.gloss li{{margin:10px 0;line-height:1.75}}
.play i,.gloss i{{color:#cdd7ea}}
ul.src{{font-size:12px;color:var(--mut);margin-top:6px}} ul.src code{{font-size:11px}}
.projrow{{margin:0 0 8px;border:1px solid var(--line);border-top:1px solid var(--line);border-radius:12px;background:var(--card);padding:0}}
.projrow summary{{display:flex;align-items:center;gap:14px;padding:12px 14px;font-size:14px;font-weight:400;list-style:none}}
.projrow summary::-webkit-details-marker{{display:none}}
.projrow summary::before{{content:"";flex:0 0 8px;width:8px;height:8px;border-right:1.5px solid var(--mut);border-bottom:1.5px solid var(--mut);transform:rotate(-45deg);transition:transform .15s ease;margin-right:2px}}
.projrow[open] summary::before{{transform:rotate(45deg)}}
.projrow summary:hover::before{{border-color:var(--accent)}}
.projrow .name{{flex:2;font-weight:600;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.projrow .num{{flex:0 0 90px;text-align:right;font-variant-numeric:tabular-nums;font-weight:600;color:var(--tx)}}
.projrow .pct{{flex:0 0 60px;text-align:right;color:var(--mut)}}
.projrow .barcell{{flex:0 0 140px}}
.projrow .subtable{{margin:0;border:none;border-top:1px solid var(--line);border-radius:0;background:#0c1220}}
.daychart{{width:100%;height:auto;display:block;background:var(--card);border:1px solid var(--line);border-radius:12px}}
.daychart .axis{{fill:var(--mut);font-size:12px}}
</style></head><body><div class="wrap">
<h1>{who}{month} Claude Code &middot; AWS Bedrock 비용 리포트</h1>
<p class="sub">기간 {month} &middot; 실청구액 <b>${total_cost:,.2f}</b></p>
<div class="cards">{cards}</div>
{summary}
{warn}
<h2>모델별 비용 {badge}</h2>
<table><thead><tr><th>모델</th><th class="mono">토큰</th><th class="num">비용</th><th class="pct">비중</th><th>&#12288;</th></tr></thead>
<tbody>{model_rows}</tbody></table>
<h2>토큰 종류별 비용 {badge}</h2>
{glossary}
<table><thead><tr><th>종류</th><th class="mono">토큰</th><th class="num">비용</th><th class="pct">비중</th><th>&#12288;</th></tr></thead>
<tbody>{type_rows}</tbody></table>
{eff}
<h2>날짜별 비용 흐름 &middot; 전체 프로젝트 <span class="badge b-approx">로컬 로그 근사</span></h2>
{day_chart}
<p class="note">점선 두 개는 Anthropic이 공개한 기준선입니다. 아래쪽이 개발자 1명의 하루 평균 <b>${bench_avg}</b>, 위쪽이 <b>${bench_p90}</b>로 사용자의 90%가 이 아래입니다. 일별 금액은 로컬 로그 비율로 나눈 근사값이라 총액만 정확합니다.</p>
<h2>프로젝트별 비용 <span class="badge b-approx">로컬 로그 근사</span></h2>
<div class="scroll">{proj_rows}</div>
<p class="note">프로젝트를 펼치면 그 프로젝트 자신의 날짜별 비용과 <b>그 프로젝트 자신의 git log</b>(커밋 테마)가 나온다 &mdash; 다른 프로젝트의 커밋이 섞이지 않는다. 날짜별 흐름 차트는 전체 프로젝트 합계, 프로젝트/날짜 금액은 로컬 세션 로그의 상대분포(메시지별 실제 모델로 가중)를 실청구액에 맞춘 <b>근사치</b>.</p>
<h2>인사이트</h2><div class="inswrap">{insights}</div>
{playbook}
<details>
<summary>산정 근거 (Methodology) &mdash; 펼쳐보기</summary>
<p>raw 토큰 비례 배분은 왜곡됨 &mdash; 캐시 읽기가 토큰의 대부분이나 단가는 출력의 1/50. 각 토큰을 <b>모델별 단가(rates.json)로 가중</b>한 "비용 프록시"를 만든 뒤 실청구액에 정규화.</p>
<div class="formula">
proxy = &Sigma;_model &Sigma;_type ( tokens &times; rate[model][type] )&nbsp;&nbsp;(rates.json, per 1M)<br>
scale_local(프로젝트/일자) = ${total_cost:,.2f} / {proxy_sum:,.2f} = {scale_local:.4f}<br>
scale_model(모델/종류) = ${total_cost:,.2f} / (정가 프록시 합) &rarr; 실단가 &asymp; 정가의 {scale_auth:.0%}
</div>
<ul>
<li><b>단가&middot;모델:</b> 코드에 하드코딩 없음. <code>rates.json</code>에서 부분문자열 매칭. 새 모델&middot;단가 변경 시 그 파일만 수정.</li>
<li><b>모델 구성:</b> CSV/API 제공 시 AICM 기준(권위). 미제공 시 로컬 로그의 메시지별 <code>model</code>로 실측(근사). all-Opus 가정 없음.</li>
<li><b>턴당 컨텍스트:</b> 로컬 로그의 cache_read &divide; 턴 수. 비율이므로 resume/fork로 인한 메시지 중복에 영향받지 않음. 최대 컨텍스트는 한 호출의 cache_read+cache_write.</li>
<li><b>모델 이전 시뮬:</b> 같은 토큰량을 대상 모델 단가로 환산해 실청구액에 비례 적용한 <b>규모 추정</b>. 실제로는 모델을 바꾸면 토큰량 자체도 달라지므로 상한선으로 볼 것.</li>
<li><b>그룹 대비:</b> 그룹 집계(인원 수&middot;총액)만 사용. 타인의 개별 데이터는 리포트에 포함되지 않음.</li>
<li><b>한계:</b> 로컬 로그는 이 머신의 부분 기록(resume/fork 중복, 타 환경 세션 누락 가능) &rarr; 프로젝트/날짜/세션 지표는 근사, 총액&middot;모델은 AICM이 권위.</li>
</ul>
</details>
<p class="foot">생성: <code>bedrock-cost-report/scripts/driver.py</code> &middot; 단가: <code>rates.json</code> &middot; 공식 문서 인용 기준 시점: <code>{docs_asof}</code> (문서는 갱신되므로 오래됐으면 원문 재확인).</p>
</div></body></html>"""


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Monthly Bedrock cost report")
    ap.add_argument("--month", default=time.strftime("%Y-%m"),
                    help="YYYY-MM (default: this month, month-to-date)")
    ap.add_argument("--csv", help="AICM per-user CSV export (primary input)")
    ap.add_argument("--fetch", action="store_true",
                    help="pull YOUR OWN usage from the dashboard API instead of "
                         "--csv (identity: $BEDROCK_KNOX_ID or git user.email). "
                         "Takes no id -- see the self-only note in main().")
    ap.add_argument("--org", help="budgetOrgId for --fetch ($BEDROCK_ORG_ID)")
    ap.add_argument("--employee", help="row to pick when CSV has multiple users")
    ap.add_argument("--cost", type=float, help="billed USD (only if no --csv)")
    ap.add_argument("--rates", default=os.path.join(here, "rates.json"))
    ap.add_argument("--out", help="output HTML path")
    ap.add_argument("--compare-start", help="override the 전월 대비 window (--fetch only); "
                    "needs --compare-end too. Default: the full previous calendar month.")
    ap.add_argument("--compare-end", help="see --compare-start")
    a = ap.parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}", a.month):
        print("--month must be YYYY-MM", file=sys.stderr)
        return 2
    if bool(a.compare_start) != bool(a.compare_end):
        print("--compare-start and --compare-end must be given together", file=sys.stderr)
        return 2
    rates = load_rates(a.rates)
    org, bands = {}, {}
    if a.fetch:
        # Self-only by design. The project / day / session sections come from
        # THIS machine's ~/.claude/projects, which nobody else's logs are in, so
        # a report about another person would pair their bill with your work
        # history. There is no --fetch <knoxId>; identity comes from the machine.
        sys.path.insert(0, here)
        import fetch_usage
        who = fetch_usage.whoami()
        if not who:
            print("cannot tell who you are: set BEDROCK_KNOX_ID, or configure "
                  "`git config user.email` with your corp mail", file=sys.stderr)
            return 2
        cur_start, cur_end = fetch_usage.month_range(a.month)
        payload = fetch_usage.fetch(a.org or fetch_usage.ORG, cur_start, cur_end)
        me = fetch_usage.pick_user(payload, who)
        if me is None:
            print(f"'{who}' has no usage row in this org for {a.month}. Check "
                  f"BEDROCK_KNOX_ID, or set BEDROCK_ORG_ID/--org to your own "
                  f"budget org.", file=sys.stderr)
            return 1
        buf = io.StringIO()
        fetch_usage.to_csv({**payload, "users": [me]}, buf)
        capture = parse_aicm_text(buf.getvalue(), None)
        # Tercile cut points for the ratings, computed here while the org's rows
        # are still in hand and reduced to two numbers before anything is kept.
        bands = org_bands(payload.get("users"), rates)
        org = fetch_usage.org_summary(a.org or fetch_usage.ORG, cur_start, cur_end)
        who_display = me.get("knoxId") or who
        # 전월 대비 delta needs last month's own bill too. Default is the FULL
        # previous month against however much of the current month has landed
        # so far -- a pacing question ("already past all of last month?"), not
        # a same-length rate. --compare-start/--compare-end override the window
        # when the user asks for a specific different period. Best-effort: the
        # org may not have existed yet, or the API may hiccup -- either way this
        # is a nice-to-have, not worth failing the whole run over.
        prev_capture = None
        try:
            if a.compare_start and a.compare_end:
                p_start, p_end = a.compare_start, a.compare_end
            else:
                p_start, p_end = fetch_usage.month_range(prev_month(a.month))
            ppayload = fetch_usage.fetch(a.org or fetch_usage.ORG, p_start, p_end)
            pme = fetch_usage.pick_user(ppayload, who)
            if pme is not None:
                pbuf = io.StringIO()
                fetch_usage.to_csv({**ppayload, "users": [pme]}, pbuf)
                prev_capture = parse_aicm_text(pbuf.getvalue(), None)
        except Exception:
            prev_capture = None
    else:
        capture = parse_aicm_csv(a.csv, a.employee) if a.csv else None
        who_display, prev_capture = (a.employee or ""), None
    total_cost = (capture or {}).get("total_cost") or a.cost
    if not total_cost:
        print("Need a billed total: pass --fetch/--csv (with total_cost) or --cost",
              file=sys.stderr)
        return 2
    cwd = os.getcwd()
    proj, day, proj_day, sessions, vers = scan_logs(a.month, cwd)
    # Last month's session stats, for the two metrics with no peer and no
    # published threshold. A second pass over the logs, which is why it only
    # collects session stats and drops everything else.
    prev = session_stats(scan_logs(prev_month(a.month), cwd)[3])
    if not proj and not capture:
        print(f"No local logs for {a.month} and no --csv; nothing to report", file=sys.stderr)
        return 1
    out = a.out or f"{a.month}-bedrock-cost-report.html"  # cwd, no subdir
    print(f"wrote {render(a.month, total_cost, proj, day, proj_day, capture, rates, out, sessions, org, vers, bands, prev, who=who_display, prev_capture=prev_capture)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
