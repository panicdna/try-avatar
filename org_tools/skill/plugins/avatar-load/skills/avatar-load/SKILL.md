---
name: avatar-load
description: Query Agent Factory avatar cards and install as local skills.
version: 0.3.0
author: Jemings Ko
license: Apache-2.0
metadata:
  hermes:
    tags: [Avatar, Agent-Factory, Skill-Generator]
    related_skills: [agent-factory-api, avatar-onboarding]
---

# Avatar Load

Load an Avatar Card from the Agent Factory, read its full Card/Role/Task tree,
and install it as **local skills** under `~/.hermes/skills/avatars/`.

The avatar's procedural knowledge becomes lazy-loaded skills — only triggered
when needed, not injected into every API call. Identity summary goes to memory.

## Prerequisites

- `agent-factory-api` skill must be installed (for API base URL, auth, endpoints).
- `AGENT_FACTORY_API_KEY` environment variable must be set (an `aft_` key).

## Directory layout after install

```
~/.hermes/skills/avatars/
  <card-safe-name>/
    meta/                        # one skill summarizing the whole avatar
      SKILL.md                   # identity + index of all task skills
    <role-safe-name>-task-<N>/   # one skill per task
      SKILL.md                   # full Task text + linked skill references
    linked-skills/               # linked skills fetched from Agent Factory
      <linked-skill-name>/
        SKILL.md
```

Names preserve Korean: `claude-code-디렉터/`, `claude-code-위임-및-적대적-리뷰-task-1/`, etc.

## Workflow

### 1. List avatars

Call `GET /avatars/cards?scope=mine` (or `?scope=team`) via `agent-factory-api`.
Display each card's name, responsibility, and role count.

### 2. Select avatar

Ask the user to choose one card by name or ID. If the user specifies a card name
in the prompt, use that directly — search by `GET /avatars/cards?scope=mine`
and match on `name`.

### 3. Fetch the Card

`GET /avatars/cards/{card_id}` — returns the card with its linked roles.

### 4. Fetch each Role

For each role, `GET /avatars/roles/{role_id}` — returns the role with its tasks.

### 5. Fetch each Task

For each task, `GET /avatars/tasks/{task_id}` — returns full task including
`title`, `context`, `text`, and **`skills`** (linked skill IDs).

### 6. Fetch linked skills (if any)

If the task's `skills` array is non-empty, fetch each linked skill and
install it locally. Use `GET /skills/{skill_id}` (NOT `/avatars/skills/`):

```
For each skill_id in task.skills:
  GET /skills/{skill_id}
  → Install to ~/.hermes/skills/avatars/<card-safe-name>/linked-skills/<name>/SKILL.md
```

If `GET /skills/{skill_id}` returns 404, the skill may be a **bundle component**
(e.g. inside "Skill Hub"). In that case:

1. List skills with `GET /skills?limit=100&cursor=` and paginate using
   `next_cursor` from the response until you find a bundle skill that contains
   the target `component_key` in its `components` array.
2. Read the bundle skill detail (`GET /skills/{bundle_id}`) to get
   `components[].key` and `components[].archive_url`.
3. Download the component archive and extract the SKILL.md, or record the
   component_key in the task skill's `prerequisites` and notify the user.

If a linked skill is still not found after checking bundles, record its ID in
the task skill's `prerequisites` and notify the user — do NOT fail the install.

### 7. Generate directory names and skill names

Preserve original names (including Korean) — only sanitize characters that
are unsafe for filesystems. This keeps directory names self-documenting:

```python
import re, unicodedata
def safe_name(name):
    # 1. NFC normalize (combine hangul jamo)
    s = unicodedata.normalize('NFC', name)
    # 2. Keep letters, numbers, spaces, hyphens, underscores; replace everything else with '-'
    result = []
    for c in s:
        if c.isalnum() or c == ' ' or c == '-' or c == '_':
            result.append(c)
        else:
            result.append('-')
    s = ''.join(result)
    # 3. Replace spaces with hyphens; collapse consecutive hyphens
    s = s.replace(' ', '-')
    s = re.sub(r'-+', '-', s)
    # 4. Trim leading/trailing hyphens; fallback to 'item' if empty
    return s.strip('-') or 'item'
```

Examples (Korean preserved):
- "Claude Code 디렉터" → `claude-code-디렉터`
- "Claude Code 위임 및 적대적 리뷰" → `claude-code-위임-및-적대적-리뷰`
- "Issue 스펙 작성 및 Claude Code 위임" → `issue-스펙-작성-및-claude-code-위임`
- "PR 코드 리뷰 및 품질 관문" → `pr-코드-리뷰-및-품질-관문`
- "위임 패턴 복기 및 개선" → `위임-패턴-복기-및-개선`

**Collision handling (rare):** Because Korean characters are preserved,
collisions are unlikely. But if two names still produce the same slug,
resolve before writing any files:

1. **Role slugs within a Card:** keep the first role's slug unchanged;
   append `-2`, `-3`, ... to later duplicates.
