---
name: bedrock-cost-report
description: Generate a monthly Claude Code / AWS Bedrock cost report as a self-contained HTML file. Fetches the user's own usage automatically from the DS Bedrock dashboard API (no input needed), or takes a pasted AICM CSV row / billed total. Use when the user asks to break down their Claude Code cost by model / project / task and get cost-saving insights. Triggers - "내 비용 리포트", "월별 비용 보고서", "bedrock 비용 정리", "이번 달 클로드 비용", "cost report", "토큰 사용 정리", "비용 인사이트", "AICM csv".
license: Proprietary - Samsung DS internal use only
compatibility: requires corp-network access to exactly one host, aws-bedrock.codehub.samsungds.net (read-only GET, no request body, no external destinations). Runs on Python 3.10+ stdlib only, no third-party packages. Works fully offline with --csv or --cost. The report cites Anthropic docs as plain text, so it needs no internet to read.
---

# Monthly Bedrock Cost Report

Turns a month's **actual billed Bedrock cost** into a self-contained HTML report:
cost by model, by token-type, by project, and by day, plus **efficiency metrics**
in two groups -- 컨텍스트 효율 (context reuse multiple, cache saving, output share,
context per turn, observed cache misses, long-session share) and 산출 대비 비용
($/session, $/call, $/commit, $/PR, $/1k lines, $/CLI-hour, org comparison,
model-shift simulation) -- then 진단->메커니즘->처방 insights.

Anthropic's published enterprise averages ($13/active day, 90% under $30, $150-250
/month) are drawn as **dashed reference lines on the by-day chart**, not as a
metric row. A per-day average would need an active-day count, and the only one
available is this machine's log dates while the bill covers every environment --
a denominator narrower than its numerator, which inflates the quotient. The daily
series is already plotted, so the comparison belongs there.

Every metric's 의미 column is a full sentence: what it measures, how to read it,
and where it misleads. Two folded sections carry the explanation the readers asked
for: a **용어 사전** for `input`/`cache_write`/`cache_read`/`output` (why the token
type with 22x fewer tokens can cost more), and a **절감 플레이북** where every item
is a documented Anthropic recommendation with its source page named. Methodology
sits in a folded `<details>` at the bottom.

### The playbook reads nothing at runtime

Every quote is a string literal in `driver.py`. The `llms-full.txt` dumps were
read **once, by hand, while writing those strings** -- report generation never
opens them, so the skill works from a plain install with no docs on disk and no
internet. That is also why the quotes are frozen in time, and why `DOCS_ASOF`
exists.

### The 판정 column: three words, and never a made-up threshold

`양호 / 보통 / 점검`, one vocabulary for every row. What differs is the basis, and
each row's 의미 cell names its own:

| Basis | Rows | Where it comes from |
|---|---|---|
| Official line | 캐시 미스로 다시 쓴 몫 | `/usage` raises its cache-miss flag at 10% |
| Org distribution | 컨텍스트 재사용 배수, 산출물 몫 | terciles of the org's own rows, computed in `org_bands()` |
| Last month | 턴당 평균 컨텍스트, 50턴 이상 세션 비중 | `rate_trend()`; both figures print in the value cell |

Two rules hold this together. **Do not invent cut points** -- an earlier draft
graded these with numbers like "60k 미만 양호" that had no published or measured
source, and labelling them "자체 기준" only disclosed the invention rather than
fixing it. **A trend is not a grade**: a metric that rose reads as 점검 (worth a
look), never 악화, because whether the rise was justified depends on what the
month was spent on. `산출 대비 비용` carries no 판정 column at all, since the docs
define those metrics but decline to say what a good value is.

`org_bands()` reduces the org's rows to two cut points before anything is kept, so
no individual's figures reach the report.

### The lead summary and 전월 대비 chips carry a direction, never a grade

