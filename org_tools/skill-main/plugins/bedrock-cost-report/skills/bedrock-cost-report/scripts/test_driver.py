#!/usr/bin/env python3
"""Self-check for driver.py — run: python3 test_driver.py

Framework-free asserts covering the money paths: CSV model-column parsing,
rate lookup with NO all-Opus fallback, and the normalize-to-bill breakdown.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import driver as d

RATES = {"opus": {"in": 15, "cache_read": 1.5, "cache_write": 18.75, "out": 75},
         "sonnet": {"in": 3, "cache_read": 0.30, "cache_write": 3.75, "out": 15}}

# 1. CSV parsing groups token-type columns by model, regardless of column order.
CSV = ("employee,total_cost,call_count,session_count,"
       "input_tokens_opus,cache_read_opus,cache_write_opus,output_tokens_opus,"
       "prompt_sonnet,cache_read_sonnet,cache_write_sonnet,completion_sonnet\n"
       "me,701.24,5452,39,290000,693440000,31830000,4640000,"
       "220000,91200000,7510000,130000\n")
with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
    fh.write(CSV)
    path = fh.name
cap = d.parse_aicm_csv(path, "me")
os.unlink(path)
assert cap["total_cost"] == 701.24, cap["total_cost"]
assert set(cap["models"]) == {"opus", "sonnet"}, cap["models"]
# opus cache_read column must land in opus (not a stray bucket) and stay in M
assert abs(cap["models"]["opus"]["cache_read"] - 693.44) < 0.01, cap["models"]["opus"]
assert abs(cap["models"]["sonnet"]["out"] - 0.13) < 0.01, cap["models"]["sonnet"]

# 1b. Tab-delimited paste (Excel copy) is auto-detected, not just comma.
TSV = CSV.replace(",", "\t")
with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
    fh.write(TSV)
    tpath = fh.name
tcap = d.parse_aicm_csv(tpath, "me")
os.unlink(tpath)
assert set(tcap["models"]) == {"opus", "sonnet"}, tcap["models"]
assert tcap["total_cost"] == 701.24, tcap["total_cost"]

# 2. rate_for has NO fallback: unknown model -> None (never priced as Opus).
assert d.rate_for("claude-opus-4-8", RATES) is RATES["opus"]
assert d.rate_for("some-future-model-x", RATES) is None

# 3. breakdown normalizes list-price proxy to the actual bill; unknown -> unpriced.
models_M = dict(cap["models"])
models_M["mystery"] = {"in": 0, "cache_read": 10.0, "cache_write": 0, "out": 0}
rows, types, scale, unpriced = d.breakdown(models_M, RATES, 701.24)
assert unpriced == {"mystery"}, unpriced           # surfaced, not guessed
assert abs(sum(c for _, _, c, _ in rows) - 701.24) < 0.5, rows  # sums to bill
top = rows[0]
assert top[0] == "opus" and top[2] > 600, top      # opus dominates cost

# 4. unmangle recovers real project paths from `~/.claude/projects` dir names.
#    The mangling maps `/` and `.` to `-`, so string splitting alone turns
#    `alpha-agent-v3` into `v3`; resolution must go through the filesystem.
with tempfile.TemporaryDirectory() as tmp:
    for rel in ("home/u/WORK/alpha-agent-v3", "home/u/WORK/alpha",
                "home/u/.config/opencode", "home/u/.claude"):
        os.makedirs(os.path.join(tmp, rel))
    u = lambda n: d.unmangle(n, root=tmp)
    # longest sibling wins: `alpha-agent-v3` must not resolve to `alpha`
    assert u("-home-u-WORK-alpha-agent-v3") == f"{tmp}/home/u/WORK/alpha-agent-v3"
    assert u("-home-u-WORK-alpha") == f"{tmp}/home/u/WORK/alpha"
    # a `-` standing in for `.` survives separator stripping
    assert u("-home-u--claude") == f"{tmp}/home/u/.claude"
    assert u("-home-u--config-opencode") == f"{tmp}/home/u/.config/opencode"
    assert u("-home-u-WORK-gone") is None      # deleted dir -> caller falls back

# 5. day_chart_svg: one polyline point per day, in chronological order, and
#    the peak day's label shows its (rounded) value.
import re
chart = d.day_chart_svg({"2026-08-01": 10.0, "2026-08-03": 40.0, "2026-08-02": 25.0})
poly = re.search(r'<polyline points="([^"]+)"', chart).group(1)
assert len(poly.split()) == 3, poly        # one point per day, chronological order
assert "$40" in chart, chart               # peak (2026-08-03) value labeled
assert "2026-08-01" in chart and "2026-08-03" in chart, chart  # first/last date axis labels
assert d.day_chart_svg({}) == '<p class="note">데이터 없음</p>'

print("all self-checks passed")
