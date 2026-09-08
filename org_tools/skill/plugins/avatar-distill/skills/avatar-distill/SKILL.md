---
name: avatar-distill
description: Use when a user wants their own Claude Code usage history turned into Agent Factory Avatar Cards — figuring out what work they actually repeat and creating new Cards or augmenting existing ones from that evidence.
license: Apache-2.0
---

# Avatar Distill

Read the user's local Claude Code transcripts, work out which work they actually
repeat, and express it as Avatar Card / Role / Task structure — creating new Cards
or augmenting existing ones.

Direction matters. This skill runs **history → Card** (what work, and why). The
`avatar-onboarding` skill runs the other direction, **Card → working subagent**
(how you work, and for whom). Leave the profile layer empty here; onboarding
fills it by interview.

## Safety boundary

- Raw transcripts never enter your context, an API payload, or a file. Only the
  digest the script produces does.
- The digest is evidence, not truth. Every Card change is proposed and approved
  one at a time — never in a batch.
- Never write to a user-global directory without the user's confirmation.
- Never modify a team-scope Card. The user's own history is not grounds to edit
  someone else's asset.
- Invoke `agent-factory-api` for every API call (install `agent-factory-api@skill`
  if missing). Do not restate its endpoints, auth, PATCH semantics, or error
  handling here — in particular its relationship-array rule, which already
  prevents the `role_ids` whole-set replacement footgun.

## Workflow

1. Run the extractor. Ask before writing outside `/tmp`:
   ```bash
   python3 scripts/extract_digest.py --stdout          # inspect first
   python3 scripts/extract_digest.py                   # ~/.agent-factory/avatar-distill/
   ```
   `--since YYYY-MM-DD` and `--project SUBSTR` narrow the scope. If the digest is
   empty or the directory is missing, stop and ask which harness the user runs.
2. Read the digest's aggregate header first — date span, session count, paths,
   Skill ranking. Get the shape before reading rows.
3. Cluster by **work character**, not by project directory. See
   [`references/clustering.md`](references/clustering.md) for the axes, promotion
   thresholds, and Card wording rules.
4. Separate the two isolation buckets and **ask** about them — see below. Do not
   decide them yourself, in either direction.
5. Read the user's existing assets through `agent-factory-api`:
   `GET /avatars/cards?scope=mine`, then each Card's Roles, then each Role's Tasks.
   A Card list entry only carries `{avatar_role_id, title, task_count}`, so Tasks
   require a Role GET.
6. **Audit what is already there** — the existing Card's own gaps are findings,
   not just a backdrop for new clusters. See below.
7. Classify each cluster against those assets: **same responsibility** → augment,
   **partial overlap** → add Roles/Tasks only, **no match** → new Card. State the
   evidence for each classification. When the overlap looks total, check whether
   it is *intake* or *disposition* that matches — two Tasks can share an input and
   still stop at different points.
8. **Optionally deepen a cluster** before proposing it — see below. Titles alone
   produce thin Task text; the conversation holds the procedure actually followed.
9. Propose **one change at a time** and wait for the user's answer. Use the
   proposal format below. A declined item is skipped; the rest continue.
10. Write in dependency order — Task → Role (`task_ids`) → Card (`role_ids`).
    On a failed step, stop and report the IDs already created rather than leaving
    an orphaned structure.
11. Record what was applied to `~/.agent-factory/avatar-distill/applied-<YYYYMMDD>.json`
    so a later run can see its own history.

## Audit the existing Card

Distilling is not only additive. A Card that already exists usually has thin
spots, and the digest is often exactly the evidence needed to fill them. Report
these as proposals alongside the new clusters — the user cannot fix what they
cannot see, and they should not have to notice it themselves.

Walk every Role and Task already on the Card and flag:

| Gap | Why it matters |
|---|---|
| Task with empty `text`, or a bare label ("기능 개선, 버그 수정") | States the topic, not the work. Nobody can act on it. |
| Task with empty `context` | No trigger and no boundary against its siblings. |
| Task missing profile slot hints while its siblings have them | Inconsistent readiness — the interview will skip this one. |
| `Role.description` that does not cover the Tasks under it | A Task drifts outside the Role's stated scope and stops being findable. |
| No skill link where the digest shows a Skill was actually used | The installed subagent lacks a capability the work needs. |
| Stale name — a renamed Skill, tool, or system | Silently breaks on the next install. |
| Two Tasks whose text no longer distinguishes them | One of them is dead weight, or a boundary needs stating. |