2. **Task directory names:** the directory is always
   `<role-safe-name>-task-<N>` (1-based position within the role's task list),
   so directory names are inherently unique.
3. **Task `name:` field in SKILL.md frontmatter:** compute `safe_name(task.title)`
   for each task. If two tasks in the same role collide, append `-2`, `-3`,
   ... to later duplicates (directory name is unaffected by rule 2).

### 8. Create task skills

For each task, you MUST call `write_file` with `path` set to
`~/.hermes/skills/avatars/<card-safe-name>/<role-safe-name>-task-<N>/SKILL.md` and
`content` set to the full Markdown below (filled in for that task). Writing
out the template below in your response is not enough — the file only exists
once `write_file` has actually been invoked and returned success. Do this for
every task before moving to step 9; do not batch or skip any.

For the `description`, write a concise English summary (≤60 chars) so the
agent can match English user requests to Korean-named skills.

For the `tags`, include the original card/role names **plus English keywords**
(e.g. `["GitHub", "delegation", "code-review", "PR"]`) so the skill is
discoverable regardless of the user's language.

```markdown
---
name: <slugified-task-name>
description: <English summary, max 60 chars, e.g. "Write issue specs and delegate to Claude Code">
version: 0.1.0
author: Jemings Ko
license: Apache-2.0
metadata:
  hermes:
    tags: [<card-name>, <role-name>, <english-keywords>]
    related_skills: [<comma-separated linked skill names from skills array>]
    prerequisites: [<linked skill names if they have external deps>]
    avatar_source:
      card_id: <card_id>
      role_id: <role_id>
      task_id: <task_id>
      card_name: <card name>
      last_loaded: "<ISO 8601 timestamp>"
---

# Task: <Task title>

<context from Task>

---

<Task text>
```

### 9. Create meta skill

You MUST call `write_file` with `path` set to
`~/.hermes/skills/avatars/<card-safe-name>/meta/SKILL.md` and `content` set to the
full Markdown below. As in step 8, the meta skill is not created until
`write_file` has actually run and returned success — do not stop at
describing what the file should contain.

Same rules as task skills: `description` in English, `tags` include English
keywords for cross-language discoverability.

```markdown
---
name: avatar-<card-safe-name>
description: <English summary, max 60 chars ending with period>
version: 0.1.0
author: Jemings Ko
license: Apache-2.0
metadata:
  hermes:
    tags: [avatar]
    related_skills: [<list all task skill names>]
    avatar_source:
      card_id: <card_id>
      card_name: <card name>
      role_count: <N>
      task_count: <N>
---

# Avatar: <Card name>

<Responsibility>

## Roles and Tasks

| Role | Task | Skill |
|------|------|-------|
| <role title> | <task title> | `avatar-<card-safe-name>/<role-safe-name>-task-<N>/` |

## How to use

Load this skill when you need to perform the avatar's responsibilities.
The table above lists all task skills — load the specific one you need.
```

### 10. Verify files were written

Before touching memory, confirm every `write_file` call from steps 8-9 actually
landed on disk — do not skip this even if the earlier calls reported success:

1. List all files under `~/.hermes/skills/avatars/<card-safe-name>/` (e.g. via
   `list_files` or an equivalent directory listing call).
2. Confirm the count of `SKILL.md` files found equals `1 (meta) + <total task
   count across all roles>`. If any are missing, go back to step 8 or 9 and
   `write_file` the missing one(s).
3. For each `SKILL.md` found, confirm it is non-empty (non-zero size, or read
   it back and confirm the content is not blank). A `SKILL.md` with 0 bytes
   means the `write_file` call did not actually execute — retry it.
4. Only proceed to step 11 once every expected `SKILL.md` exists and is
   non-empty. Do not report success to the user until this check passes.

### 11. Save identity to memory

Save **only** an identity summary to memory:

```
memory(target="memory", action="add", content="<Card name> avatar installed. Roles: <count>, Tasks: <count>. Use avatar-load to reload or skill_manage to list.")
```

If the avatar is already loaded (memory entry exists), use `action="replace"` with
the `old_text` matching the previous entry.

### 12. Report

Confirm:
- Which avatar was loaded
- How many roles/tasks were installed as skills
- How many linked skills were fetched
- Path to the meta skill (`~/.hermes/skills/avatars/<card-safe-name>/meta/`)

## Re-installing an existing avatar

If the avatar was previously loaded and the user wants to reload:

1. Check `~/.hermes/skills/avatars/<card-safe-name>/` — if it exists, remove it first
   (`rm -rf ~/.hermes/skills/avatars/<card-safe-name>/`)
2. Re-fetch from Agent Factory (steps 3-11)
3. This ensures the skills reflect the latest server-side changes

## What to extract from each Task text

From the Task's `text` field, extract into the skill SKILL.md:

1. **Tools and commands** — specific CLI commands, API endpoints, file paths, environment variables
2. **Decision rules** — conditional logic, approval boundaries, escalation thresholds
3. **Pitfalls and gotchas** — common mistakes, failure modes, workarounds
4. **Workflows** — numbered step-by-step procedures, ideal flows
5. **Quality criteria** — checklists, acceptance criteria, verification commands

## What NOT to do

- Do NOT install the avatar to Claude Code/OpenCode/Codex platforms (that is `avatar-onboarding`'s job).
- Do NOT modify Card/Role/Task server data.
- Do NOT ask for explicit confirmation on every skill created — create them all and report once.
- Do NOT store Task knowledge in memory (memory is only for identity summary).
- Do NOT scan or enumerate the user's session history or home directory.

## Example usage

```
User: "Load the Claude Code 디렉터 avatar"

Agent:
1. Lists avatars: "Found 6 cards. Which one?"
2. User: "Claude Code 디렉터"
3. Agent fetches card → 1 role → 3 tasks → 0 linked skills
4. Agent creates skills:
   ~/.hermes/skills/avatars/claude-code-디렉터/meta/SKILL.md
   ~/.hermes/skills/avatars/claude-code-디렉터/claude-code-위임-및-적대적-리뷰-task-1/
   ~/.hermes/skills/avatars/claude-code-디렉터/claude-code-위임-및-적대적-리뷰-task-2/
   ~/.hermes/skills/avatars/claude-code-디렉터/claude-code-위임-및-적대적-리뷰-task-3/
5. Agent saves identity to memory
6. Agent reports: "Loaded 'Claude Code 디렉터' — 1 role, 3 tasks installed as skills under ~/.hermes/skills/avatars/claude-code-디렉터/"
```