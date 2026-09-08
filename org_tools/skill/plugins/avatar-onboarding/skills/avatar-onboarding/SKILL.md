---
name: avatar-onboarding
description: Use when a user wants to install, set up, improve, or adapt an Agent Factory Avatar Card as a personal Claude Code, OpenCode, or Codex subagent; also use when an avatar needs missing work knowledge, tools, data references, quality rules, or approved Card/Role/Task changes before it can do real work.
license: Apache-2.0
---

# Avatar Onboarding

Turn an Avatar Card into a useful personal subagent. A Card's Role/Task text describes **what** work to do and **why** -- write it as specifically as the work warrants; a detailed, concrete Card is a better starting point than a vague one. Personal rules, Skills, tools, knowledge references, and quality criteria specify **how** it works and **for whom**, and those are a different category of information from the Card's what/why -- so they still need filling in even when the Card's Task text is already detailed. Never treat a Card as ready without filling those operational gaps.

## Safety boundary

- Keep domain data in its system of record. Record or generate only its location, owner, intended task, access scope, sensitivity/exclusions, freshness, and access method.
- Do not write to a user-global directory, modify a Card/Role/Task, overwrite a generated file, install or reconfigure an MCP server/Skill, or perform an external final action without the user's explicit confirmation. Default `claude mcp add`/`claude plugin install` to the least-global scope (`local`); only pass `-s user`/`-s project`, or use a broader plugin-install scope, when the user explicitly asks to escalate.
- Use existing Agent Factory endpoints. Invoke the `agent-factory-api` skill (install `agent-factory-api@skill` if it is not already installed) for endpoint details and the payload reference before calling the API.
- Personal instructions belong in the installed avatar profile. Restructuring a Card (add/delete/split/merge/relink) can affect every installation built on it -- show a semantic diff and impact, and get explicit approval, before calling the API for those. Making existing Role/Task text more specific (adding detail, conditions, examples) without changing that structure is lower-stakes: show the before/after text and get a plain confirmation, no impact writeup required.

## Workflow

1. Explain the Card/operational-knowledge distinction above, then identify the current task/project and search/read candidate Cards, Roles, and Tasks through the existing Agent Factory API.
2. Recommend candidates by task/project fit first, then the user's stated favorites or prior use. Explain the reasons and wait for selection. If none fits, or the user wants a new avatar, start a **new Card draft** rather than forcing an existing Card to fit.
3. For a new Card draft, interview to define one responsibility, then propose the smallest useful Role->Task structure. Reuse an existing Role/Task when it fits; otherwise draft the new Task(s), then Role(s), then Card. Do not create any server entity yet.
4. **Use personal Agent session evidence only when the user explicitly requests it.** Accept the current conversation context, a user-selected session export/file, or an explicitly named local session location. Read only that selected scope; never scan a home directory, enumerate session histories, or upload/store raw logs. Extract a short evidence summary: repeated task, inputs, outputs, tools/Skills, decisions, quality checks, and unresolved friction. Show the summary and proposed Card/profile changes before using it.
5. Run the **Structural pre-filter** below first when a Card already exists, then interview until the readiness checklist is complete. Ask one high-value question at a time; summarize confirmed answers and distinguish facts from assumptions. Confirm each checklist item **explicitly** as answered or marked unavailable -- do not infer that a detailed Card's Task prose pre-answers any item. The operational context that makes a Skill do *your part's* work (org/reporting line, cadence, project/space keys, recipients, quality exemplars, credentials) is almost never in the Card; elicit it here, not after install. If this Card already has a `decisions.md` (see *Install targets*) from a prior session, check it before asking -- when the same root cause recurs (e.g. an access gap already ruled out while resolving a different Task/Role), restate the prior resolution and ask only a lightweight confirmation that it still applies, rather than re-running the full question.
6. For every MCP/Skill requirement surfaced in step 5, resolve it per [`references/mcp-skill-setup.md`](references/mcp-skill-setup.md): detect present-vs-absent, ask reuse-vs-reinstall when present, install when absent, and interview for any credential/config the tool needs to function -- using the **MCP/Skill setup approval format** below before running any install or config command. Do this during the interview, before the checklist item counts as answered -- not after install.
7. Classify proposed changes:
   - **Personal profile:** output template, quality bar, decision rules, prohibitions, examples, tool choices, and knowledge-reference metadata. Include them only in the personal profile/install files.
   - **Card restructuring:** add/delete/move/split/merge/relink of Cards, Roles, or Tasks. Show a before/after diff and impact, then call the existing avatar CRUD API only after approval.
   - **Role/Task text elaboration:** making an existing Task or Role's description more specific without changing the Card/Role/Task structure. Show the before/after text and get a plain confirmation before the PATCH; no impact writeup needed.
