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
attribution reads each message's own model, so mixed-model usage is handled — there
is no all-Opus fallback. A model with no rate entry is reported, never guessed.

Usage:
  driver.py --fetch                              # you, this month — the usual call
  driver.py --fetch --month 2026-07
  driver.py --month 2026-08 --csv aicm-export.csv
  driver.py --month 2026-08 --csv aicm-export.csv --employee jibin.sung
  driver.py --month 2026-08 --cost 701.24        # no CSV: local logs only
  driver.py --month 2026-08 --csv x.csv --rates /path/rates.json --out report.html
"""
import argparse, csv, glob, html, io, json, os, re, subprocess, sys, time
from collections import defaultdict

FIELDS = ("in", "cache_read", "cache_write", "out")  # canonical token-type order


def load_rates(path: str) -> dict:
    """Load {model_substring: {in,cache_read,cache_write,out}} from rates.json."""
    with open(path) as fh:
        raw = json.load(fh)
    return {k.lower(): v for k, v in raw.items() if not k.startswith("_")}


def rate_for(model_name: str, rates: dict):
    """Return the rate dict whose key is a substring of model_name, else None.

    No default tier: an unknown model is surfaced, not silently priced as Opus.
    """
    n = (model_name or "").lower()
    for key, r in rates.items():
        if key and key in n:
            return r
    return None


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


def scan_logs(month: str, cwd: str):
    """Aggregate the month's local usage, split BY MODEL.

    Returns (proj, day, proj_day, sessions) where:
      proj     = {project_dir: {model: {in,cache_read,cache_write,out}}}
      day      = {YYYY-MM-DD: {model: {...}}}   (ALL projects, not just cwd)
      proj_day = {project_dir: {YYYY-MM-DD: {model: {...}}}}  (per-project drill-down)
      sessions = [{turns, cache_read, ctx_max}]  per session file, for the
                 context-hygiene metrics
    """
    root = os.path.expanduser("~/.claude/projects")
    proj: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    day: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    proj_day: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(int))))
    sessions = []
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
        project = os.path.basename(os.path.dirname(f))
        s = {"turns": 0, "cache_read": 0, "ctx_max": 0}
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
                # cache_read + cache_write on one call ≈ context size that turn
                s["ctx_max"] = max(s["ctx_max"], rec["cache_read"] + rec["cache_write"])
        if s["turns"]:
            sessions.append(s)
    return proj, day, proj_day, sessions


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
    run from — a project with no resolvable/git repo just gets no themes.
    """
    try:
        out = subprocess.run(
            ["git", "-C", repo_path, "log", f"--since={month}-01",
             "--until", f"{month}-31", "--date=short", "--pretty=format:%ad|%s"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return {}
    themes = defaultdict(list)
    for line in out.splitlines():
        if "|" in line:
            d, subj = line.split("|", 1)
            themes[d].append(subj)
    return {d: " · ".join(s[:70] for s in subs[:4]) for d, subs in themes.items()}


def day_chart_svg(day_billed: dict, width=880, height=140, pad=24) -> str:
    """Inline SVG line+area chart of cost by day — flow only, no exact numbers.

    No JS, no charting library: just polyline/polygon points computed in
    Python. Exact per-day figures live in each project's drill-down table.
    """
    days = sorted(day_billed)
    if not days:
        return '<p class="note">데이터 없음</p>'
    vals = [day_billed[d] for d in days]
    vmax = max(vals) or 1.0
    n = len(days)
    step = (width - 2 * pad) / max(n - 1, 1)
    pts = [(pad + i * step, height - pad - (v / vmax) * (height - 2 * pad))
           for i, v in enumerate(vals)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pad:.1f},{height - pad:.1f} " + poly + f" {width - pad:.1f},{height - pad:.1f}"
    peak_i = vals.index(vmax)
    return (
        f'<svg viewBox="0 0 {width} {height}" class="daychart" preserveAspectRatio="none">'
        f'<polygon points="{area}" fill="#4f7cff22"/>'
        f'<polyline points="{poly}" fill="none" stroke="#4f7cff" stroke-width="2"/>'
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
    text = text.lstrip("﻿").strip("\n")
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
    numerator and denominator alike — it survives the local-log caveat that makes
    absolute counts untrustworthy.
    """
    turns = sum(s["turns"] for s in sessions)
    cr = sum(s["cache_read"] for s in sessions)
    if not turns or not cr:
        return {}
    top = sorted(sessions, key=lambda s: -s["cache_read"])[:8]
    longs = [s for s in sessions if s["turns"] >= 50]
    return {
        "n": len(sessions), "turns": turns, "ctx_per_turn": cr / turns,
        "top_n": len(top), "top_share": sum(s["cache_read"] for s in top) / cr,
        "long_n": len(longs), "long_share": sum(s["cache_read"] for s in longs) / cr,
        "ctx_max": max(s["ctx_max"] for s in sessions),
    }


def shift_sim(models_M: dict, rates: dict, total_cost: float, frac=0.7,
              target="sonnet"):
    """Bill if `frac` of Opus token volume had run on `target` instead.

    Ratio-based, so it inherits the report's normalization to the real bill —
    it is a scale estimate, not a quote.
    """
    tr = rate_for(target, rates)
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


def efficiency(cap: dict, total_cost: float, org: dict, stats: dict,
               models_M: dict, rates: dict):
    """(label, value, meaning) rows for the 효율 지표 table. Skips any metric
    whose input is missing rather than printing a zero."""
    cap = cap or {}
    rows = []
    cr = sum(v["cache_read"] for v in models_M.values())
    out = sum(v["out"] for v in models_M.values())
    if out:
        rows.append(("cache_read : output", f"{cr/out:,.0f} : 1",
                     "1토큰 산출을 위해 다시 읽은 컨텍스트 양. 컨텍스트 낭비의 직접 척도"))
    if org.get("users") and org.get("cost"):
        avg = org["cost"] / org["users"]
        label = f"{org.get('name') or '조직'} 대비"
        rows.append((label, f"{total_cost/avg:.1f}배 · 조직의 {total_cost/org['cost']*100:.1f}%",
                     f"{org['users']}명 1인 평균 ${avg:,.2f} 기준 (조직 집계값만, 개인 데이터 없음)"))
    if cap.get("cli_sec"):
        h = cap["cli_sec"] / 3600
        uh = (cap.get("user_sec") or 0) / 3600
        rows.append(("$ / CLI 활동시간", f"${total_cost/h:,.2f} /h",
                     f"CLI 활동 {h:,.1f}h · 사용자 입력 {uh:,.1f}h"))
    if cap.get("commit"):
        rows.append(("$ / 커밋", f"${total_cost/cap['commit']:,.2f}",
                     f"커밋 {int(cap['commit']):,}건"))
    if cap.get("prs"):
        rows.append(("$ / PR", f"${total_cost/cap['prs']:,.2f}",
                     f"PR {int(cap['prs']):,}건 — 건수가 적으면 해석 주의"))
    lines = (cap.get("lines_added") or 0) + (cap.get("lines_removed") or 0)
    if lines:
        rows.append(("$ / 1k 라인", f"${total_cost/(lines/1000):,.2f}",
                     f"+{int(cap.get('lines_added') or 0):,} / -{int(cap.get('lines_removed') or 0):,}"))
    sim = shift_sim(models_M, rates, total_cost)
    if sim and sim < total_cost:
        rows.append(("opus 70% → sonnet 시 추정",
                     f"${sim:,.2f} (−{(1-sim/total_cost)*100:.0f}%)",
                     "같은 토큰량을 sonnet 단가로 환산한 규모 추정치"))
    if stats:
        rows.append(("턴당 평균 컨텍스트", f"{stats['ctx_per_turn']/1000:,.0f}k",
                     f"세션 {stats['n']}개 · {stats['turns']:,}턴 · 최대 {stats['ctx_max']/1000:,.0f}k"))
        rows.append(("50턴↑ 세션 비중",
                     f"cache_read의 {stats['long_share']*100:.0f}%",
                     f"{stats['long_n']}개 세션 / 상위 {stats['top_n']}개가 {stats['top_share']*100:.0f}%"))
    return rows


def render(month, total_cost, proj, day, proj_day, capture, rates, out_path,
           sessions=(), org=None):
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
        # segment — that used to turn `alpha-agent-v3` into `v3`
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
    day_chart = day_chart_svg(day_billed)
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
                f'{esc(", ".join(sorted(unpriced)))} — <code>rates.json</code>에 추가하세요. '
                f'해당 모델은 비용 배분에서 제외됨(임의 추정 안 함).</p>')

    stats = session_stats(list(sessions))
    eff_rows = "".join(
        f'<tr><td class="name">{esc(l)}</td><td class="num">{esc(v)}</td>'
        f'<td class="theme">{esc(n)}</td></tr>'
        for l, v, n in efficiency(capture, total_cost, org or {}, stats,
                                  models_M, rates))
    eff_html = (f'<h2>효율 지표</h2><table><thead><tr><th>지표</th>'
                f'<th class="num">값</th><th>의미</th></tr></thead>'
                f'<tbody>{eff_rows}</tbody></table>') if eff_rows else ""

    # --- insights: 진단(수치) → 메커니즘(왜) → 처방(무엇을 얼마나) -------------
    ins = []
    share = {n: p for n, _, _, p in type_rows}   # "Cache Read" -> % of bill
    cr_M = sum(v["cache_read"] for v in models_M.values())
    out_M = sum(v["out"] for v in models_M.values())
    if share.get("Cache Read") and out_M:
        ctx = f", 턴당 평균 {stats['ctx_per_turn']/1000:,.0f}k" if stats else ""
        ins.append(
            f"<b>진단 — 비용의 {share['Cache Read']+share.get('Cache Write',0):.0f}%가 "
            f"산출물이 아니라 컨텍스트다.</b> Cache Read {share['Cache Read']:.0f}% + "
            f"Cache Write {share.get('Cache Write',0):.0f}% vs 실제 산출(Output) "
            f"{share.get('Output',0):.0f}% (cache_read {cr_M:,.0f}M : output {out_M:,.1f}M = "
            f"{cr_M/out_M:,.0f}:1{ctx}).<br>"
            f"<b>메커니즘:</b> 두 항목은 성격이 다르다. <b>Cache Write는 컨텍스트에 뭔가를 넣을 때 한 번</b> "
            f"내는 비용(예: 5천 줄 파일 열람), <b>Cache Read는 그렇게 넣은 것을 이후 턴마다 다시</b> 내는 비용이다. "
            f"그래서 큰 파일을 한 번 읽는 행위의 실제 비용은 write 1회가 아니라 "
            f"write 1회 + read × (남은 턴 수)다. 비용 ≈ (컨텍스트 크기) × (턴 수).<br>"
            f"<b>처방:</b> 세션 후반에 큰 파일을 통째로 읽는 것이 가장 비싸다 — 남은 턴이 많을수록 재청구가 길어진다. "
            f"필요한 범위만 읽거나(grep·부분 read) 서브에이전트에 맡길 것. 턴 수보다 <b>턴당 컨텍스트</b>가 목표 지표다.")
    if stats:
        ins.append(
            f"<b>진단 — 50턴 이상 장기 세션 {stats['long_n']}개가 cache_read의 {stats['long_share']*100:.0f}%</b>"
            f" (상위 {stats['top_n']}개가 {stats['top_share']*100:.0f}%, 최대 컨텍스트 {stats['ctx_max']/1000:,.0f}k).<br>"
            f"<b>메커니즘:</b> 한 세션에서 브레인스토밍→설계→구현→리뷰를 모두 하면 앞 단계 전사가 이후 모든 턴에 재청구된다. "
            f"단계가 끝나도 그 맥락은 컨텍스트에 남아 계속 과금된다.<br>"
            f"<b>처방:</b> ①<b>단계 경계에서 <code>/clear</code></b> — plan 파일·커밋·PR 설명처럼 산출물이 이미 맥락을 담고 있는 지점에서만 끊는다 "
            f"(superpowers <code>writing-plans</code>→<code>executing-plans</code>가 이 핸드오프 구조다). 문서 한 번 쓰는 비용은 출력 몇 k 토큰, "
            f"큰 컨텍스트를 수백 턴 끌고 가는 비용은 cache_read 수십 M — 자릿수가 다르다. "
            f"②<b>탐색은 서브에이전트에 위임</b> — 파일 덤프가 서브 컨텍스트에서 끝나고 메인에 남지 않는다. "
            f"③<b>디버깅 중에는 끊지 말 것</b> — 실패 흔적이 정보다. <code>/compact</code>가 중간 대안.")
    if model_rows:
        tm = model_rows[0]
        sim = shift_sim(models_M, rates, total_cost)
        cut = (f" 이 리포트 기준으로 opus 토큰량의 70%를 sonnet으로 옮기면 <b>${sim:,.2f} (−{(1-sim/total_cost)*100:.0f}%)</b> 규모다."
               if sim and sim < total_cost else "")
        rr = rate_for("opus", rates), rate_for("sonnet", rates)
        ratio = (f" opus의 cache_read 단가는 sonnet의 <b>{rr[0]['cache_read']/rr[1]['cache_read']:.0f}배</b>이므로, "
                 f"컨텍스트가 큰 단계일수록 모델을 내리는 효과가 커진다." if all(rr) else "")
        ins.append(
            f"<b>진단 — {esc(tm[0])}이 비용의 {tm[3]:.0f}%.</b><br>"
            f"<b>메커니즘:</b> 비용은 토큰량보다 단가에서 갈린다.{ratio}<br>"
            f"<b>처방:</b> 설계·모호한 판단은 상위 모델, <b>탐색·정형 리팩터·테스트 작성·리뷰는 sonnet</b>으로 내릴 것.{cut}")
    if proj_billed:
        tp = max(proj_billed.items(), key=lambda kv: kv[1])
        ins.append(
            f"<b>진단 — 비용이 {esc(short(tp[0]))}에 집중</b>(${tp[1]:,.2f}, {tp[1]/total_cost*100:.0f}%).<br>"
            f"<b>처방:</b> 위 처방들을 전 프로젝트에 적용하기 전에 이 프로젝트에서만 먼저 시험하면 효과를 가장 빨리 확인할 수 있다. "
            f"(프로젝트 배분은 로컬 로그 기반 근사)")
    ins.append(
        f"<b>참고 — 실단가 ≈ Bedrock 정가의 {scale_auth*100:.0f}%.</b> 단가는 이미 계약으로 낮아져 있어 "
        f"추가 절감은 단가 협상이 아니라 위의 사용 패턴(턴당 컨텍스트 · 모델 라우팅)에서만 나온다.")
    insights = "".join(f"<li>{s}</li>" for s in ins)

    cards = f'<div class="card"><div class="k">실 청구액</div><div class="v">${total_cost:,.2f}</div></div>'
    if capture:
        for k, lab in (("calls", "총 호출"), ("sessions", "세션"), ("commit", "커밋")):
            if capture.get(k):
                cards += f'<div class="card"><div class="k">{lab}</div><div class="v">{int(capture[k]):,}</div></div>'

    doc = HTML_TMPL.format(
        month=esc(month), total_cost=total_cost, cards=cards, badge=badge,
        model_rows=model_html, type_rows=type_html, proj_rows=proj_rows,
        day_chart=day_chart, insights=insights, warn=warn, eff=eff_html,
        scale_local=scale_local, proxy_sum=proxy_sum, scale_auth=scale_auth)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(doc)
    return out_path


HTML_TMPL = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{month} Claude Code · Bedrock 비용 리포트</title>
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
.projrow{{margin:0 0 8px;border:1px solid var(--line);border-top:1px solid var(--line);border-radius:12px;background:var(--card);padding:0}}
.projrow summary{{display:flex;align-items:center;gap:14px;padding:12px 14px;font-size:14px;font-weight:400;list-style:none}}
.projrow summary::-webkit-details-marker{{display:none}}
.projrow .name{{flex:2;font-weight:600;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.projrow .num{{flex:0 0 90px;text-align:right;font-variant-numeric:tabular-nums;font-weight:600;color:var(--tx)}}
.projrow .pct{{flex:0 0 60px;text-align:right;color:var(--mut)}}
.projrow .barcell{{flex:0 0 140px}}
.projrow .subtable{{margin:0;border:none;border-top:1px solid var(--line);border-radius:0;background:#0c1220}}
.daychart{{width:100%;height:140px;display:block}} .daychart .axis{{fill:var(--mut);font-size:11px}}
</style></head><body><div class="wrap">
<h1>{month} Claude Code · AWS Bedrock 비용 리포트</h1>
<p class="sub">기간 {month} · 실청구액 <b>${total_cost:,.2f}</b></p>
<div class="cards">{cards}</div>
{warn}
<h2>모델별 비용 {badge}</h2>
<table><thead><tr><th>모델</th><th class="mono">토큰</th><th class="num">비용</th><th class="pct">비중</th><th>　</th></tr></thead>
<tbody>{model_rows}</tbody></table>
<h2>토큰 종류별 비용 {badge}</h2>
<table><thead><tr><th>종류</th><th class="mono">토큰</th><th class="num">비용</th><th class="pct">비중</th><th>　</th></tr></thead>
<tbody>{type_rows}</tbody></table>
{eff}
<h2>날짜별 비용 흐름 · 전체 프로젝트 <span class="badge b-approx">로컬 로그 근사</span></h2>
{day_chart}
<h2>프로젝트별 비용 <span class="badge b-approx">로컬 로그 근사</span></h2>
<div class="scroll">{proj_rows}</div>
<p class="note">프로젝트를 펼치면 그 프로젝트 자신의 날짜별 비용과 <b>그 프로젝트 자신의 git log</b>(커밋 테마)가 나온다 — 다른 프로젝트의 커밋이 섞이지 않는다. 날짜별 흐름 차트는 전체 프로젝트 합계, 프로젝트/날짜 금액은 로컬 세션 로그의 상대분포(메시지별 실제 모델로 가중)를 실청구액에 맞춘 <b>근사치</b>.</p>
<h2>인사이트</h2><ul>{insights}</ul>
<details>
<summary>산정 근거 (Methodology) — 펼쳐보기</summary>
<p>raw 토큰 비례 배분은 왜곡됨 — 캐시 읽기가 토큰의 대부분이나 단가는 출력의 1/50. 각 토큰을 <b>모델별 단가(rates.json)로 가중</b>한 "비용 프록시"를 만든 뒤 실청구액에 정규화.</p>
<div class="formula">
proxy = Σ_model Σ_type ( tokens × rate[model][type] )&nbsp;&nbsp;(rates.json, per 1M)<br>
scale_local(프로젝트/일자) = ${total_cost:,.2f} / {proxy_sum:,.2f} = {scale_local:.4f}<br>
scale_model(모델/종류) = ${total_cost:,.2f} / (정가 프록시 합) → 실단가 ≈ 정가의 {scale_auth:.0%}
</div>
<ul>
<li><b>단가·모델:</b> 코드에 하드코딩 없음. <code>rates.json</code>에서 부분문자열 매칭. 새 모델·단가 변경 시 그 파일만 수정.</li>
<li><b>모델 구성:</b> CSV/API 제공 시 AICM 기준(권위). 미제공 시 로컬 로그의 메시지별 <code>model</code>로 실측(근사). all-Opus 가정 없음.</li>
<li><b>턴당 컨텍스트:</b> 로컬 로그의 cache_read ÷ 턴 수. 비율이므로 resume/fork로 인한 메시지 중복에 영향받지 않음. 최대 컨텍스트는 한 호출의 cache_read+cache_write.</li>
<li><b>모델 이전 시뮬:</b> 같은 토큰량을 대상 모델 단가로 환산해 실청구액에 비례 적용한 <b>규모 추정</b>. 실제로는 모델을 바꾸면 토큰량 자체도 달라지므로 상한선으로 볼 것.</li>
<li><b>그룹 대비:</b> 그룹 집계(인원 수·총액)만 사용. 타인의 개별 데이터는 리포트에 포함되지 않음.</li>
<li><b>한계:</b> 로컬 로그는 이 머신의 부분 기록(resume/fork 중복, 타 환경 세션 누락 가능) → 프로젝트/날짜/세션 지표는 근사, 총액·모델은 AICM이 권위.</li>
</ul>
</details>
<p class="foot">생성: <code>bedrock-cost-report/scripts/driver.py</code> · 단가: <code>rates.json</code>.</p>
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
                         "Takes no id — see the self-only note in main().")
    ap.add_argument("--org", help="budgetOrgId for --fetch ($BEDROCK_ORG_ID)")
    ap.add_argument("--employee", help="row to pick when CSV has multiple users")
    ap.add_argument("--cost", type=float, help="billed USD (only if no --csv)")
    ap.add_argument("--rates", default=os.path.join(here, "rates.json"))
    ap.add_argument("--out", help="output HTML path")
    a = ap.parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}", a.month):
        print("--month must be YYYY-MM", file=sys.stderr)
        return 2
    rates = load_rates(a.rates)
    org = {}
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
        payload = fetch_usage.fetch(a.org or fetch_usage.ORG,
                                    *fetch_usage.month_range(a.month))
        me = fetch_usage.pick_user(payload, who)
        if me is None:
            print(f"'{who}' has no usage row in this org for {a.month}. Check "
                  f"BEDROCK_KNOX_ID, or set BEDROCK_ORG_ID/--org to your own "
                  f"budget org.", file=sys.stderr)
            return 1
        buf = io.StringIO()
        fetch_usage.to_csv({**payload, "users": [me]}, buf)
        capture = parse_aicm_text(buf.getvalue(), None)
        org = fetch_usage.org_summary(a.org or fetch_usage.ORG,
                                      *fetch_usage.month_range(a.month))
    else:
        capture = parse_aicm_csv(a.csv, a.employee) if a.csv else None
    total_cost = (capture or {}).get("total_cost") or a.cost
    if not total_cost:
        print("Need a billed total: pass --fetch/--csv (with total_cost) or --cost",
              file=sys.stderr)
        return 2
    cwd = os.getcwd()
    proj, day, proj_day, sessions = scan_logs(a.month, cwd)
    if not proj and not capture:
        print(f"No local logs for {a.month} and no --csv; nothing to report", file=sys.stderr)
        return 1
    out = a.out or f"{a.month}-bedrock-cost-report.html"  # cwd, no subdir
    print(f"wrote {render(a.month, total_cost, proj, day, proj_day, capture, rates, out, sessions, org)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
