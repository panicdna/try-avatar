---
name: agent-factory-api
description: Use when registering, updating, searching, or deleting Agent Factory assets through the agent REST API, including skills, avatar or agent cards, roles, tasks, task-skill links, skill versions, component visibility, aft_ API keys, or https://agent.samsungds.net:3355/api/docs.
---

# Agent Factory API

Use the Agent Factory agent API (`/api/v1/agent/*`) to manage skills, avatar cards, roles, and tasks.
The base URL is the internal deployment `https://agent.samsungds.net:3355`.

## Authentication

Before any API call:

1. Use `AGENT_FACTORY_API_KEY` from the environment if present.
2. If it is absent, ask the user to issue or copy a **user API key** from `https://agent.samsungds.net:3355/me/api-keys`.
3. Require an `aft_` key. Do not use `afd_` dashboard keys for the agent API.
4. Keep the key only in memory or a shell variable. Do not write it to files, commits, transcripts, or examples.
5. Verify it:

```bash
BASE="https://agent.samsungds.net:3355/api/v1/agent"
curl -sfS -H "Authorization: Bearer $AGENT_FACTORY_API_KEY" "$BASE/me"
```

Use `Authorization: Bearer <aft_key>` for all `/api/v1/agent/*` calls.

## Concepts

- **Agent Factory**: Internal marketplace and discussion hub for AI development assets. It catalogs reusable assets such as skills and uses the Avatar System to model real work contexts.
- **Skill**: A catalog item registered from a GitHub repo or ZIP. The server inspects the repo, extracts metadata/components, stores versions, and runs an asynchronous scan. Skills can be linked to avatar tasks by `skill_id` and optional `component_key`.
- **Avatar Card / Agent Card**: A work-partner profile with `name` and `responsibility`. A card links one or more roles and represents what an agent/avatar is responsible for.
- **Role**: A reusable work mode used to fulfill a card's responsibility. This is not an auth role. A role links one or more tasks.
- **Task**: The concrete work unit. It stores `title`, optional `context`, optional free-form `text`, and linked skill components.
- **Relationships**: card -> roles, role -> tasks, task -> skill components. Create or resolve lower-level IDs first when creating a linked structure.

## Avatar Card Guidance

Avatar Card(Agent Card)는 "이 아바타/에이전트가 어떤 책임을 맡는가"를 적는 최상위 프로필이다. 조직의 직급이나 권한(auth role)이 아니라, 사용자가 실제로 맡기는 책임과 그 책임을 수행하기 위한 역할 묶음이다.

When the user asks to make an avatar card:

1. Clarify the card's `name`: visible card/agent name, usually a concise noun phrase.
2. Clarify `responsibility`: the outcome or responsibility the avatar owns. Prefer a concrete business/work outcome over a tool name.
3. Decide whether roles already exist. If not, create tasks first, then roles, then the card.
4. Keep cards small enough to have one clear responsibility. If the user describes unrelated responsibilities, propose multiple cards.
5. Status is not settable via PATCH — the `AvatarCardPatch` schema does not include a `status` field. Cards are created in draft state by the server.

Minimum card creation needs only `name`; `responsibility`, `role_ids`, and `manager_emails` are optional:

```bash
curl -sS -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "name": "Release operations agent",
    "responsibility": "Prepare release communication assets.",
    "role_ids": [],
    "manager_emails": []
  }' \
  "$BASE/avatars/cards"
```

To attach roles, pass the complete desired role set in `role_ids` at create time or PATCH time:

```bash
curl -sS -X PATCH -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"role_ids": ["ROLE_UUID"]}' \
  "$BASE/avatars/cards/CARD_UUID"
```

Good card examples:

- `name`: "Release operations agent"; `responsibility`: "Prepare release communication assets for product releases."
- `name`: "Customer VOC analyst"; `responsibility`: "Turn incoming customer feedback into categorized insights and follow-up tasks."
- `name`: "PR quality reviewer"; `responsibility`: "Review pull requests for correctness, maintainability, and release risk."