8. For a new Card, show the entire draft and impact, obtain explicit approval, then use the existing API in dependency order: create/reuse Task -> create/reuse Role with `task_ids` -> create Card with `role_ids`. Re-read/report every returned ID; stop on a failed step rather than creating an orphaned structure.
9. Compute each Role's Skill closure before writing the profile JSON's `skills` field:
   1. Collect the entry-point Skill names named in the Role's Task description(s).
   2. Read each Skill's SKILL.md and extract every other Skill name it invokes via `Skill(...)` calls/chains.
   3. Repeat step 2 for each newly discovered name until no new name appears (fixed point).
   4. Populate the Role's `skills` field with the final closure set -- the whole set, not just the entry points.
   5. Show the computed set to the user and get confirmation before installing, at the same visibility level as the Card-change approval format.
10. Generate a reviewed profile and platform-specific installation plan. Show every target path and any conflict before writing.
11. If a **Structural pre-filter** ran in step 5, re-run it once more immediately before writing. A CRITICAL/HIGH finding that is new since step 5 means the profile about to be installed may no longer match the Card; surface it and pause rather than writing silently. Install only the confirmed platforms. Write the reviewed local JSON profile, then run `scripts/install_avatar.py --profile <approved-profile.json> --platform <claude|opencode|codex>` once for each selected platform. The installer refuses user-modified targets. At execution time, bind the current project as context; do not copy project data into the global profile. If a profile or platform target already exists (resync, not a fresh install), run the **Resync consistency check** below before writing.
12. Run toward a reviewable **draft final**. Ask for feedback, update the personal profile or propose a structural Card change, and re-run. Require a separate explicit approval for irreversible external writes.

## Readiness checklist

Do not offer install until each item is **explicitly** answered or the user deliberately marks it unavailable. Confirm item by item; a Card whose Role/Task text looks complete pre-answers none of these. Capture the concrete identifiers in parentheses -- a reference recorded by name only ("Jira", "Confluence") is not answered.

- **Trigger/start condition, cadence, and expected inputs** (e.g. weekly deadline day, quarterly review month; who/what triggers it)
- **Deliverable/output format and definition of done** (prefer pointing at an existing artifact to match)
- **Quality bar and review method**, plus **one representative good/bad example** (or an existing file that defines "good")
- **Decision rules, prohibitions, and escalation/approval boundary** (concrete thresholds and who performs the final external action) -- record the confirmed answer as the role's `approval_scope` (`none`/`external-write`/`all`) in the profile JSON; default to `external-write` unless the user explicitly asked for a different scope for that role.
- **Required Skills, MCP/tools, and access constraints** -- for each one referenced anywhere in the Card/Role/Task (a structured skill-component link *or* just a free-text mention), resolve it now per [`references/mcp-skill-setup.md`](references/mcp-skill-setup.md): confirm it is installed/reachable, or run the install/credential-interview steps there before offering install. A requirement is not "answered" until it is either working or explicitly marked unavailable with the user's stated reason -- naming it in the Card/Task text is not the same as it being installed.
- **Delegation scope**: may this avatar spawn or message further subagents itself (Claude Code `Agent`/`SendMessage`, or the platform equivalent)? Default to **no** -- `install_avatar.py` denies these on Claude Code unless the role sets `allow_delegation: true`. Only opt in when the task genuinely needs fan-out, and never to the avatar's own Card/role type; record the reason.
- **Knowledge references**: location/system of record, owner, purpose, sensitivity/exclusions, freshness, access method -- with the concrete identifiers the tools need (repo files to read at runtime, Jira project keys, Confluence space key, required env/credentials, report recipients, org/reporting line)

