# avatar-onboarding — 설치·사용 가이드

Agent Factory Avatar Card를 개인용 Claude Code/OpenCode/Codex 서브에이전트로
설치하는 스킬이다. 대화형 인터뷰를 통해 Card에 없는 운영 지식(호출 주기, 품질
기준, 필요 Skill/MCP, 자격증명 등)을 채운 뒤에만 설치를 제안한다 — 전체 절차는
[`skills/avatar-onboarding/SKILL.md`](skills/avatar-onboarding/SKILL.md)를 본다
(이 README와 같은 `plugins/avatar-onboarding/` 디렉터리를 기준으로 한 상대 경로).
이 문서는 설치부터 실제 호출까지 필요한 나머지 단계를 다룬다.

## 1. 설치 Quickstart

1. **API key 발급** — `https://agent.samsungds.net:3355/me/api-keys`에서
   `aft_` 접두 사용자 API key를 발급받아 `AGENT_FACTORY_API_KEY` 환경변수로
   export한다(대시보드용 `afd_` 키는 agent API에 쓸 수 없다). Card/Role/Task
   조회·생성에 필요하다 — 자세한 인증 절차는 `agent-factory-api` 스킬을 본다.
2. **스킬 설치**:
   ```text
   /plugin marketplace add https://github.samsungds.net/aiagent/skill.git
   /plugin install avatar-onboarding@skill
   /plugin install agent-factory-api@skill
   ```
   `avatar-onboarding`은 Card/Role/Task API 호출을 `agent-factory-api` 스킬에
   위임하므로 두 플러그인을 같이 설치한다.
3. **`/avatar-onboarding` 실행** — 대화창에서 스킬을 부르면 인터뷰가 시작된다.
   기존 Card를 고르거나 새 Card를 정의하고, readiness checklist(3절 참고)를
   답한 뒤 설치를 승인하면 진행된다.
4. **설치 산출물 확인** — 승인 후 다음 위치에 파일이 생긴다:

   | 위치 | 내용 |
   | --- | --- |
   | `~/.agent-factory/avatars/<card-slug>/profile.md` | 이 아바타의 개인 프로필(런타임이 읽는 본문) |
   | `~/.agent-factory/avatars/<card-slug>/decisions.md` | readiness checklist 각 항목의 결정 로그(사람이 읽는 이력, 런타임은 읽지 않음) |
   | `~/.claude/agents/agent-factory/<card-slug>-<role-slug>.md` | Claude Code 서브에이전트(Role마다 1개) |
   | `~/.config/opencode/agents/agent-factory/<card-slug>-<role-slug>.md` | OpenCode 대상(선택 시) |
   | `~/.codex/agents/<card-slug>-<role-slug>.toml` | Codex 대상(선택 시) |

5. **설치 검증** — 파일이 생겼는지 확인하고, 실제로 응답하는지 짧게 호출해본다:
   ```bash
   ls ~/.claude/agents/agent-factory/
   ```
   이어서 아래 2절의 호출 형식으로 한 번 불러 자기소개(프로필 경로, 담당 Role)를
   시키면 설치가 제대로 됐는지 확인된다.

## 2. 설치 후 호출법

- `<card-slug>`/`<role-slug>`는 Card/Role 이름을 소문자 kebab-case로 바꾼 값이다
  (공백·특수문자를 `-`로 치환) — 설치 시 실제 생성된 값은 4절 "설치 산출물 확인"의
  경로에서 그대로 확인할 수 있다.
- Role은 `@<card-slug>:<role-slug>` 형태로 부른다. 예: Card 슬러그가
  `weekly-report`이고 Role 슬러그가 `writer`면 `@weekly-report:writer`.
- **Role이 여러 개인 Card도 한 번에 하나씩만 부른다**(동시 호출 기능 없음) —
  순서가 있는 작업은 각 Role을 순서대로 호출한다.
- **Role 간 결과 전달**은 설치된 서브에이전트가 서로 직접 이어받지 않는다.
  기본적으로 `allow_delegation`이 꺼져 있어 설치된 서브에이전트는 `Agent`/
  `SendMessage`로 다른 서브에이전트를 부를 수 없다(재귀적으로 자기 자신의
  서브에이전트를 낳는 것을 막기 위한 기본값). 대신 **부모 세션이 중계**한다:
  `@card:role-a`의 출력을 받아 그 결과를 그대로 다음 호출 `@card:role-b`의
  입력으로 넘긴다. 두 Role이 항상 같은 순서로 이어져야 한다면 그 사실을 checklist
  인터뷰에서 밝혀 `decisions.md`에 기록해 둔다.

## 3. 실제 동작을 위해 추가로 해야 하는 것

Card를 설치했다고 바로 실제 업무를 하는 것은 아니다 — 아래를 다 채워야
"내 몫의 일"을 한다.

### readiness checklist 6항목

인터뷰 중 아래 6항목이 각각 **명시적으로 답변되거나 "unavailable"로 표시**되어야
설치가 제안된다(Card의 Task 설명이 자세해도 이 항목들을 대신 답해주지 않는다):

1. 트리거/시작 조건, 주기, 예상 입력
2. 산출물 형식과 완료 정의
3. 품질 기준과 리뷰 방법 + 대표 good/bad 예시
4. 의사결정 규칙, 금지사항, 승인 경계
5. 필요한 Skill/MCP/접근 제약
6. 위임 범위(다른 서브에이전트를 부를 수 있는지 — 기본 거부) + 지식 참조(위치·소유자·민감도·최신성·접근 방법)

전체 항목 정의는 [`SKILL.md`](skills/avatar-onboarding/SKILL.md)의
"Readiness checklist" 절을 본다.

### 연결된 Skill/MCP 설치

- Card/Role/Task가 참조하는 각 Skill/MCP는 [`references/mcp-skill-setup.md`](skills/avatar-onboarding/references/mcp-skill-setup.md)의
  절차로 하나씩 확인·설치된다 — Card에 이름이 적혀 있다고 설치된 것으로 간주하지
  않는다. 일괄 자동 설치는 의도적으로 지원하지 않는다: SKILL.md의 안전 원칙상
  설치/재구성마다 사용자의 명시적 승인이 필요하므로, 인터뷰 중 발견된 요구사항마다
  위 참조 문서의 절차를 밟아 개별적으로 승인해야 한다.

### credential 준비

MCP가 자격증명/설정을 요구하면, 시크릿 값은 채팅에 남기지 않는 것이 기본이다 —
사용자가 `!<command>`로 직접 실행하거나 이미 셸에 export해 둔 값을 승인 후
그대로 쓰게 한다. 어떤 키를 어디에 설정했는지만 `decisions.md`에 남고, 값 자체는
프로필·Card 페이로드·응답 어디에도 기록되지 않는다.