The top cards (실청구액,호출,세션,커밋) and the 3-4 line summary above the tables
show a 전월 대비 delta (`_pct_change`/`delta_html`), styled like a stock ticker
(빨강 상승, 파랑 하락). This is the same +/-10% flat band `rate_trend()` uses, on
purpose -- but it must never be upgraded to a 양호/보통/점검 pill. There is no
published or measured basis for whether more cost, more calls, more sessions,
or more commits is "good" -- exactly the reason `산출 대비 비용` already carries
no 판정 column. If you're tempted to color-code these as good/bad, don't; that
would be the same invented cut point the 판정 rubric above forbids, just moved
into a chip.

Default comparison window is the **full previous month** against however much
of the current month has landed so far -- deliberately not day-capped. The
question this answers is pacing ("has this month already passed all of last
month?"), which is what a cost report needs; a same-length-window comparison
would answer a different question (rate of change) that nobody asked for here.
`--compare-start`/`--compare-end` (both required together, `--fetch` only)
override the window when the user names a specific different period -- pass
them straight through rather than asking first. Only use AskUserQuestion if
the user's ask is ambiguous about *which* different period they want (e.g.
"다른 기간으로도 보고 싶어" with nothing more specific); don't ask when they
haven't mentioned a comparison at all -- the default already answers that.

### Refreshing the quotes when the docs change

`driver.py` holds `DOCS_ASOF` -- the date the quoted wording was last read out of
the official docs. It is **hardcoded on purpose**; using `today()` would claim a
freshness the text hasn't earned. The date is printed twice in every report (the
always-visible footer and the sources block) so a reader can judge how stale the
guidance might be, and `test_driver.py` asserts it reaches the output.

To re-verify: on an external machine fetch `docs.claude.com/llms-full.txt` and
`code.claude.com/llms-full.txt` (whole-site markdown dumps, tens of MB -- they are
`.gitignore`d and must never be committed), re-read the pages listed in
`DOCS_ALL`, correct any wording that changed, then bump `DOCS_ASOF` and the
plugin `version`. Also re-check `rates.json` against the Pricing page while there.
Bump the date **only** after actually re-reading -- a stale quote with a fresh date
is worse than an honestly old one.

> **Citations are plain text, never links.** The corp network reaches neither
> `code.claude.com` nor `platform.claude.com`, so a real `<a>` renders as a broken
> report. Inline citations name the page; the full URLs are listed once at the end
> of the playbook for anyone checking from an external machine. `test_driver.py`
> asserts no `<a ` tag ever appears in those sections. Nothing here is inferred --
> if the official docs don't say it, it isn't in the playbook (which is why
> "which model for which task" beyond Sonnet-vs-Opus is absent).

## Run the driver. Do not write the report yourself.

**Every word the reader sees is a string literal in `driver.py`.** Generating a
report means running that script and reporting where the file landed. Do not
re-word the metric explanations, rewrite an insight, hand-author HTML, or "improve"
a sentence for one run -- the wording was reviewed against real users' feedback,
and a per-run rewrite silently gives one person a different report from everyone
else. If a phrase is genuinely wrong, fix it **in `driver.py`**, bump the plugin
`version`, and let every future run inherit the fix.

The same applies to numbers: the driver decides which rows and cards appear and
what verdict each gets. Don't add commentary that contradicts it, and don't fill
in a verdict the driver deliberately left blank.

### When you DO edit the Korean copy

Readers have said twice that this report's Korean read machine-written. Run any
copy you change past these before committing -- they are the tells that actually
showed up here, not a general style guide:

- **Em dashes.** Korean prose uses far fewer than English. A comma or a full stop
  is almost always better. Target zero in the insight cards.
- **Sentences carrying three clauses.** Split them. Two short sentences beat one
  hinged on `~니, ~라서, ~이므로`.
- **Uniform endings.** A run of `~입니다 / ~입니다 / ~입니다` reads like a
  template. Vary the shape, not the politeness level.
- **Connective filler.** `그래서 / 다만 / 따라서 / 즉` are usually deletable with
  no loss.
- **Over-helpful tails.** `~라고 보시면 됩니다`, `~해 보시면 좋습니다` add length
  and no information.
- **Saying it twice.** If a sentence restates the previous one in other words,
  cut one.