### Red flags -- STOP, you are skipping the checklist

- "The Card's Task text is detailed, so the checklist is covered."
- "The Skill is installed, so the avatar can do the work."
- "I'll fill the operational context after installing / during a trial run."
- Offering install with any item neither answered nor explicitly marked unavailable.
- Recording a knowledge reference by name only, without its concrete identifier and access method.

All of these mean: return to the interview and confirm each item before offering install.

| Rationalization | Reality |
|---|---|
| "Rich Card = ready" | Card = what/why. Checklist = how/for-whom (cadence, recipients, credentials, quality exemplars -- a different category of information). No matter how specific the Task prose is, it doesn't answer these. |
| "Skill installed = capable" | A Skill is a generic capability. Without cadence, recipients, project/space keys, and quality exemplars it emits generic output, not your part's work. |
| "Fill context later" | With the ask satisfied, later never comes and a shallow avatar ships. Elicit before install; mark true unknowns 'unavailable', not 'skip'. |
| "Leave delegation tools on, just in case" | An avatar with unrestricted `Agent`/`SendMessage` access recursively spawns its own subagent instead of doing the work -- the orchestrator then waits on a "완료" report with no actual result. Deny by default; enable only per confirmed need. |

### Structural pre-filter

For an existing Card (skip for a draft not yet created), call its `quality-evaluate` endpoint via `agent-factory-api` before working through the checklist above -- see that skill for the endpoint contract, status derivation, and the `code`-based dispatch rule. Call it with an empty body (`{}`); the interview wants every advisory-level finding, unlike a promotion gate that might set `include_advisory: false` to cut noise. Use each finding's `code` and `path` (e.g. `card.roles[0].tasks[2]`) to turn it into the specific question it implies rather than a generic one:

- `TASK_CONTEXT_MISSING` at a Task -> ask what triggers/starts that Task.
- `TASK_NO_SKILLS_AND_THIN_TEXT` -> ask to link a Skill or write out the procedure.
- `CARD_RESPONSIBILITY_MISSING` / `CARD_RESPONSIBILITY_TOO_NARROW` -> ask for the one responsibility, stated concretely.

This narrows the interview to what the endpoint cannot judge -- breadth, duplication, whether the prose is actually true -- not structural completeness it already checked. Two response conditions change this:

- **403 (forbidden):** the session's key is not this Card's owner or a co-manager. Fall back to reading the tree yourself for this session, and record in `decisions.md` that the automated pre-filter was unavailable and why -- do not silently treat the absence of a result as "no findings."
- **`CARD_ROLES_NOT_VISIBLE` / `ROLE_TASKS_NOT_VISIBLE` (INFO):** treat the checklist items any hidden Role/Task would have affected as still unanswered -- a clean result alongside either code covers only what was visible.

## Session-evidence update format

When a user asks to update an avatar from an Agent session, use this format before proposing a write:

```markdown
## Selected session evidence

- Scope read: [current conversation / user-selected file or location]
- Observed repeated work: ...
- Candidate role/task/profile improvements: ...
- Excluded sensitive material: ...

May I use this summary to propose the Card/profile diff? (yes/no)
```

Treat session evidence as a suggestion, not truth: ask the user to confirm inferred responsibilities, ownership, and quality standards. Do not include secrets, personal data, unrelated conversation details, or verbatim logs in the generated Card, profile, API payload, or final report.

## Card-change approval format

Use this exact format before a **restructuring** API write (add/delete/move/split/merge/relink), including a new Card. Plain Role/Task text elaboration only needs a before/after and a confirmation -- see step 7.

```markdown
## Avatar Card change proposal

### Structural diff / new draft

- [add/update/delete/move] ...

### Impact

- Affected roles/tasks: ...
- Installation/runtime effect: ...
- Reversal: ...

Approve this exact structural change? (yes/no)
```

For approved changes, re-read the target entity immediately before PATCH and send the minimum existing API fields. Report returned IDs and changed fields.

## MCP/Skill setup approval format

