---
name: bedrock-cost-report
description: Generate a monthly Claude Code / AWS Bedrock cost report as a self-contained HTML file. Fetches the user's own usage automatically from the DS Bedrock dashboard API (no input needed), or takes a pasted AICM CSV row / billed total. Use when the user asks to break down their Claude Code cost by model / project / task and get cost-saving insights. Triggers - "내 비용 리포트", "월별 비용 보고서", "bedrock 비용 정리", "이번 달 클로드 비용", "cost report", "토큰 사용 정리", "비용 인사이트", "AICM csv".
license: Proprietary - Samsung DS internal use only
compatibility: requires corp-network access to exactly one host, aws-bedrock.codehub.samsungds.net (read-only GET, no request body, no external destinations). Runs on Python 3.11+ stdlib only, no third-party packages. Works fully offline with --csv or --cost.
---

# Monthly Bedrock Cost Report

Turns a month's **actual billed Bedrock cost** into a self-contained HTML report:
cost by model, by token-type, by project, and by day, plus **efficiency metrics**
(cache_read:output, $/CLI-hour, $/commit, org-average comparison, model-shift
simulation, session hygiene) and 진단→메커니즘→처방 insights. Methodology sits in a
folded `<details>` at the bottom.

Driver: `scripts/driver.py` (Python 3.11 stdlib only).
Rates: `scripts/rates.json` (user-maintained).

> Script paths below (`scripts/driver.py` etc.) are relative to **this skill's
> own directory** — when this skill loads, use its actual on-disk path (shown
> in the tool/skill context) for the script, e.g.
> `python3 /path/to/finops/skills/bedrock-cost-report/scripts/driver.py`.
> Run it with your shell's **cwd set to the target project repo** (the one
> whose cost/tasks you're reporting on) — that's where `git log` runs for day
> themes, and where the HTML lands (**cwd, no subdirectory**).

## Network access (declared)

All outbound traffic is `urllib.request.urlopen` in `scripts/fetch_usage.py:_get()`
— the single choke point every request goes through. Allowed destination, one host:

| | |
|---|---|
| Host | `https://aws-bedrock.codehub.samsungds.net` (corp-internal DS dashboard) |
| Endpoints | `GET /api/budget-org/users`, `/api/budget-org/summary`, `/api/budget-org/info` |
| Method | `GET` only — no request body, so **nothing is transmitted outward** except the query string (`budgetOrgId`, date range, `detail`) |
| Credentials | none sent; the API requires no auth on the corp network |
| Data flow | inbound only. The response is parsed in memory, the caller's own row is kept, the rest is discarded, and only the local HTML report is written to disk |
| Third-party | none. `urllib` from the stdlib; no packages, no telemetry, no external analytics |

`--csv` and `--cost` make no network calls at all, so the skill is usable with
networking blocked entirely. `driver.py` never opens a socket itself — it imports
`fetch_usage` only on the `--fetch` path.

## Inputs