- **Register drift.** The whole report is 경어체. A stray `~한다` stands out.
- **Claims that fight the number.** "이 비중은 원래 낮습니다" breaks on the user
  whose value is high. Describe the tendency, don't assert the value.

If the `humanize-korean` plugin is installed, its `humanize-diagnostician` agent
does this pass properly -- point it at the copy and fix what it names. Do NOT wire
it into report generation: the copy is static, so there is nothing to humanize at
runtime, and a per-run rewrite is exactly what the section above forbids.

Driver: `scripts/driver.py` (Python 3.10+ stdlib only).
Rates: `scripts/rates.json` (user-maintained).

> Script paths below (`scripts/driver.py` etc.) are relative to **this skill's
> own directory** -- when this skill loads, use its actual on-disk path (shown
> in the tool/skill context) for the script, e.g.
> `python3 /path/to/finops/skills/bedrock-cost-report/scripts/driver.py`.
> Run it with your shell's **cwd set to the target project repo** (the one
> whose cost/tasks you're reporting on) -- that's where `git log` runs for day
> themes, and where the HTML lands (**cwd, no subdirectory**).

## Network access (declared)

All outbound traffic is `urllib.request.urlopen` in `scripts/fetch_usage.py:_get()`
-- the single choke point every request goes through. Allowed destination, one host:

| | |
|---|---|
| Host | `https://aws-bedrock.codehub.samsungds.net` (corp-internal DS dashboard) |
| Endpoints | `GET /api/budget-org/users`, `/api/budget-org/summary`, `/api/budget-org/info` |
| Method | `GET` only -- no request body, so **nothing is transmitted outward** except the query string (`budgetOrgId`, date range, `detail`) |
| Credentials | none sent; the API requires no auth on the corp network |
| Data flow | inbound only. The response is parsed in memory, the caller's own row is kept, the rest is discarded, and only the local HTML report is written to disk |
| Third-party | none. `urllib` from the stdlib; no packages, no telemetry, no external analytics |

`--csv` and `--cost` make no network calls at all, so the skill is usable with
networking blocked entirely. `driver.py` never opens a socket itself -- it imports
`fetch_usage` only on the `--fetch` path.

## Inputs

0. **`--fetch` (preferred) -- 입력 0개.** The dashboard's data comes from its own
   JSON API (`/api/budget-org/users?budgetOrgId=...&start=...&end=...&detail=full`,
   same-origin, no auth on the corp network). Bare `--fetch` resolves **본인**
   knoxId and keeps only that row -- no id, no CSV download, no paste:

   ```bash
   python3 scripts/driver.py --fetch              # 이번 달 (month-to-date)
   python3 scripts/driver.py --fetch --month 2026-07
   ```

   `--month`는 생략하면 **이번 달**(오늘까지). 사용자가 다른 달을 말하면 그때만 지정.

   본인 식별 순서: `$BEDROCK_KNOX_ID` -> `git config user.email`의 @ 앞부분.
   API의 `knoxId`/`emailLower`와 매칭한다. 둘 다 없으면 exit 2로 알려주고,
   조직에 행이 없으면 exit 1 (첫 행으로 조용히 대체하지 않음).

   **팀원에게 공유할 때**: 이 플러그인만 설치하면 각자 `--fetch`로 자기 리포트가
   나온다. 준비물은 `git config user.email`(사내 메일)뿐. 기본 조직은
   **S/W혁신팀(S.LSI)** (`budgetOrgId=20017947`) -- 수동 등록이 필요한 그룹이 아니라
   조직 기준이므로 팀원이 자동으로 포함된다. knoxId가 메일과 다르면
   `export BEDROCK_KNOX_ID=<knoxId>`. 다른 조직으로 확장할 때는
   `export BEDROCK_ORG_ID=<budgetOrgId>` 또는 `--org` -- 그 값은 대상 조직의
   `/budget-org?budgetOrgId=...` 링크에서 가져온다 (조직 목록 API는 없음).

   **`--fetch`는 id를 받지 않는다 -- 본인 전용이다.** 프로젝트/날짜/세션 표는 이
   머신의 `~/.claude/projects`에서 나오고 거기엔 남의 로그가 없다. 남을 지정하면
   *그 사람의 청구액*과 *내 작업 이력*이 한 리포트에 섞여 잘못 읽히므로 아예
   막았다. knoxId가 git 메일과 다르면 `BEDROCK_KNOX_ID`로 지정할 것.

   조직 전원 CSV만 필요하면: `scripts/fetch_usage.py --month 2026-08 [--out f.csv]`.
   Self-check: `python3 scripts/fetch_usage.py --selfcheck`.
   나중에 401/redirect가 나면 (인증 추가) 아래 paste 경로로 폴백.

   > **범위 주의.** 이 API에는 인증이 없다 -- budgetOrgId를 아는 사람은 누구나 그
   > 조직 전체를 조회할 수 있고, 한 번 요청에 조직 전원(현재 314명)의 행이 내려온다.
   > driver.py는 **호출자 자신의 행만 남기고 나머지를 버리며**, 리포트에는 조직
   > 집계값(인원 수,총액,1인 평균)만 실린다. 그래도 이 스킬은 **팀 내부 공유 전용**
   > 이라는 전제로 만들어졌다 -- 배포 범위를 넓힐 때는 기본 org id를 코드에서 빼고
   > `BEDROCK_ORG_ID` 필수로 돌리는 것을 먼저 검토할 것.