Avoid vague cards like "AI assistant" or "Developer helper" unless the user provides a concrete responsibility. Convert vague requests into a focused responsibility before creating the card.

## Workflow

1. Search first before creating, especially for skills and reusable roles/tasks.
2. For edits, `GET` the current item first and `PATCH` only the fields the user asked to change.
3. For linked structures, create or find tasks first, then roles, then cards.
4. Report returned IDs, changed fields, and async scan status. For skill registration/resync, expect `scan_status: "pending"` initially.
5. Ask for explicit confirmation before `DELETE` unless the user already explicitly requested deletion.

## Endpoint Quick Reference

Set:

```bash
BASE="https://agent.samsungds.net:3355/api/v1/agent"
AUTH="Authorization: Bearer $AGENT_FACTORY_API_KEY"
```

| Resource             | Endpoints                                                                                         |
| -------------------- | ------------------------------------------------------------------------------------------------- |
| Me                   | `GET /me`                                                                                         |
| Skill                | `GET /skills?q=&category=&tag=&cursor=&limit=` · `POST /skills` · `POST /skills/upload`          |
|                      | `GET/PATCH/DELETE /skills/{item_id}`                                                              |
|                      | `POST /skills/{item_id}/resync` (repo) · `POST /skills/{item_id}/resync-zip` (ZIP multipart)     |
| Skill versions       | `GET /skills/{item_id}/versions` · `POST /skills/{item_id}/versions/auto`                        |
|                      | `POST /skills/{item_id}/versions/{version_id}/serve`                                              |
| Skill archive        | `GET /skills/{item_id}/archive`                                                                   |
| Component visibility | `PATCH /skills/{item_id}/components/{component_key}/visibility`                                   |
| Avatar/Agent Card    | `GET /avatars/cards?scope=mine\|team` · `POST /avatars/cards`                                    |
|                      | `GET/PATCH/DELETE /avatars/cards/{card_id}`                                                       |
| Role                 | `GET /avatars/roles?scope=mine\|team` · `POST /avatars/roles`                                    |
|                      | `GET/PATCH/DELETE /avatars/roles/{role_id}`                                                       |
| Task                 | `GET /avatars/tasks?scope=mine\|team` · `POST /avatars/tasks`                                    |
|                      | `GET/PATCH/DELETE /avatars/tasks/{task_id}`                                                       |

Detailed interactive docs are at `https://agent.samsungds.net:3355/api/docs`.

## Payloads

Register a skill from a repo:

```bash
curl -sS -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/org/repo",
    "category": "ai-productivity",
    "tags": ["git", "automation"],
    "path": null,
    "scope_type": "team",
    "private_component_paths": []
  }' \
  "$BASE/skills"
```

Register a skill from ZIP:

```bash
curl -sS -H "$AUTH" \
  -F "file=@skill.zip" \
  -F "category=ai-productivity" \
  -F "tags=git,automation" \
  -F "summary=Short summary" \
  -F "scope_type=team" \
  -F "private_paths=" \
  "$BASE/skills/upload"
```

Create linked task, role, and card:

```bash
curl -sS -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "title": "Weekly changelog draft",
    "context": "Run every Friday before release notes",
    "text": "Collect merged PRs, group by user impact, draft concise release notes.",
    "skills": [{"skill_id": "SKILL_UUID", "component_key": null}],
    "manager_emails": []
  }' \
  "$BASE/avatars/tasks"

curl -sS -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "title": "Release note writer",
    "description": "Turns engineering changes into clear release notes.",
    "task_ids": ["TASK_UUID"],
    "manager_emails": []
  }' \
  "$BASE/avatars/roles"
# Note: both title and description are required for role creation.

curl -sS -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "name": "Release operations agent",
    "responsibility": "Prepare release communication assets.",
    "role_ids": ["ROLE_UUID"],
    "manager_emails": []
  }' \
  "$BASE/avatars/cards"
```