0. **`--fetch` (preferred) — 입력 0개.** The dashboard's data comes from its own
   JSON API (`/api/budget-org/users?budgetOrgId=…&start=…&end=…&detail=full`,
   same-origin, no auth on the corp network). Bare `--fetch` resolves **본인**
   knoxId and keeps only that row — no id, no CSV download, no paste:

   ```bash
   python3 scripts/driver.py --fetch              # 이번 달 (month-to-date)
   python3 scripts/driver.py --fetch --month 2026-07
   ```

   `--month`는 생략하면 **이번 달**(오늘까지). 사용자가 다른 달을 말하면 그때만 지정.

   본인 식별 순서: `$BEDROCK_KNOX_ID` → `git config user.email`의 @ 앞부분.
   API의 `knoxId`/`emailLower`와 매칭한다. 둘 다 없으면 exit 2로 알려주고,
   조직에 행이 없으면 exit 1 (첫 행으로 조용히 대체하지 않음).

   **팀원에게 공유할 때**: 이 플러그인만 설치하면 각자 `--fetch`로 자기 리포트가
   나온다. 준비물은 `git config user.email`(사내 메일)뿐. 기본 조직은
   **S/W혁신팀(S.LSI)** (`budgetOrgId=20017947`) — 수동 등록이 필요한 그룹이 아니라
   조직 기준이므로 팀원이 자동으로 포함된다. knoxId가 메일과 다르면
   `export BEDROCK_KNOX_ID=<knoxId>`. 다른 조직으로 확장할 때는
   `export BEDROCK_ORG_ID=<budgetOrgId>` 또는 `--org` — 그 값은 대상 조직의
   `/budget-org?budgetOrgId=…` 링크에서 가져온다 (조직 목록 API는 없음).

   **`--fetch`는 id를 받지 않는다 — 본인 전용이다.** 프로젝트/날짜/세션 표는 이
   머신의 `~/.claude/projects`에서 나오고 거기엔 남의 로그가 없다. 남을 지정하면
   *그 사람의 청구액*과 *내 작업 이력*이 한 리포트에 섞여 잘못 읽히므로 아예
   막았다. knoxId가 git 메일과 다르면 `BEDROCK_KNOX_ID`로 지정할 것.

   조직 전원 CSV만 필요하면: `scripts/fetch_usage.py --month 2026-08 [--out f.csv]`.
   Self-check: `python3 scripts/fetch_usage.py --selfcheck`.
   나중에 401/redirect가 나면 (인증 추가) 아래 paste 경로로 폴백.

   > **범위 주의.** 이 API에는 인증이 없다 — budgetOrgId를 아는 사람은 누구나 그
   > 조직 전체를 조회할 수 있고, 한 번 요청에 조직 전원(현재 314명)의 행이 내려온다.
   > driver.py는 **호출자 자신의 행만 남기고 나머지를 버리며**, 리포트에는 조직
   > 집계값(인원 수·총액·1인 평균)만 실린다. 그래도 이 스킬은 **팀 내부 공유 전용**
   > 이라는 전제로 만들어졌다 — 배포 범위를 넓힐 때는 기본 org id를 코드에서 빼고
   > `BEDROCK_ORG_ID` 필수로 돌리는 것을 먼저 검토할 것.

1. **AICM row, pasted** — fallback when auto-fetch is unavailable. Corp exports are
   DRM-locked and often unreadable from disk, so the user **pastes the header +
   their data row** into the chat. Excel copy = tab-delimited, CSV = comma; the
   parser auto-detects the delimiter. You save the paste to a temp file (or pipe
   it) and run with `--csv`. It carries `total_cost`, `call_count`,
   `session_count`, `commit`, and per-model token columns — no screenshot
   transcription. Pass `--employee <id>` if multiple users are pasted.
2. **`--month YYYY-MM`** — target month, **defaults to this month** (month-to-date).
   Past month → full-month row; current month → up to today.
3. **No AICM data?** Pass `--cost <USD>` instead. The model/project/day breakdown
   then comes from local logs only (labeled 근사) — still weighted by each
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

> **⚠️ Excel range-copy pastes as an IMAGE, not text.** Selecting cells in Excel
> and pasting into the chat puts a screenshot on the clipboard, so it arrives as
> an image (garbled/truncated column names via OCR) — not usable as CSV. Ask the
> user to instead **open the CSV in a text editor (Notepad/VS Code) and copy the
> header line + their row as plain text**, which comes through as tab/comma text.
> If they can only give an image, read the values off it and **echo them back for
> confirmation before running** — don't trust OCR of many columns silently.

## Rates: config, not code — and only ratios matter

`rates.json` maps a model-name **substring** → per-1M rates
(`in`/`cache_read`/`cache_write`/`out`). Nothing is hardcoded in the driver.
"User-maintained" = a human edits this small JSON when a new model appears or
the contract price changes. Concretely:

- **Absolute prices need not be exact.** The report divides the CSV's fixed
  `total_cost`; rates only set *how* it's split. So only the *ratios* between
  models (Opus:Sonnet:Haiku ≈ 25:5:1) matter, and those are stable — you rarely
  touch this file.
- **You only edit it when a new model shows up.** The report tells you exactly
  when: an unpriced model appears in a red "단가 미등록 모델" box (excluded from
  the split, never guessed as Opus). Add one entry, re-run.