Use this exact format before running any `claude mcp add|remove|login`, `claude plugin install`, or `npx skills add` command, and before applying any credential value. See [`references/mcp-skill-setup.md`](references/mcp-skill-setup.md) for how to fill each field.

```markdown
## MCP/Skill setup proposal

### Requirement

- Referenced by: [Card/Role/Task name] -- [structured skill-component link / free-text mention]
- Kind: [mcp_server / skill]
- Name: ...

### Current state

- Detected: [not installed / installed, scope: local|user|project / installed but unreachable]
- If installed: reuse existing, or reinstall/reconfigure -- and why

### Proposed action

- Command: `claude mcp add ...` / `claude plugin install ...` / `npx skills add ...` (exact command; redact any secret value as `<REDACTED>`)
- Scope: [local (default) / user / project] -- least-global unless the user asked to escalate
- Credentials/config needed: [key names only, never values] -- obtained via: [user runs a `!`-prefixed command themselves / user pasted a value in chat and the assistant will run the command]

### Effect

- What this avatar/subagent gains access to: ...
- Reversal: `claude mcp remove <name>` / `claude plugin uninstall <name>`

Proceed with this exact action? (yes/no)
```

Never write the literal credential value into this block, the generated profile, a Card/Role/Task payload, or the final report.

## Install targets

Generate a profile under `~/.agent-factory/avatars/<card-slug>/` containing the profile, reference metadata, and a `decisions.md` decision log (see below). Then, after confirmation:

| Platform    | Subagent target                                                      |
| ----------- | -------------------------------------------------------------------- |
| Claude Code | `~/.claude/agents/agent-factory/<card-slug>-<role-slug>.md`          |
| OpenCode    | `~/.config/opencode/agents/agent-factory/<card-slug>-<role-slug>.md` |
| Codex       | `~/.codex/agents/<card-slug>-<role-slug>.toml`                       |

Read [`references/platform-adapters.md`](references/platform-adapters.md) before rendering. Verify current platform documentation when a field or global path is uncertain; do not invent config keys.

`scripts/install_avatar.py` accepts a local profile JSON with `card_slug`, `profile`, and `roles[]` (`slug`, `title`, `description`, and the optional `allow_delegation: bool`, `approval_scope: "none"|"external-write"|"all"`, and `skills: string[]`). `approval_scope` carries the confirmed escalation/approval-boundary answer into the installed agent's instructions -- omitted means `external-write` (ask before any irreversible external action); `all` demands approval before every action; `none` drops the approval sentence entirely and is only correct when the user explicitly asked for full automation of that role. Unless a role sets `allow_delegation: true`, the installer denies the `Agent` and `SendMessage` tools on the generated Claude Code subagent (see the Delegation-scope checklist item) so it cannot recursively spawn or message further subagents. `skills` must already be the computed transitive closure of Skills reachable from the Role's Task-named entry-point Skills -- not the entry-point names alone -- and it currently affects the Claude Code target only; the OpenCode and Codex targets do not yet render tool/Skill scoping. Omitting `skills` (or passing an empty list) scopes the Claude Code target to the base tool bundle with no `Skill(...)` suffix -- it never falls back to the harness default of full tool access. Use `--home <temporary-directory>` only for tests; omit it for the user's confirmed real installation.

### Decision log

Alongside `profile.json`, maintain `decisions.md` in the same `~/.agent-factory/avatars/<card-slug>/` directory: a timestamped log of each readiness-checklist item's **resolution and rationale** -- not a raw transcript, just enough for a future session to know what was decided and why without re-deriving or re-asking it. Append an entry as soon as a checklist item is resolved, even mid-interview; don't wait for the final write. `profile.json` stays lean and runtime-facing (what the installed subagent reads); `decisions.md` is provenance only, consulted by *you* during future onboarding/update sessions on this Card, never by the installed subagent itself.

## Backup and restore

`scripts/backup_avatar.py` freezes a server Card/Role/Task and/or its local install files into a
single `*.zip`, unmodified -- every server response is stored as the raw bytes received (no
re-serialization) and every local file is copied byte-for-byte, so the frozen content matches the
source exactly. `scripts/restore_avatar.py` reverses this: it can import the frozen server data
back into Agent Factory (create-or-update, never rewording any field) and/or restore the frozen
local files back to disk. Use this before a risky Card restructuring, or to recreate a Card/Role/Task
after a local fake-server reset that dropped its IDs.