Patch examples:

```bash
curl -sS -X PATCH -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"short_description": "Drafts release notes from merged PRs", "tags": ["release", "writing"]}' \
  "$BASE/skills/SKILL_UUID"

curl -sS -X PATCH -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"role_ids": ["ROLE_UUID"], "status": "active"}' \
  "$BASE/avatars/cards/CARD_UUID"

curl -sS -X PATCH -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"discoverable": false}' \
  "$BASE/skills/SKILL_UUID/components/COMPONENT_KEY/visibility"
```

## Resync Skills

Resync re-ingests the skill from its source, updating name, summary, README, license, and components from the source. User-curated fields (category, tags, visibility) are preserved.

From the original repo:

```bash
curl -sS -X POST -H "$AUTH" "$BASE/skills/SKILL_UUID/resync"
```

From a new ZIP (replaces source ZIP, creator/admin only):

```bash
curl -sS -X POST -H "$AUTH" \
  -F "file=@updated-skill.zip" \
  "$BASE/skills/SKILL_UUID/resync-zip"
```

Both return `{"skill_id": "...", "scan_status": "pending"}`.

## Response Schemas

### Skill

`POST /skills` → **201**:
```json
{"skill_id": "uuid", "scan_status": "pending"}
```

`GET /skills` → **200**:
```json
{"items": [SkillSummary], "next_cursor": "string|null"}
```

`GET /skills/{item_id}` → **200**:
```
id*            string
short_id       string|null
name*          string
short_description  string|null
category*      string
tags*          array[string]
scan_status*   string   — pending|unverified|passed|warning|failed
version_label  string|null
owner          {user_id*, email, display_name}
title          string|null
description    string|null
license        string|null
components     array[{key*, name*, short_description, discoverable*}]
scenarios      array
archive_url*   string
```

**SkillSummary** (list item):
```
id*, short_id, name*, short_description, category*, tags*, scan_status*, version_label, owner{user_id*, email, display_name}
```

### Avatar Card

`POST /avatars/cards` → **201** · `GET /avatars/cards/{card_id}` → **200**:
```
id*              string
name*            string
responsibility   string|null
roles            array[{avatar_role_id*, title*, task_count}]
manager_emails   array[string]
```

### Role

`POST /avatars/roles` → **201** · `GET /avatars/roles/{role_id}` → **200**:
```
id*              string
title*           string
description*     string
team_id          string|null
owner_user_id*   string
tasks            array[{avatar_task_id*, title*}]
manager_emails   array[string]
```

### Task

`POST /avatars/tasks` → **201** · `GET /avatars/tasks/{task_id}` → **200**:
```
id*              string
title*           string
context          string|null
text             string|null
team_id          string|null
owner_user_id*   string
skills           array[{skill_id*, component_key*, component_name*}]
manager_emails   array[string]
```

## Patch Semantics

- Omitted fields are preserved.
- `null` usually means "preserve" for non-nullable scalar fields such as `name`, `title`, and `category`; do not send `null` unless clearing is explicitly supported.
- Relationship arrays reconcile the whole set when sent:
  - `role_ids: []` removes all roles from a card.
  - `task_ids: []` removes all tasks from a role.
  - `skills: []` removes all skill links from a task.
  - `manager_emails: []` removes all co-managers; omitted keeps existing managers.
- `status` is **not patchable** on avatar cards via this API — the `AvatarCardPatch` schema has no `status` field.
- Skill `item_id` accepts UUID or `short_id`; avatar card/role/task IDs must be UUIDs.

## Common Errors

