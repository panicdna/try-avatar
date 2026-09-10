# Clustering a digest into Card / Role / Task

## The axis

Cluster by **work character × recurrence**, not by project directory. The same
kind of work scattered across several repos belongs in one Card; two unrelated
kinds of work inside one repo belong in two.

"Work character" means the answer to: *what does this produce, and by what
judgment?* A guide document and a landing-page plan are both writing, but the
judgment differs (accuracy for a reader who must follow steps vs. persuasion for
a reader deciding whether to care) — two Roles, possibly one Card.

`tool_mix` is the cheapest character signal in the digest:

| Signal | Likely character |
|---|---|
| `Bash` dominant | operations, diagnosis, environment work |
| `Edit` dominant | code development and modification |
| `Read` + `Write` together | documentation, research, synthesis |
| `WebFetch` / `WebSearch` present | investigation, external verification |

Treat it as a hint, not a verdict. A `Bash`-heavy session can be a build script
for a documentation pipeline.

## Promotion thresholds

| Layer | Promote when | API requires |
|---|---|---|
| **Task** | the same character recurs in 2+ sessions, or 5+ one-off sessions compose into one unit | `title` |
| **Role** | 2+ Tasks share an output kind and a judgment standard | `title` **and** `description` |
| **Card** | the responsibility fits one sentence, backed by 3+ sessions across 2+ distinct dates | `name` |

Below threshold, do not discard. List it as **"관측됨 · 근거 부족"** with the session
count so the user can promote it if it is real work whose evidence is thin.

**Card ceiling: 3–6.** Mirroring the project count produces Cards without a
single clear responsibility, which is exactly what `agent-factory-api` warns
against. If you have more candidate Cards than that, you are clustering by
directory.

## Rolling up one-off sessions

A session with `turns` of 1–2 is a question, not a work unit. It never becomes a
Task on its own. But 5+ one-off sessions of the same character **compose into one
Task**:

```
11 sessions, turns=1, Bash-dominant, ~ 로 시작하는 제목 (statusline / hook / 설정 진단)
  → Task "환경 설정 진단 및 복구"     ← not 11 Tasks, and not discarded either
```

The `~ ` prefix on a title means it fell back to the first prompt because the
session had no `ai-title`. Those titles are rawer and less reliable — weigh
`tool_mix` and `cwd` more heavily for them.

## Wording rules

Write the business outcome, never the tool.

| Bad | Good | Why |
|---|---|---|
| "Claude Code 쓰기" | "부서원이 쓸 AI 개발환경 가이드를 유지한다" | a tool name is not a responsibility |
| "AI assistant" | — | says nothing; ask the user for the actual outcome |
| "개발 도우미" | — | same |
| "스킬 만들기" | "사내 마켓플레이스에 배포할 스킬을 패키징·검증한다" | names the deliverable and the standard |

A Card's `responsibility` should survive the question *"and then what?"* —
"스킬을 패키징한다" invites it; "배포 가능한 상태로 검증해 마켓플레이스에 올린다"
answers it.

## What never goes into Card text

- session dates, `cwd` paths, `tool_mix` counts, `turns` numbers
- Skill call counts ("brainstorming 9회")
- anything from the profile layer: output templates, quality bars, decision rules,
  prohibitions, escalation boundaries, credentials, knowledge-reference metadata

The first two are working evidence — they belong in the proposal's 근거 section,
summarized. The last is `avatar-onboarding`'s layer, elicited by interview.