1. **AICM row, pasted** -- fallback when auto-fetch is unavailable. Corp exports are
   DRM-locked and often unreadable from disk, so the user **pastes the header +
   their data row** into the chat. Excel copy = tab-delimited, CSV = comma; the
   parser auto-detects the delimiter. You save the paste to a temp file (or pipe
   it) and run with `--csv`. It carries `total_cost`, `call_count`,
   `session_count`, `commit`, and per-model token columns -- no screenshot
   transcription. Pass `--employee <id>` if multiple users are pasted.
2. **`--month YYYY-MM`** -- target month, **defaults to this month** (month-to-date).
   Past month -> full-month row; current month -> up to today.
3. **No AICM data?** Pass `--cost <USD>` instead. The model/project/day breakdown
   then comes from local logs only (labeled 근사) -- still weighted by each
   message's real model, never assumed all-Opus.

### Handling the paste

The user pastes text; you turn it into `--csv` input one of two ways:

```bash
# (a) write the paste to a temp file, then point --csv at it
cat > /tmp/aicm.tsv <<'EOF'
<paste: header line, then the user's data row>
EOF
python3 scripts/driver.py --month 2026-08 --csv /tmp/aicm.tsv --employee <id>

# (b) or pipe straight in via stdin ( --csv - )
python3 scripts/driver.py --month 2026-08 --csv - --employee <id> <<'EOF'
<paste>
EOF
```

> **[!] Excel range-copy pastes as an IMAGE, not text.** Selecting cells in Excel
> and pasting into the chat puts a screenshot on the clipboard, so it arrives as
> an image (garbled/truncated column names via OCR) -- not usable as CSV. Ask the
> user to instead **open the CSV in a text editor (Notepad/VS Code) and copy the
> header line + their row as plain text**, which comes through as tab/comma text.
> If they can only give an image, read the values off it and **echo them back for
> confirmation before running** -- don't trust OCR of many columns silently.

## Rates: config, not code -- and the ratios are NOT stable across generations

`rates.json` maps a model-name **substring** -> per-1M rates
(`in`/`cache_read`/`cache_write`/`out`). Nothing is hardcoded in the driver.
"User-maintained" = a human edits this small JSON when a new model appears or
the contract price changes.

> **An earlier version of this file claimed absolute prices didn't matter because
> "only ratios matter, and those are stable (Opus:Sonnet:Haiku ~= 25:5:1)". That
> was wrong and it corrupted the report.** The file was carrying Opus 4.1 prices
> ($15/$75) while actual usage was Opus 4.8/5 ($5/$25), so opus:sonnet computed
> as 5:1 instead of 2.5:1. Consequences: opus's cost share was overstated, the
> "opus -> sonnet" saving was inflated (-53% vs the true -37%), and the report
> asserted a 65% contract discount that does not exist.