Report the audit as a table — gap, which entity, and what evidence in the digest
could fill it — then propose fixes one at a time like any other change. A gap
with no supporting evidence in the digest is still worth naming; say plainly that
the user has to supply the content.

**Do not silently rewrite existing text.** An existing Task was written by
someone, possibly for reasons the digest cannot see. Propose, show the before and
after, and let the user decide.

## Optional deep read

A Task built from session titles says *that* the work happens. It cannot say
*how*. To get the procedure, read the cluster's conversation:

```bash
python3 scripts/extract_transcript.py --title "…" --title "…" --out /tmp/cluster.md
```

It emits user prompts and assistant prose only — tool results, tool inputs, and
thinking blocks are excluded, and secrets are scrubbed. Conversation text runs
about 3% of the raw transcript, so a 6-session cluster costs roughly 25k tokens.

**Rules:**

- **Offer it, don't assume it.** Report the token cost from the script's own
  output and let the user decide per cluster. Never deep-read the whole history —
  one cluster at a time.
- **Delegate the read to a subagent.** It reads `/tmp/cluster.md` and returns only
  its findings, so the conversation text never enters the main context.
- **Require repetition.** A step counts as procedure only if it appears in at
  least half the cluster's sessions. Tell the subagent to report the observation
  count per step; a step seen once is that incident's accident, not a procedure.
- **Give it a character budget, measured from the Card.** Count the length of the
  Card's existing well-filled Tasks and pass that as a cap — "본문 N자 이내". Asking
  for "4–6 sentences" does not work: a subagent that found twelve valid steps
  writes twelve-clause sentences and lands at 2–5x the house length. With the cap
  it has to rank by observation count, which is the editorial decision you want it
  making anyway. If it overruns, cut by observation count, keep every safety
  prohibition, and say what you dropped.

**Require the subagent to split its findings into three buckets.** Mixing them is
the failure mode — a first run returned approval boundaries and quality bars as
if they were procedure, and they had to be separated by hand:

| Bucket | Goes where | Example |
|---|---|---|
| **Procedure** — how this work is done, by anyone | Task `text` | "재현과 실측으로 사실을 확보한 뒤 판단한다" |
| **Decision rules, approval boundaries, quality bars** | *Nowhere here* — `avatar-onboarding`'s profile layer. The exception is a safety prohibition; see above | "되돌릴 수 없는 변경 전 승인을 받는다" |
| **Profile slot hints** — *which* operational facts this work needs, not their values | Task `text`, closing line, in the Card's own format | "설치 시 개인 프로필에 채울 것: 신고 접수 경로 · 승인자·임계값 · 완료 판정 기준" |

The third bucket is the bridge. Naming the slots is shareable and tells
`avatar-onboarding`'s interview what to ask; filling them is not this skill's job.

## Isolation buckets — ask, never decide

Two groups look like work in the digest but may not be the user's
responsibility. Silently excluding them is as wrong as silently promoting them.

**`[self-tooling]`** — sessions whose `cwd` is `~`, `~/.claude`, or `~/.config/*`
and whose subject is Claude Code's own configuration (statusline, `settings.json`,
hooks, plugin installs). Whether this is the user's job or personal tool fiddling
is not inferable from the digest. Ask once:

```
[self-tooling] 관측: N개 세션 (statusline 6, settings.json/hook 5, 플러그인 설치 3)
  (a) 제외 — 개인 도구 세팅이므로 Card 대상 아님
  (b) 별도 Card — "개인 AI 개발환경 관리"
  (c) 기존 Card 의 Role 로 승격 — 동료 환경 세팅을 돕는 업무의 일부라면
```

**`[meta]`** — one-off learning or exploration questions, sessions that only read
someone else's code, and sessions spent building this tooling. Default to
excluding them, but list what you excluded so the user can object.

## Card text carries no raw evidence

The digest's session dates, local paths, tool counts, and `turns` are *your*
working evidence. A Card is a shared asset read by colleagues, so none of that
belongs in `name`, `responsibility`, `title`, `description`, `context`, or `text`.

<Bad>
```json
{"title": "가이드 문서 출처 보강",
 "context": "2026-08-21, /home/u/WORK/ai-enablement, Read 40/Edit 17"}
```
</Bad>

<Good>
```json
{"title": "가이드 문서 출처 보강",
 "context": "가이드 개정 시 근거 링크가 빠졌다는 지적을 받았을 때"}
```
</Good>

