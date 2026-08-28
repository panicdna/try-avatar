#!/usr/bin/env python3
"""Fetch org Bedrock usage from the dashboard's own JSON API and emit the same
CSV the dashboard's "CSV 다운로드" button produces, so driver.py --csv works
unchanged.

    python3 fetch_usage.py --month 2026-08 | python3 driver.py --month 2026-08 --csv - --employee <knoxId>

The endpoint is the page's internal API (`/api/budget-org/users?...&detail=full`,
behind /budget-org?budgetOrgId=…) — same-origin, no auth on the corp network.
ponytail: no session/cookie handling until the dashboard actually starts
requiring one.

Scoped to a budget org rather than a manually-registered group, so every member
of the org is covered without anyone having to be added first. The response
carries the whole org's rows; driver.py keeps only the caller's and discards the
rest, and the report shows org-level aggregates only.
"""
import argparse
import calendar
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

BASE = "https://aws-bedrock.codehub.samsungds.net"
# S/W혁신팀(S.LSI); override with $BEDROCK_ORG_ID or --org for another org
ORG = os.environ.get("BEDROCK_ORG_ID") or "20017947"
NETWORK = {"legacy": "AI Dev Network", "current": "Office Network"}
DEPTS = [f"dept_level_{n}_name" for n in (3, 4, 5, 6, 7, 8)]
COUNTS = [("call_count", "calls"), ("commit_count", "ccCommits"),
          ("pull_request_count", "ccPullRequests"), ("session_count", "ccSessions"),
          ("lines_added", "ccLinesAdded"), ("lines_removed", "ccLinesRemoved"),
          ("cli_active_sec", "ccCliActiveSec"), ("user_active_sec", "ccUserActiveSec")]
TOKENS = [("input", "inputTokens"), ("output", "outputTokens"),
          ("cache_read", "cacheReadTokens"), ("cache_write", "cacheWriteTokens")]


def whoami() -> str:
    """This machine's knoxId: $BEDROCK_KNOX_ID, else local part of git user.email.

    ponytail: git identity is the only id every teammate already has configured;
    no login, no credential store reading.
    """
    env = (os.environ.get("BEDROCK_KNOX_ID") or "").strip()
    if env:
        return env
    try:
        email = subprocess.run(["git", "config", "user.email"], capture_output=True,
                               text=True, timeout=10).stdout.strip()
    except Exception:
        email = ""
    return email.split("@")[0]


def pick_user(payload: dict, who: str):
    w = who.lower()
    for u in payload.get("users") or []:
        if (u.get("knoxId") or "").lower() == w or \
           (u.get("emailLower") or "").split("@")[0] == w:
            return u
    return None


def month_range(month: str, today=None):
    y, m = (int(x) for x in month.split("-"))
    today = today or dt.date.today()
    end = min(dt.date(y, m, calendar.monthrange(y, m)[1]), today)
    return f"{y:04d}-{m:02d}-01", end.isoformat()


def _get(path: str, params: dict):
    qs = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{BASE}{path}?{qs}", timeout=90) as r:
        return json.load(r)


def fetch(org: str, start: str, end: str) -> dict:
    return _get("/api/budget-org/users", {"budgetOrgId": org, "start": start,
                                          "end": end, "detail": "full"})


def org_summary(org: str, start: str, end: str) -> dict:
    """Org totals + name for the 'vs org average' comparison. Aggregates only —
    no per-person figures from this call enter the report."""
    try:
        s = _get("/api/budget-org/summary", {"budgetOrgId": org, "start": start,
                                             "end": end}).get("summary") or {}
    except Exception:
        return {}
    try:
        name = _get("/api/budget-org/info", {"budgetOrgId": org}).get("name") or ""
    except Exception:
        name = ""
    return {"users": s.get("totalUsers") or 0, "cost": s.get("totalCost") or 0.0,
            "name": name}


def to_csv(payload: dict, out) -> int:
    models = payload.get("availableModels") or []
    header = (["employee_id", "environment"] + DEPTS + ["total_cost"]
              + [c for c, _ in COUNTS]
              + [f"{t}_{m}" for m in models for t, _ in TOKENS])
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    for u in payload.get("users") or []:
        row = [u.get("knoxId") or "-", NETWORK.get(u.get("bucket"), "-")]
        row += [u.get(d) or "-" for d in DEPTS]
        row.append(f"{u.get('cost') or 0:.2f}")
        row += [round(u.get(k) or 0) for _, k in COUNTS]
        md = u.get("modelDetails") or {}
        row += [round((md.get(m) or {}).get(k) or 0) for m in models for _, k in TOKENS]
        w.writerow(row)
    return len(payload.get("users") or [])


def selfcheck():
    payload = {"availableModels": ["opus-5"], "users": [
        {"knoxId": "a.b", "bucket": "current", "cost": 12.345, "calls": 7,
         "dept_level_3_name": "DS부문",
         "modelDetails": {"opus-5": {"inputTokens": 1, "cacheReadTokens": 2}}}]}
    out = __import__("io").StringIO()
    assert to_csv(payload, out) == 1
    rows = list(csv.DictReader(out.getvalue().splitlines()))
    r = rows[0]
    assert r["employee_id"] == "a.b" and r["environment"] == "Office Network"
    assert r["total_cost"] == "12.35" and r["call_count"] == "7"
    assert r["dept_level_3_name"] == "DS부문" and r["dept_level_8_name"] == "-"
    assert r["input_opus-5"] == "1" and r["cache_read_opus-5"] == "2"
    assert r["output_opus-5"] == "0" and r["session_count"] == "0"
    assert month_range("2026-08", dt.date(2026, 8, 19)) == ("2026-08-01", "2026-08-19")
    assert month_range("2026-07", dt.date(2026, 8, 19)) == ("2026-07-01", "2026-07-31")
    p = {"users": [{"knoxId": "A.B", "emailLower": "a.b@samsung.com"}]}
    assert pick_user(p, "a.b") is p["users"][0]
    assert pick_user(p, "a.b@samsung.com".split("@")[0]) is p["users"][0]
    assert pick_user(p, "c.d") is None
    print("all self-checks passed")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", default=dt.date.today().strftime("%Y-%m"),
                    help="YYYY-MM, default this month (capped at today)")
    ap.add_argument("--start", help="YYYY-MM-DD, overrides --month")
    ap.add_argument("--end", help="YYYY-MM-DD, overrides --month")
    ap.add_argument("--org", default=ORG, help="budgetOrgId ($BEDROCK_ORG_ID)")
    ap.add_argument("--out", default="-", help="output CSV path ('-' = stdout)")
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    if a.selfcheck:
        return selfcheck()
    start, end = (a.start, a.end) if a.start and a.end else month_range(a.month)
    payload = fetch(a.org, start, end)
    out = sys.stdout if a.out == "-" else open(a.out, "w", encoding="utf-8-sig")
    n = to_csv(payload, out)
    if out is not sys.stdout:
        out.close()
        print(f"wrote {a.out} ({n} users, {start}..{end})", file=sys.stderr)


if __name__ == "__main__":
    main()