| Status/detail                                                                  | Meaning and action                                                                        |
| ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| `401 unauthenticated`                                                          | Missing, revoked, or wrong API key. Ask the user to issue a new `aft_` key.               |
| `403 creator_only`                                                             | API key owner is not the skill creator. API-key calls are not elevated admin calls.       |
| `403 forbidden`                                                                | Caller is neither owner nor co-manager for the avatar resource.                           |
| `404 *_not_found`                                                              | ID typo, not visible to this user/team, or missing resource. Re-list and verify IDs.      |
| `404 component_not_found`                                                      | The task references a missing or non-discoverable skill component.                        |
| `409 duplicate_source_repo_url`                                                | Repo is already registered in the conflicting scope. Patch or resync the existing skill.  |
| `409 skill_in_use_by_avatar_task`                                              | Skill cannot be deleted while tasks reference it. Unlink first.                           |
| `422 component_key_required`                                                   | Bundle skill needs an explicit `component_key`. Read skill detail and choose a component. |
| `422 not_a_skill_repo`, `invalid_zip`, `repo_too_large`, `too_many_components` | Registration input is invalid. Surface the exact detail to the user.                      |
| `429` with `Retry-After`                                                       | Creation quota or upstream rate limit. Tell the user when to retry.                       |

## Connectivity Troubleshooting

`https://agent.samsungds.net:3355` 은 삼성DS 사내망 도메인이다. 사내망/VPN 이 붙어 있고 사내 CA 가 신뢰 저장소에 있어야 접근할 수 있다. 요청이 실패하면 아래 순서로 확인한다.

1. **DNS 해석 확인** — 사내망 밖(해외 법인 포함)에서는 도메인 자체가 안 풀리는 경우가 많다.

   ```bash
   nslookup agent.samsungds.net
   ```

   실패하면 사내 VPN/Zscaler 접속 여부를 먼저 확인한다.

2. **포트 도달 여부** — `3355` 는 비표준 포트라 지역 프록시/방화벽에서 막힐 수 있다.

   ```bash
   nc -zv agent.samsungds.net 3355
   curl -v https://agent.samsungds.net:3355/api/docs
   ```

3. **TLS 인증서 검증 실패** — `unable to verify`, `self-signed certificate in chain`, `SSL certificate problem` 같은 메시지는 사내 사설 CA 가 신뢰 저장소에 없어서 발생한다. 근본 해결은 사내 CA 를 설치하는 것이다.
   - macOS: 사내 CA `.crt` 를 System 키체인에 추가하고 "Always Trust" 로 설정.
   - Linux: `/usr/local/share/ca-certificates/` 에 `.crt` 를 두고 `sudo update-ca-certificates`.
   - Windows: 사내 CA 를 "신뢰할 수 있는 루트 인증 기관" 저장소에 설치.
   - Node/npm 도구(`npx skills` 등): `export NODE_EXTRA_CA_CERTS=/path/to/ds-ca.crt`.
   - Python `requests`/`httpx`: `export REQUESTS_CA_BUNDLE=/path/to/ds-ca.crt` 또는 `SSL_CERT_FILE`.
   - curl: 시스템 CA 번들에 추가하거나 `curl --cacert /path/to/ds-ca.crt ...`.

   진단용으로만 임시 우회할 수 있다 (실사용 금지):

   ```bash
   curl -k https://agent.samsungds.net:3355/api/docs           # curl
   NODE_TLS_REJECT_UNAUTHORIZED=0 npx skills add ...           # node
   ```

4. **프록시 환경 변수 충돌** — `HTTP_PROXY`/`HTTPS_PROXY` 가 외부용 프록시로 설정돼 있으면 사내 도메인이 오히려 안 뚫린다. 사내 도메인을 `NO_PROXY` 에 추가하거나 세션에서 잠시 해제한다.

   ```bash
   env | grep -i proxy
   export NO_PROXY="agent.samsungds.net,$NO_PROXY"
   ```

## Safety Rules

- Never expose the API key in final answers, code snippets with real values, saved shell history, or files.
- Prefer `GET` + minimal `PATCH` over reconstructing entire objects from memory.
- Treat delete operations as destructive even when links are cascaded.
- Use `https://agent.samsungds.net:3355/api/docs` or `packages/api-client/openapi.json` to confirm fields if the API has changed.