`context` answers *when this work is triggered* and *where its boundary against a
neighbouring Task lies*, not *where the evidence came from*. If you cannot state
the trigger without citing a session, leave `context` out and say so.

### Prohibitions are not all the same

Not every rule belongs to the profile. Split them by whether being shared is the
point:

| Kind | Goes where | Example |
|---|---|---|
| **Safety prohibition** — must survive being handed to anyone | Card `context` | "고객 메일을 직접 발송하지 않는다 — 발송은 사람이 웹 UI 로 한다" |
| **Personal quality bar / approval preference** | Profile | "되돌릴 수 없는 변경 전 팀장 승인을 받는다" |

A safety prohibition that lives only in a profile disappears for the next person
who installs the Card, which is the failure it exists to prevent. Output
templates, quality bars, decision rules, tool choices, credentials, and
knowledge-reference metadata still belong to the profile.

### Match the Card's own conventions

Before writing, read a few of the user's existing Tasks. If they already have a
house style, follow it rather than inventing one — an established Card is
evidence about how this user writes. In particular, profile slot hints are often
already present in a compact form:

```
설치 시 개인 프로필에 채울 것: 담당 서비스명 · 판별 기준 · 서명 형식 · 좋은/나쁜 예 각 1건
```

## Proposal format

One of these per change. Never merge several into one approval request.

```markdown
## Avatar Card change proposal (n/N)

### 변경
- [new Card / add Role / add Task / patch responsibility] …

### 근거
- 세션 N개, <기간> — 요약된 관측 (원시 경로·툴 카운트 없이)

### 영향
- 영향받는 Role/Task: …
- 되돌리기: …

이 변경을 적용할까요? (yes/no/skip)
```

## Red flags — STOP

- Emitting more than one change for a single approval
- Any curl in your output that the user has not approved for that specific change
- A session date, local path, tool count, or `turns` number inside Card text
- Deciding `[self-tooling]` or `[meta]` without asking
- Guessing a `skill_id` or `component_key` instead of resolving it
- Proposing a Card for a cluster below the promotion threshold without saying so

## Rationalizations

| Excuse | Reality |
|---|---|
| "The user is out of time, so I'll confirm everything at once" | Time pressure is when a wrong Card gets written. One at a time is faster than undoing a batch. |
| "I'll list my judgment calls at the end instead" | A note after the write is not an approval before it. Ask at the gate. |
| "The context field is where evidence goes" | `context` is the work's trigger condition. Evidence stays in the digest. |
| "Session paths make the Card more precise" | They make it unreadable to colleagues and leak local layout. Summarize instead. |
| "These home-directory sessions are obviously not real work" | Obvious to you, not established. The user said which of these count; ask. |
| "Only one Card matched, so the rest are clearly new" | Partial overlap is the common case. Check Roles and Tasks before declaring a new Card. |
| "Prohibitions always belong in the profile" | A safety prohibition kept out of the Card vanishes for the next installer. Share it; keep personal approval preferences out. |
| "This Task overlaps an existing one, so drop it" | Check whether the overlap is intake or disposition. Two Tasks can share an input and still differ in where they stop. |
| "I'll write it in the format I think is clearest" | The user's existing Tasks are evidence of their house style. Read a few first and match them. |
| "The existing Card is context, my job is the new clusters" | Distilling repairs as well as adds. An empty `text` on an existing Task is a finding — audit before proposing. |
| "The user approved this proposal, so it is complete" | You wrote the proposal. If it omitted `text`, the Task ships empty and that is on you, not the approval. |

## Skill links

The digest reports Skill names the way the harness does — often
`plugin:component` (`superpowers:systematic-debugging`). Agent Factory registers
the *plugin* as the skill and the rest as a component, so resolve in that shape:

1. Split on `:`. Query `GET /skills?q=<plugin-part>`.
2. Pick the item whose `name` is **exactly** the plugin part — not "the only
   result". `q=superpowers` returns `superpowers` and `impl-select`; only the
   first is the match.
3. Read that skill's detail and confirm the component part appears in
   `components[].key`. That key is the `component_key`.
4. For a bare name with no `:`, match an exact skill name the same way; if the
   skill has exactly one discoverable component, use it.

Link only when steps 2 and 3 both succeed. Otherwise — no exact name match, or
no matching component key — create the Task without the link and report why. Many
locally-installed skills are simply not registered in Agent Factory; that is a
normal outcome, not an error. A missing link never blocks Task creation, and an
ID is never invented or copied from an unrelated Task.