Rules that follow from that:

- **Per-generation keys, no family catch-all.** `opus` as a single key silently
  prices Opus 4.1 -- which is **still served on Bedrock** at 3x -- the same as
  Opus 5. `sonnet_5` ($2) and `sonnet_4_6` ($3) differ too. Add one entry per
  generation you actually use.
- **Key order decides matching.** `rate_for()` returns the *first* key that is a
  substring of the model name, so specific keys must precede broader ones.
  `test_driver.py` asserts the resulting prices rather than the order, so
  reordering the file breaks the test loudly instead of the report quietly.
- **Matching ignores separators.** Both sides are reduced to alphanumerics, so
  one key `sonnet_5` matches the CSV suffix `sonnet_5` and the local-log id
  `claude-sonnet-5-20260514`.
- **`scale` is the verification signal.** The report prints "실단가 ~= 정가의 N%".
  The DS dashboard computes cost from **official list rates**, so a correct
  `rates.json` yields **N = 100%**. Far from 100 means the table is stale (or the
  contract genuinely differs) -- fix the table before trusting the model split.
  Verified 2026-08: `scale = 1.0000` against $816.91 of real usage.
- **cache_write here is the 5-minute TTL rate** (1.25x input; 1-hour is 2x). The
  dashboard prices writes at the 5-minute rate regardless, which is why
  `scale` hits exactly 1.0. If `ENABLE_PROMPT_CACHING_1H=1` is set, AWS may bill
  more than the dashboard shows for those writes.
- **An unpriced model is surfaced, never guessed.** It appears in a red
  "단가 미등록 모델" box and is excluded from the split. Add an entry, re-run.

**If the AICM CSV already has per-model cost columns** (e.g. `cost_opus`), rates
aren't needed for the model split at all -- prefer those. Check the header; if
present, use them directly and treat `rates.json` as fallback only.

## Why token weighting (not raw proportion)

Cache-read is the bulk of tokens but ~1/50 the price. Splitting cost by raw token
count is wrong. The driver weights each token type by its model's rate to get a
"cost proxy", then normalizes the proxy sum to the actual billed total. Two
normalizations, both summing to the bill: `scale_model` for the authoritative
model/type tables, `scale_local` for the project/day tables.

## Run (agent path)

Default -- auto-fetch the user's own row for this month:

```bash
python3 scripts/driver.py --fetch
```

With a pasted AICM CSV (fallback; authoritative model/type breakdown):

```bash
python3 scripts/driver.py \
  --month 2026-08 --csv /path/aicm-export.csv --employee jibin.sung
```

Without CSV (local-log estimate; needs the billed total):

```bash
python3 scripts/driver.py --month 2026-08 --cost 701.24
```

Default output: `./<month>-bedrock-cost-report.html` -- **현재 디렉토리**, 하위 폴더를
만들지 않는다. 다른 위치는 `--out <path>`. Open on WSL with `explorer.exe <path>`.

## Self-check

```bash
python3 scripts/test_driver.py   # -> all self-checks passed
```

