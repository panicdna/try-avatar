---
name: avatar-onboarding
description: Use when a user wants to install, set up, improve, or adapt an Agent Factory Avatar Card as a personal Claude Code, OpenCode, or Codex subagent; also use when an avatar needs missing work knowledge, tools, data references, quality rules, or approved Card/Role/Task changes before it can do real work.
---

# Avatar Onboarding

Turn an Avatar Card into a useful personal subagent. A Card is the starting design for **what** work to do and **why**; personal rules, Skills, tools, knowledge references, and quality criteria specify **how** it works and **for whom**. Never treat a Card as ready without filling the operational gaps — and a Card with detailed Role/Task text is *not* an exception: that text is shared intent, not your operational context.

## Safety boundary

- Keep domain data in its system of record. Record or generate only its location, owner, intended task, access scope, sensitivity/exclusions, freshness, and access method.
- Do not write to a user-global directory, modify a Card/Role/Task, overwrite a generated file, or perform an external final action without the user's explicit confirmation.
- Use existing Agent Factory endpoints. Invoke the `agent-factory-api` skill (install `agent-factory-api@skill` if it is not already installed) for endpoint details and the payload reference before calling the API.
- Personal instructions belong in the installed avatar profile. Card structure is shared: add/delete/split/merge/relink only after showing a semantic diff and impact.

## Workflow

1. Explain the Card/operational-knowledge distinction above, then identify the current task/project and search/read candidate Cards, Roles, and Tasks through the existing Agent Factory API.
2. Recommend candidates by task/project fit first, then the user's stated favorites or prior use. Explain the reasons and wait for selection. If none fits, or the user wants a new avatar, start a **new Card draft** rather than forcing an existing Card to fit.
3. For a new Card draft, interview to define one responsibility, then propose the smallest useful Role→Task structure. Reuse an existing Role/Task when it fits; otherwise draft the new Task(s), then Role(s), then Card. Do not create any server entity yet.
4. **Use personal Agent session evidence only when the user explicitly requests it.** Accept the current conversation context, a user-selected session export/file, or an explicitly named local session location. Read only that selected scope; never scan a home directory, enumerate session histories, or upload/store raw logs. Extract a short evidence summary: repeated task, inputs, outputs, tools/Skills, decisions, quality checks, and unresolved friction. Show the summary and proposed Card/profile changes before using it.
5. Interview until the readiness checklist below is complete. Ask one high-value question at a time; summarize confirmed answers and distinguish facts from assumptions. Confirm each checklist item **explicitly** as answered or marked unavailable — do not infer that a detailed Card's Task prose pre-answers any item. The operational context that makes a Skill do *your part's* work (org/reporting line, cadence, project/space keys, recipients, quality exemplars, credentials) is almost never in the Card; elicit it here, not after install.
6. Classify proposed changes:
   - **Personal profile:** output template, quality bar, decision rules, prohibitions, examples, tool choices, and knowledge-reference metadata. Include them only in the personal profile/install files.
   - **Card structure:** Card/Role/Task text or links, including add/delete/move/split/merge. Show a before/after diff and impact, then call the existing avatar CRUD API only after approval.
7. For a new Card, show the entire draft and impact, obtain explicit approval, then use the existing API in dependency order: create/reuse Task → create/reuse Role with `task_ids` → create Card with `role_ids`. Re-read/report every returned ID; stop on a failed step rather than creating an orphaned structure.
8. Generate a reviewed profile and platform-specific installation plan. Show every target path and any conflict before writing.
9. Install only the confirmed platforms. Write the reviewed local JSON profile, then run `scripts/install_avatar.py --profile <approved-profile.json> --platform <claude|opencode|codex>` once for each selected platform. The installer refuses user-modified targets. At execution time, bind the current project as context; do not copy project data into the global profile.
10. Run toward a reviewable **draft final**. Ask for feedback, update the personal profile or propose a structural Card change, and re-run. Require a separate explicit approval for irreversible external writes.

## Readiness checklist