```bash
python3 scripts/backup_avatar.py \
  --output ./backups/<card-slug>.zip \
  --scope both \
  --card-id <CARD_UUID> --card-slug <card-slug> --role-slug <role-slug> \
  --home ~ --base-url "$BASE"
```

`--scope` selects `server` (Card/Role/Task API responses only), `local` (installed profile/agent
files only), or `both` (default). Pass `--role-slug` once per role so the local install targets for
each role can be located; server-side roles/tasks are discovered automatically by walking the
Card's linked Role/Task tree.

`profile.md`/`decisions.md` always come from `--home`. The three platform subagent targets
(`.claude/agents/agent-factory/`, `.config/opencode/agents/agent-factory/`, `.codex/agents/`) come
from `--install-home` instead, which defaults to `--home` but can be pointed at a different
directory -- e.g. a project-scoped Claude Code install
(`<project>/.claude/agents/agent-factory/<card-slug>-<role-slug>.md`) instead of the global
`~/.claude/agents/agent-factory/`. Without a matching `--install-home`, those files are silently
absent from the zip (and from `manifest.json`'s `files` list) -- there's no error, since `_add`
only checks whether the target path exists under whichever root it was given.

```bash
python3 scripts/restore_avatar.py --zip ./backups/<card-slug>.zip --target both --mode auto
```

Without `--confirm`, this only previews what would change -- no API call or file write happens.
Add `--confirm` to actually apply it. `--target` selects `server` (import), `local` (restore), or
`both` (default, simultaneous). Local restore mirrors backup's home split: pass the same
`--install-home` used for backup so the platform subagent files land back in the project directory
they came from rather than under `--home`. `--mode` controls the server side only:

- `auto` (default): `GET` each frozen ID first -- if it still exists, `PATCH` it back to the frozen
  values (rollback in place); if not (e.g. the ID was lost to a server reset), `POST` a new
  Task -> Role -> Card in that dependency order and report the old-ID -> new-ID mapping.
- `create`: always `POST` new Task/Role/Card, ignoring whether the frozen IDs still exist.
- `update`: always `PATCH` the frozen IDs; raises if any no longer exists (no silent fallback to create).

Local restore refuses to overwrite a target whose current content differs from the frozen backup
(same conflict philosophy as `install_avatar.py`'s `_write`) unless `--force` is passed. This is a
**Card restructuring**-equivalent write when importing to the server -- show the plan (the
`--confirm`-less preview output) and get explicit approval per the Card-change approval format
above before adding `--confirm`.

## Resync consistency check

The server Task/Role/Card, the local profile (`~/.agent-factory/avatars/<card-slug>/profile.md`), and the installed platform subagent file are one record set, not three independent copies -- see `aiagent/AgentToolbox` repo's `docs/avatar-system/decisions/0014-three-source-consistency-for-installed-avatars.md` (ADR 0014) for the failure modes this prevents (a rule added to only one of the three silently disappears on the next resync or gets reverted by a stale server text). Before overwriting an existing profile/target:

1. Fetch the current server Task/Role text via `agent-factory-api` and diff it against the local profile.md and the installed platform file. Show the three-way diff to the user, not just server-vs-local.
2. If any side has a rule the others lack (e.g. a normalization/procedure rule that forces a specific Skill call), ask whether it should be promoted into the server Task text so it survives future installs elsewhere -- do not silently drop it by overwriting.
3. If the server Task text references a stale name (renamed Skill/agent/tool), flag it and offer to `PATCH` the correction as part of this resync, not as a separate follow-up that may never happen.
4. Only proceed with `install_avatar.py` once the user has confirmed which side wins for each conflicting line.

## Final response format

Always report: selected avatar, readiness gaps (including unresolved Structural pre-filter findings, when available) or confirmed profile, decision-log updates, Card changes (if any), MCP/Skill setup performed (kind, reused vs installed, scope -- never credential values), installed platforms/files, draft-final status, and the next approval required.