- Matching is substring, case-insensitive (`opus` matches `claude-opus-4-8` and
  the CSV column suffix `opus`).

**If the AICM CSV already has per-model cost columns** (e.g. `cost_opus`), rates
aren't needed for the model split at all — prefer those. Check the header; if
present, use them directly and treat `rates.json` as fallback only.

## Why token weighting (not raw proportion)

Cache-read is the bulk of tokens but ~1/50 the price. Splitting cost by raw token
count is wrong. The driver weights each token type by its model's rate to get a
"cost proxy", then normalizes the proxy sum to the actual billed total. Two
normalizations, both summing to the bill: `scale_model` for the authoritative
model/type tables, `scale_local` for the project/day tables.

## Run (agent path)

Default — auto-fetch the user's own row for this month:

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

Default output: `./<month>-bedrock-cost-report.html` — **현재 디렉토리**, 하위 폴더를
만들지 않는다. 다른 위치는 `--out <path>`. Open on WSL with `explorer.exe <path>`.

## Self-check

```bash
python3 scripts/test_driver.py   # -> all self-checks passed
```

Covers CSV model-column grouping, the no-fallback rate lookup, and the
normalize-to-bill math.

## If the CSV columns don't parse

The parser detects token-type columns by keyword (`input`/`prompt`,
`output`/`completion`, `cache_read`, `cache_write`/`cache_creation`) and takes
the remaining non-generic word(s) as the model key — order-independent, so
`input_tokens_opus` and `opus_input_tokens` both work. If AICM uses different
column names, adjust `COLPATS` / `GENERIC` at the top of the CSV section in
`scripts/driver.py`. When in doubt, **ask the user to paste the CSV header line** and
confirm which columns map to which token type before trusting the output.

## Gotchas

- **Local logs ≠ AICM totals.** `~/.claude/projects` on one machine is a *partial*
  record: session resume/fork copies a message across files (inflates raw counts
  ~2×), and sessions from other machines/environments are missing entirely (e.g.
  Sonnet usage may not appear locally at all). So model/token-type/total come from
  the CSV (authoritative), and local logs drive only the *relative* project/day
  split. The report badges which is which (`AICM 기준` vs `로컬 로그 근사`).
- **Effective rate ~34% of list.** Internal Bedrock price is well below AWS list;
  the driver normalizes to the actual bill, so the emitted `scale` ≈ 0.34 is
  expected, not a bug. With CSV missing, local token inflation makes it look lower.
- **Top-level day chart = all projects, flow only.** The overall "날짜별 비용"
  section is a trend chart (no per-day table), covering every project's cost
  by day. Expand a project row under "프로젝트별 비용" for its own exact
  day-by-day cost **and its own `git log`** (resolved via `unmangle()` from
  the `~/.claude/projects` dir name to that project's real path) — themes
  never mix across projects, and a project without a resolvable git repo just
  shows cost with no theme.
- **Efficiency metrics degrade gracefully.** Each row is skipped when its input is
  missing rather than printing a zero: the org comparison needs `--fetch` (it calls
  `/api/budget-org/summary` + `/info` for aggregates and the org name only), and the session
  metrics need local logs. `--csv`-only runs simply show fewer rows.
- **`cache_read` vs `cache_write` are different levers** — don't merge them in
  prose. Write = paid once when content enters the context; read = paid again every
  later turn. That distinction is what makes the insight actionable.
- **Output lands in cwd** as `<month>-bedrock-cost-report.html`; pass `--out` to
  put it elsewhere. Reporting inside a git repo leaves an untracked HTML file —
  tell the user where it is so they can move or ignore it.

## Troubleshooting

- `No local logs for <month> and no --csv` — no local records for that month on
  this machine and no CSV. Provide `--csv`, or run on the machine with the logs.
- `Need a billed total` — pass `--csv` (with a `total_cost` column) or `--cost`.
- Model row shows a weird key like `unknown` — a token column's model suffix
  wasn't recognized; check the CSV header and adjust `GENERIC`/`COLPATS`.
