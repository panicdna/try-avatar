---
name: claude-delegation
license: Apache-2.0
description: >-
  Delegate a GitHub issue to Claude Code CLI end to end: implement, open a
  PR, adversarially review it yourself, and loop re-delegation until every
  review comment is resolved. Use when the user says "do #N", "#N 해줘",
  or references any bare "#N" issue number as a task — treat "#N" as
  GitHub issue #N and run this skill.
allowed-tools: Bash, Read, Grep, Glob
metadata:
  agent-factory:
    kind: item
    item_id: 6d6f1518-ee35-4bf8-9fea-e430f489327a
    version_id: 0d1d50c9-ff0d-40dd-a7a0-858c9129fd85
---

# claude-delegation — Issue → Claude Code → PR → Adversarial Review Loop

End-to-end: take a GitHub issue, delegate implementation to the Claude Code
CLI, verify the PR really exists, review it adversarially yourself, and loop
re-delegation until all review comments are resolved. **Completion = all
comments closed with independent verification on the final head SHA**, not
"PR exists".

## When to Use

- "do #N", "#N 해줘" — a bare issue number is enough; treat `#N` as GitHub
  issue #N in the current repo and run this skill.
- Any request to delegate implementation to Claude Code and gate it on your own adversarial review.

If the user gives only `#N` with no other instruction, default to this
skill's full loop (implement → PR → adversarial review → resolve comments).

## Procedure

### Step 1: Read the live issue

```bash
gh issue view <N> --json title,body,state,labels,comments
gh pr list --search "#<N>" --state all   # duplicate sweep
```

The body is a snapshot from filing time; newest comments carry the live
state. Done when the requested behavior, non-goals, and any thread questions
are known.

### Step 2: Delegate to Claude Code (generous limits — never let it get killed)

**Work in a Claude worktree, not the main checkout.** Branches alone block
parallel work — other sessions can't run concurrently on the same working
tree. Create it yourself to match Claude's convention (directory and branch
share the same name, 1:1):

```bash
git worktree add .claude/worktrees/issue-<N> -b issue-<N>
```

(The `claude -w` flag does this too, but it's interactive-mode oriented —
in print mode (`-p`) create the worktree directly as above.)

Run Claude with the working directory set to that worktree. After merge,
clean up: `git worktree remove .claude/worktrees/issue-<N>` — keeps the main
checkout on main, clean, so multiple issues can proceed in parallel across
sessions.

Run in a **background process** (e.g. `terminal(background=true,
notify_on_complete=true)`), not foreground with a timeout — foreground
timeouts kill long delegations mid-flight.

**Permissions: prefer scoped `--allowedTools` over
`--dangerously-skip-permissions`.** Print mode (`-p`) is non-interactive:
unapproved tools simply fail rather than prompt, so autonomous work needs
pre-approved permissions — but that can be an allowlist, not a blanket
bypass:

```bash
claude -p "$(cat /tmp/task.md)" \
  --allowedTools 'Read' 'Edit' 'Write' 'Bash(git *)' 'Bash(gh *)' 'Bash(uv run pytest *)' 'Bash(bun run *)' \
  --output-format json --max-turns 200 --max-budget-usd 25 \
  --model sonnet --effort ultracode \
  > /tmp/result.json 2>/tmp/stderr.log; echo "EXIT=$?" >> /tmp/stderr.log
```

Rules of thumb:

- Default to `--allowedTools` scoped to what the task needs (git, gh, test
  runner, formatter). Least privilege. `rm -rf`, network installs etc.
  stay blocked.
- Reach for `--dangerously-skip-permissions` only when the task legitimately
  needs arbitrary commands (unknown build tooling, network installs) and the
  workdir is disposable/isolated.
- Middle ground: `--permission-mode acceptEdits` (auto-accept file edits
  only; bash still needs explicit allows. Use instead of `--allowedTools`,
  not alongside it — they are mutually exclusive).
- Generous ceilings so it never dies mid-task: `--max-turns 200`,
  `--max-budget-usd 25`, `--model sonnet --effort ultracode`.
- Upgrade to `--model opus` for complex reasoning (major refactoring,
  architecture changes).