Do not offer install until each item is **explicitly** answered or the user deliberately marks it unavailable. Confirm item by item; a Card whose Role/Task text looks complete pre-answers none of these. Capture the concrete identifiers in parentheses — a reference recorded by name only ("Jira", "Confluence") is not answered.

- **Trigger/start condition, cadence, and expected inputs** (e.g. weekly deadline day, quarterly review month; who/what triggers it)
- **Deliverable/output format and definition of done** (prefer pointing at an existing artifact to match)
- **Quality bar and review method**, plus **one representative good/bad example** (or an existing file that defines "good")
- **Decision rules, prohibitions, and escalation/approval boundary** (concrete thresholds and who performs the final external action)
- **Required Skills, MCP/tools, and access constraints** (and whether each is actually installed/reachable now)
- **Knowledge references**: location/system of record, owner, purpose, sensitivity/exclusions, freshness, access method — with the concrete identifiers the tools need (repo files to read at runtime, Jira project keys, Confluence space key, required env/credentials, report recipients, org/reporting line)

### Red flags — STOP, you are skipping the checklist

- "The Card's Task text is detailed, so the checklist is covered."
- "The Skill is installed, so the avatar can do the work."
- "I'll fill the operational context after installing / during a trial run."
- Offering install with any item neither answered nor explicitly marked unavailable.
- Recording a knowledge reference by name only, without its concrete identifier and access method.

All of these mean: return to the interview and confirm each item before offering install.

| Rationalization | Reality |
|---|---|
| "Rich Card = ready" | Card = what/why (shared intent). Checklist = how/for-whom (your operational context). Detailed Task prose answers none of it. |
| "Skill installed = capable" | A Skill is a generic capability. Without cadence, recipients, project/space keys, and quality exemplars it emits generic output, not your part's work. |
| "Fill context later" | With the ask satisfied, later never comes and a shallow avatar ships. Elicit before install; mark true unknowns 'unavailable', not 'skip'. |

## Session-evidence update format

When a user asks to update an avatar from an Agent session, use this format before proposing a write:

```markdown
## Selected session evidence

- Scope read: [current conversation / user-selected file or location]
- Observed repeated work: …
- Candidate role/task/profile improvements: …
- Excluded sensitive material: …

May I use this summary to propose the Card/profile diff? (yes/no)
```

Treat session evidence as a suggestion, not truth: ask the user to confirm inferred responsibilities, ownership, and quality standards. Do not include secrets, personal data, unrelated conversation details, or verbatim logs in the generated Card, profile, API payload, or final report.

## Card-change approval format

Use this exact format before any existing API write, including a new Card:

```markdown
## Avatar Card change proposal

### Structural diff / new draft

- [add/update/delete/move] …

### Impact

- Affected roles/tasks: …
- Installation/runtime effect: …
- Reversal: …

Approve this exact structural change? (yes/no)
```

For approved changes, re-read the target entity immediately before PATCH and send the minimum existing API fields. Report returned IDs and changed fields.

## Install targets

Generate a profile under `~/.agent-factory/avatars/<card-slug>/` containing only the profile and reference metadata. Then, after confirmation:

| Platform    | Subagent target                                                      |
| ----------- | -------------------------------------------------------------------- |
| Claude Code | `~/.claude/agents/agent-factory/<card-slug>-<role-slug>.md`          |
| OpenCode    | `~/.config/opencode/agents/agent-factory/<card-slug>-<role-slug>.md` |
| Codex       | `~/.codex/agents/<card-slug>-<role-slug>.toml`                       |

Read [`references/platform-adapters.md`](references/platform-adapters.md) before rendering. Verify current platform documentation when a field or global path is uncertain; do not invent config keys.

`scripts/install_avatar.py` accepts a local profile JSON with `card_slug`, `profile`, and `roles[]` (`slug`, `title`, `description`). Use `--home <temporary-directory>` only for tests; omit it for the user's confirmed real installation.

## Final response format

Always report: selected avatar, readiness gaps or confirmed profile, Card changes (if any), installed platforms/files, draft-final status, and the next approval required.
