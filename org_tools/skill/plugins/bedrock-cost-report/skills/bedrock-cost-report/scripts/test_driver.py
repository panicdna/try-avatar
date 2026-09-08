#!/usr/bin/env python3
"""Self-check for driver.py -- run: python3 test_driver.py

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
line = re.search(r'<path d="(M[^"]+)" fill="none"', chart).group(1)
assert line.count(" C ") == 2, line        # 3 days -> 2 curve segments
xs = [float(x) for x in re.findall(r'([\d.]+),[\d.]+', line)]
assert xs == sorted(xs), xs                 # left to right, chronological
assert "$40" in chart, chart               # peak (2026-08-03) value labeled
assert "2026-08-01" in chart and "2026-08-03" in chart, chart  # first/last date axis labels
# A stretched viewBox squashed the labels, which is what made them unreadable.
assert "preserveAspectRatio" not in chart, "labels must not be scaled non-uniformly"
assert "<polyline" not in chart, "the series is a smooth path now"
assert d.day_chart_svg({}) == '<p class="note">데이터 없음</p>'
# A single day has no segment to curve, and must not raise.
assert d.day_chart_svg({"2026-08-01": 3.0}).count(" C ") == 0

# 6. The shipped rates.json must price generations separately. Opus 4.1 is still
#    served on Bedrock at 3x the Opus 4.5+ price and Sonnet 5 is cheaper than
#    Sonnet 4.6, so a single `opus`/`sonnet` catch-all would silently mis-price
#    real usage. Key ORDER decides which entry wins, and order is easy to break
#    by editing the file, so assert the outcome rather than the order.
REAL = d.load_rates(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rates.json"))
assert d.rate_for("opus_4_1", REAL)["in"] == 15, "Opus 4.1 must keep its 3x price"
assert d.rate_for("opus_5", REAL)["in"] == 5
assert d.rate_for("opus_4_8", REAL)["in"] == 5     # must not fall into the 4_1 entry
assert d.rate_for("sonnet_5", REAL)["in"] == 2
assert d.rate_for("sonnet_4_6", REAL)["in"] == 3   # must not fall into the sonnet_5 entry
assert d.rate_for("haiku_4_5", REAL)["in"] == 1
# cache_write is the 5-minute rate (1.25x input) and cache_read is 0.1x, the two
# multipliers the report's glossary explains. Drifting from them breaks the text.
for k in ("opus_5", "sonnet_5", "haiku_4_5"):
    r = d.rate_for(k, REAL)
    assert abs(r["cache_write"] / r["in"] - 1.25) < 1e-9, (k, r)
    assert abs(r["cache_read"] / r["in"] - 0.1) < 1e-9, (k, r)

# 6b. A CSV column suffix and a local-log model id name the same model and must
#     resolve to the same entry despite different separators.
assert d.rate_for("claude-sonnet-5-20260514", REAL) is d.rate_for("sonnet_5", REAL)
assert d.rate_for("us.anthropic.claude-opus-4-1-20250805-v1:0", REAL)["in"] == 15
assert d.rate_for("sonnet_9", REAL) is None        # unknown gen stays unpriced

# 7. family_rate resolves a family to its cheapest generation. rate_for cannot,
#    now that keys name generations -- that mismatch silently killed shift_sim.
assert d.rate_for("sonnet", REAL) is None
assert d.family_rate("sonnet", REAL)["in"] == 2
assert d.shift_sim({"opus_5": {"in": 0, "cache_read": 100.0, "cache_write": 0, "out": 0}},
                   REAL, 100.0) is not None

# 8. session_stats: miss_share is a fraction of cache_write, while miss_fast_share
#    is a fraction OF THE MISSES (the part an expiry cannot explain).
st = d.session_stats([
    {"turns": 4, "cache_read": 300, "cache_write": 100, "ctx_max": 400,
     "miss_write": 40, "miss_n": 2, "miss_fast": 30},
    {"turns": 60, "cache_read": 700, "cache_write": 100, "ctx_max": 900,
     "miss_write": 0, "miss_n": 0, "miss_fast": 0},
])
assert abs(st["miss_share"] - 0.20) < 1e-9, st["miss_share"]            # 40 / 200
assert abs(st["miss_fast_share"] - 0.75) < 1e-9, st["miss_fast_share"]  # 30 / 40
assert st["long_n"] == 1 and abs(st["long_share"] - 0.7) < 1e-9

# 9. efficiency rows are (group, label, value, meaning) and each meaning is a real
#    sentence. The VOC was that this column just repeated the number.
MM = {"opus_5": {"in": 0.1, "cache_read": 50.0, "cache_write": 4.0, "out": 1.0}}
rows = d.efficiency(cap, 701.24, {}, st, MM, REAL,
                    type_rows=[("Output", 1.0, 100.0, 14.3)])
assert rows and all(len(r) == 5 for r in rows), rows   # (group, verdict, label, value, meaning)
assert {g for g, *_ in rows} <= {d.CTX, d.YIELD}
assert all(len(m) > 40 for *_, m in rows), [m for *_, m in rows if len(m) <= 40]
# No per-active-day average: the only active-day count available comes from this
# machine's logs while the bill spans every environment, so the quotient inflates.
assert not any("활동일" in l for _, _, l, _, _ in rows), "active-day average must stay out"
# 캐시가 아껴준 금액 is always positive and just restates the reuse multiple, so it
# belongs in the glossary, not in a table that grades things.
assert not any("아껴준" in l for _, _, l, _, _ in rows)

# 9c. Ratings only where a basis exists, and the basis decides the vocabulary:
#     조직 분포(양호/보통/점검) vs 지난달 대비(개선/비슷/악화) vs 공식 10% 선.
assert d.terciles([1, 2, 3]) is None, "too few values to split"
assert d.terciles(list(range(9))) == (3, 6)
BANDS = {"reuse": (5.0, 12.0), "out_share": (10.0, 20.0)}
#     st is 1000 cache_read over 64 turns (15.6/turn) with a 70% long-session share,
#     so last month at 10/turn reads as 점검 now and at 90% reads as 양호.
PREV = dict(st, ctx_per_turn=10, long_share=0.90)
rated = d.efficiency(cap, 701.24, {"users": 30, "cost": 900.0}, st, MM, REAL,
                     type_rows=[("Output", 1.0, 100.0, 14.3)], bands=BANDS, prev=PREV)
verdict = {l: v for _, v, l, _, _ in rated}
assert verdict["컨텍스트 재사용 배수"] == d.GOOD, verdict     # 50/4 = 12.5x, top third
assert verdict["Output 비중"] == d.OK, verdict                  # 14.3%, middle third
assert verdict["캐시 미스로 다시 쓴 몫"] == d.CHECK, verdict   # 20% >= the 10% flag
# Trend rows use the SAME three words as the rest: a rising number is 점검
# (worth a look), never 악화 -- this cannot know whether the rise was justified.
assert verdict["턴당 평균 컨텍스트"] == d.CHECK, verdict
assert verdict["50턴 이상 세션 비중"] == d.GOOD, verdict
assert {v for _, v, _, _, _ in rated if v} <= {d.GOOD, d.OK, d.CHECK}, "one vocabulary only"
# 산출 대비 비용 carries no verdict at all: the docs define those metrics but
# decline to say what a good value is, so grading them would invent a standard.
assert all(v == "" for g, v, _, _, _ in rated if g == d.YIELD), rated

# 9d. rate_trend direction and the flat band.
assert d.rate_trend(80, 100) == d.GOOD           # smaller is better by default
assert d.rate_trend(120, 100) == d.CHECK
assert d.rate_trend(105, 100) == d.OK            # within +-10%
assert d.rate_trend(120, 100, lower_is_better=False) == d.GOOD
assert d.rate_trend(100, 0) == "", "no previous month -> no verdict"
assert d.prev_month("2026-01") == "2025-12" and d.prev_month("2026-08") == "2026-07"

# 9e. org_bands reduces the org's rows to cut points only -- no per-person figures.
users = [{"cacheReadTokens": 10 * i, "cacheWriteTokens": 1,
          "modelDetails": {"opus_5": {"inputTokens": 1, "outputTokens": i,
                                      "cacheReadTokens": 1, "cacheWriteTokens": 1}}}
         for i in range(1, 13)]
b = d.org_bands(users, REAL)
assert set(b) <= {"reuse", "out_share"} and b["reuse"][0] < b["reuse"][1], b
assert all(isinstance(x, float) for cuts in b.values() for x in cuts), b

# 9a2. The glossary diagram's CW/CR brackets must encode the corrected timing:
#      a turn's own Output is never bracketed as CW in that same turn -- only the
#      NEXT turn's [prev Output + this Input] delta is. And a turn's CR bracket
#      must equal the PREVIOUS turn's whole bar (that whole prefix is what got
#      cache-written last time), not just its input. Hand-tuned widths that lose
#      either identity would quietly re-teach the wrong billing model.
diag = d.context_diagram()
paths = re.findall(r'<path d="M([\d.]+),[\d.]+ L[\d.]+,[\d.]+ L([\d.]+),[\d.]+ L[\d.]+,[\d.]+" '
                    r'fill="none" stroke="([^"]+)"', diag)
by_color = {}
for b0, b1, color in paths:
    by_color.setdefault(color, []).append(float(b1) - float(b0))
cw = sorted(by_color[d.TOK_COLOR["cache_write"]])
cr = sorted(by_color[d.TOK_COLOR["cache_read"]])
assert len(cw) == 3 and len(cr) == 2, (cw, cr)      # every turn writes; only turns 2-3 read
assert cw[1] == cw[2], cw                # turn 2 and turn 3 write the same-shaped delta
assert cr[0] == cw[0], (cr, cw)          # turn 2's read == turn 1's whole (write-only) bar
assert cr[1] > cr[0] + cw[0], (cr, cw)   # turn 3's read grew past turn 1 -- cache keeps accumulating
# The right-hand "Cached Prefix" column marks exactly 2 segments as newly-added
# (this turn's CW delta) per turn, never a turn's own just-generated Output.
assert diag.count(f'stroke="{d.TOK_COLOR["cache_write"]}" stroke-width="1.3"') == 6
assert all(t in diag for t in ("Base", "Input 1", "Output 1", "Input 2", "Output 2", "Input 3",
                                "Output 3", "Cache Read", "Cache Write", "Cached Prefix"))

# 9a3. A user with only short sessions must not read "50턴을 넘긴 세션 0개가 문맥
#      비용의 0%를 씁니다" -- verified by generating that exact case, not assumed.
short = d.session_stats([{"turns": 6, "cache_read": 300, "cache_write": 100,
                          "ctx_max": 400, "miss_write": 0, "miss_n": 0, "miss_fast": 0}])
srows = d.efficiency({}, 10.0, {}, short, MM, REAL,
                     type_rows=[("Output", 1.0, 100.0, 14.3)])
long_row = next(m for _, _, l, _, m in srows if l == "50턴 이상 세션 비중")
assert "0개" not in long_row and "없습니다" in long_row, long_row
# Rows judged against the org say so when the org data is absent, instead of
# leaving a bare dash the reader cannot act on.
reuse_row = next(m for _, _, l, _, m in srows if l == "컨텍스트 재사용 배수")
assert "--fetch" in reuse_row, reuse_row

# 9b. Benchmarks ride on the day chart as reference lines instead. A line above
#     the peak is dropped, not clamped to the top edge where it would misread as
#     "you are at the benchmark".
c = d.day_chart_svg({"2026-08-01": 5.0, "2026-08-02": 20.0},
                    refs=((13, "공식 평균"), (30, "상위 10%")))
assert c.count("stroke-dasharray") == 1, "only the in-range line is drawn"
assert "공식 평균" in c and "상위 10%" not in c, c
assert d.day_chart_svg({"2026-08-01": 5.0}, refs=((13, "x"),)).count("stroke-dasharray") == 0

# 10. Glossary and playbook carry attribution as TEXT: the corp network reaches
#     neither docs host, so a real <a> would render as a broken link.
gl = d.glossary_html([("Cache Read", 50.0, 400.0, 55.0), ("Cache Write", 4.0, 250.0, 34.0)],
                     MM, REAL, 730.0)
assert "12.5" in gl, "write:read price ratio must be shown"
pb = d.playbook_html(st, {"2.1.224": [40, 100]})
assert "<a " not in gl + pb, "no live links -- corp network cannot reach the docs"
assert "code.claude.com/docs/en/costs" in pb, "URLs still listed once, as text"
assert "2.1.224" in pb, "version breakdown surfaces where misses concentrated"
# The quotes are frozen at a point in time while the docs keep changing, so the
# as-of date must reach the reader. It is hardcoded, never today() -- a run date
# would assert freshness the wording hasn't earned.
assert d.DOCS_ASOF in pb, "citation as-of date must appear with the sources"
assert "today" not in d.DOCS_ASOF and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.DOCS_ASOF)

# 11. 전월 대비 delta: direction only, same +/-10% flat band as rate_trend, but
#     NEVER a 판정 word -- there's no published basis for whether more cost,
#     calls, sessions, or commits is "good".
assert d._pct_change(150, 100) == (50.0, "up")
assert d._pct_change(80, 100) == (-20.0, "down")
assert d._pct_change(104, 100)[1] == "flat"          # inside +-10%
assert d._pct_change(100, 0) == (None, None), "no previous value -> no delta at all"
assert d._pct_change(0, 100) == (None, None), "a zero current value is not a real delta either"
dh = d.delta_html(150, 100)
assert "&#9650;" in dh and "50%" in dh and "d-up" in dh, dh   # up arrow, as an entity
assert "&#9660;" in d.delta_html(80, 100) and "d-down" in d.delta_html(80, 100)
assert "비슷" in d.delta_html(104, 100)
assert d.delta_html(150, 0) == "", "nothing to compare against -> no chip at all"
assert "GOOD" not in dh.upper() and d.GOOD not in dh and d.CHECK not in dh, \
    "must never carry a grade word -- only direction"

print("all self-checks passed")