- `--model sonnet` / `--model opus` are environment-independent aliases. On
  a custom gateway they map to the gateway's actual model names (e.g.
  `claudecode-sonnet-5[1m]`, `claudecode-opus-5[1m]`). If you see an
  `unrecognized_model` warning, it is cosmetic — the gateway still resolves
  and uses the correct model.

**Task file** (`/tmp/task.md`) must be self-contained: issue summary,
branch/commit/PR steps, quality gates to run, scope constraints ("no
out-of-scope refactors", "if blocked, print what blocked you and stop"),
and required final output (PR URL, head SHA, files). Feeding everything it
needs up front also reduces the tool surface Claude needs — fewer surprises
under an allowlist.

**If interrupted:** do NOT just do it yourself. Diagnose root cause from
`result.json` `subtype` (`error_max_turns`, permission denials),
`stderr.log`, cost/turns — then fix the config (raise turns/budget, extend
the allowlist) and rerun.

### Step 3: Verify the PR yourself — never trust the child's report

```bash
gh pr view <N> --json number,url,state,headRefOid,baseRefName,files
gh pr diff <N> > /tmp/pr.diff   # read it fully
```

Independently run the gates in a clean clone: tests, the guard script,
plus a **sabotage check** — temporarily break the thing the guard/tests
protect (e.g. mutate a revision id), confirm FAIL + exit 1, restore.
A test that passes with and without the fix proves nothing; sabotage is
the only proof a guard actually bites.

### Step 4: Adversarial review → inline comments via one atomic API call

Write the review payload to a JSON file (avoids heredoc/backtick shell
mangling), fill `commit_id` with the real head SHA, then:

```bash
gh api repos/<owner>/<repo>/pulls/<N>/reviews --input /tmp/review.json
```

Include per-file inline comments with exact new-file line numbers,
verified against full file context, not just the diff. Review checklist:
correctness/edge cases, security, scope discipline ("every changed line
traces to the issue"), sibling call sites of the same bug, missing tests,
fail-open vs fail-closed direction.

**Note:** GitHub rejects APPROVE on your own PR (422 "Can not approve your
own pull request") when the same token authored it — use
`event: "COMMENT"` for the verdict in that case.

### Step 5: Re-delegation loop until every comment is resolved

Loop Steps 2–4 on the SAME PR branch until each review comment is either
fixed or explicitly justified as no-change (with reasoning). Then post a
re-review confirming each comment resolved/closed.

**Keep the follow-up task SHORT:** instruct Claude to read the review
comments itself and address each one — don't paste the full comment text
into the prompt. Cleaner, less drift, Claude sees the canonical source:

```
gh api repos/<owner>/<repo>/pulls/<N>/comments --jq '.[].body' 로 리뷰 코멘트를 읽고,
각 코멘트에 대해 반영하거나 반영하지 않을 근거를 답변으로 남겨라.
```

After the fix push: re-read the diff, re-run gates independently on the new
head SHA, then close each comment in a re-review.

### Step 6: Done only when

- All inline comments have resolution replies or fixes,
- independent verification passes on the final head SHA (tests + sabotage),
- no out-of-scope files changed,
- worktree cleaned up after merge (main checkout back on main, clean).

**Always finish with a PR + adversarial review.** Any completed change —
even skill/doc edits like updating this file itself — goes through the same
loop: commit → push → open PR → adversarial review → resolve all comments.
Local-only edits are not "done".

## Pitfalls

- Foreground timeouts kill long delegations → always background +
  notify_on_complete.
- Trusting child's "PR created" summary without checking head SHA/diff.
- Heredoc/quoting mangles JSON review payloads with backticks/`$` — write
  the payload with a file-write tool instead.
- APPROVE 422 on own PR → use COMMENT event.
- Sabotage test is the only proof a guard actually bites.
- Blanket `--dangerously-skip-permissions` on a repo checkout lets the
  child touch anything — prefer scoped allowlists.
- Working on a branch in the shared checkout kills parallelism — always use
  `.claude/worktrees/issue-<N>`; clean up after merge.
- The `-w` flag is interactive-mode oriented; in print mode (`-p`) create
  the worktree yourself and pass it as the working directory.