Covers CSV model-column grouping, the no-fallback rate lookup, the
normalize-to-bill math, `unmangle()` path recovery, and the day chart. Added with
the metrics rework: per-generation rate prices (so a `sonnet`/`opus` catch-all
can't creep back in), the 1.25x/0.1x cache multipliers the 용어 사전 text depends
on, separator-insensitive matching, `family_rate` (the lookup mismatch that
silently returned `None` from `shift_sim`), the miss-share vs miss-fast-share
denominators, that every 의미 string is a real sentence, and that the glossary and
playbook contain no `<a ` tag.

Written for Python 3.10+ (verified on 3.10.19); stdlib only. Avoid nesting
same-type quotes inside f-string replacement fields -- that is a syntax error
before 3.12, which is why the playbook keeps its English quotes in plain string
literals.

## If the CSV columns don't parse

The parser detects token-type columns by keyword (`input`/`prompt`,
`output`/`completion`, `cache_read`, `cache_write`/`cache_creation`) and takes
the remaining non-generic word(s) as the model key -- order-independent, so
`input_tokens_opus` and `opus_input_tokens` both work. If AICM uses different
column names, adjust `COLPATS` / `GENERIC` at the top of the CSV section in
`scripts/driver.py`. When in doubt, **ask the user to paste the CSV header line** and
confirm which columns map to which token type before trusting the output.

## Gotchas

- **Local logs != AICM totals.** `~/.claude/projects` on one machine is a *partial*
  record: session resume/fork copies a message across files (inflates raw counts
  ~2x), and sessions from other machines/environments are missing entirely (e.g.
  Sonnet usage may not appear locally at all). So model/token-type/total come from
  the CSV (authoritative), and local logs drive only the *relative* project/day
  split. The report badges which is which (`AICM 기준` vs `로컬 로그 근사`).
- **Effective rate ~= 100% of list -- there is no contract discount.** The DS
  dashboard prices usage with Anthropic's official list rates, so a correct
  `rates.json` makes `scale` land on 1.00. A number far from 1.00 means the rate
  table is stale, not that the contract is cheap. (With `--cost` and no CSV, local
  token inflation drags it below 1.00; that case is labeled 근사.)
- **Observed cache misses are a floor, and the cause matters more than the size.**
  A turn with `cache_read == 0` that still writes cache re-established the whole
  prefix, so those tokens were paid twice. First turns and sidechain (subagent)
  turns are excluded -- a subagent's opening write is the documented price of
  delegation, not waste. The looser test `cache_write > cache_read` gives a higher
  number but conflates a miss with a turn that legitimately added a lot of new
  content, so the report uses the strict one. `miss_fast_share` is the portion
  following a sub-5-minute gap, which **no cache TTL can explain** -- that part
  points at an invalidation (tool definitions, mid-session MCP connect,
  thinking/effort change, model switch). Because several Claude Code releases
  carried prompt-cache bugs that did exactly this, the playbook also breaks misses
  down by `version`; that correlation is confounded with usage habits over the
  same period and is presented as a prompt to upgrade, not a proven cause.
- **Don't infer a TTL from settings.** `ENABLE_PROMPT_CACHING_1H` can change
  mid-month, and settings files keep no history, so thresholding on the *current*
  value mislabels earlier days. That is why misses are observed from the logs
  rather than derived from a configured TTL.
- **Top-level day chart = all projects, flow only.** The overall "날짜별 비용"
  section is a trend chart (no per-day table), covering every project's cost
  by day. Expand a project row under "프로젝트별 비용" for its own exact
  day-by-day cost **and its own `git log`** (resolved via `unmangle()` from
  the `~/.claude/projects` dir name to that project's real path) -- themes
  never mix across projects, and a project without a resolvable git repo just
  shows cost with no theme.
- **Efficiency metrics degrade gracefully.** Each row is skipped when its input is
  missing rather than printing a zero: the org comparison needs `--fetch` (it calls
  `/api/budget-org/summary` + `/info` for aggregates and the org name only), and the session
  metrics need local logs. `--csv`-only runs simply show fewer rows.
- **`cache_read` vs `cache_write` are different levers** -- don't merge them in
  prose. Write = paid once when content enters the context; read = paid again every
  later turn. That distinction is what makes the insight actionable.
- **Output lands in cwd** as `<month>-bedrock-cost-report.html`; pass `--out` to
  put it elsewhere. Reporting inside a git repo leaves an untracked HTML file --
  tell the user where it is so they can move or ignore it.

## Troubleshooting

- `No local logs for <month> and no --csv` -- no local records for that month on
  this machine and no CSV. Provide `--csv`, or run on the machine with the logs.
- `Need a billed total` -- pass `--csv` (with a `total_cost` column) or `--cost`.
- Model row shows a weird key like `unknown` -- a token column's model suffix
  wasn't recognized; check the CSV header and adjust `GENERIC`/`COLPATS`.
