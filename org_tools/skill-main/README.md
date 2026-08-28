# skill

동료들과 함께 쓰는 Claude Code **플러그인 마켓플레이스**다. 대부분의 플러그인은
**자기 자신의 GHE 레포(`jemings/<name>`)를 가리키는 외부 `source`**로 등록되어
있어, 원작자가 자기 레포에서 그대로 독립적으로 계속 유지보수한다 — `aiagent/skill`은
그런 스킬들의 "설치 지점"만 하나로 모아주는 역할이다. 일부 플러그인(예:
`avatar-onboarding`)은 예외적으로 `plugins/<name>/`에 파일을 직접 담아 이 레포에서만
유지보수된다 — 어느 쪽인지는 아래 표의 "유지보수" 칸을 본다.

| Skill | Plugin | 유지보수 | 설명 |
| --- | --- | --- | --- |
| **skill-cure** | `skill-cure` | [jemings/skill-cure](https://github.samsungds.net/jemings/skill-cure) (외부) | 스킬/레포에 대한 보안 스캔(SAST) 결과를 진단 유형별로 검증된 수정 방법에 연결해 remediation한다. |
| **statusline-kit** | `statusline-kit` | [jemings/statusline-kit](https://github.samsungds.net/jemings/statusline-kit) (외부) | 현재 환경의 Claude Code statusline(모델·cwd/branch·컨텍스트 사용량·세션 토큰 합계)을 새 환경에도 동일하게 설치한다. |
| **agent-clinic** | `agent-clinic` | [jemings/agent-clinic](https://github.samsungds.net/jemings/agent-clinic) (외부) | 비대해진 CLAUDE.md/AGENTS.md 정리, 공개 문서와 코드 간 불일치 재동기화, 커밋된 에디터 설정 정리, 끝난 플래닝 산출물 정리. |
| **resolve-conflict** | `resolve-conflict` | [jemings/resolve-conflict](https://github.samsungds.net/jemings/resolve-conflict) (외부) | upstream과 동기화할 때 발생하는 머지 충돌 및 조용한 auto-merge 불일치를 해결한다. |
| **git-sweep** | `git-sweep` | [jemings/git-sweep](https://github.samsungds.net/jemings/git-sweep) (외부) | 이미 머지된(스쿼시 머지 포함) worktree/브랜치를 병합 근거와 함께 찾아 정리한다. |
| **gateway-migration** ¹ | `gateway-migration` | [jemings/gateway-migration](https://github.samsungds.net/jemings/gateway-migration) (외부) | System LSI사업부 LLM Gateway 전환(2026-08-18) 무인 셋업 스킬. |
| **aws-login** | `aws-login` | [jemings/aws-login](https://github.samsungds.net/jemings/aws-login) (외부) | AWS SSO 자격증명 만료로 반복 로그인하는 문제를 자동 갱신 설정으로 해결한다. |
| **github-workflow** | `github-workflow` | [jemings/github-workflow](https://github.samsungds.net/jemings/github-workflow) (외부) | GitHub Issue 기반 작업 세션 워크플로우 — 이슈 선택→worktree→브랜치→테스트→PR→Project 보드 상태 자동화. |
| **skill-optimizer** | `skill-optimizer` | [jemings/skill-optimizer](https://github.samsungds.net/jemings/skill-optimizer) (외부) | SKILL.md를 동작·트리거·정보 손실 없이 토큰 효율적으로 슬림화·구조 최적화한다. |
| **plugin-packager** | `plugin-packager` | [jemings/plugin-packager](https://github.samsungds.net/jemings/plugin-packager) (외부) | 스킬/레포를 `/plugin` 설치 가능한 마켓플레이스·플러그인으로 패키징하고 실제 설치까지 검증한다(GHES 포함). |
| **avatar-onboarding** ² | `avatar-onboarding` | `plugins/avatar-onboarding/` (이 레포에서 직접) | Agent Factory Avatar Card를 개인용 Claude Code/OpenCode/Codex 서브에이전트로 설치한다. |
| **agent-factory-api** ² | `agent-factory-api` | `plugins/agent-factory-api/` (이 레포에서 직접) | Agent Factory agent REST API(스킬·아바타/에이전트 카드·역할·태스크·`aft_` API 키 등)를 등록·조회·수정·삭제한다. |
| **bedrock-cost-report** ² | `bedrock-cost-report` | `plugins/bedrock-cost-report/` (이 레포에서 직접) | 월별 Claude Code/AWS Bedrock 비용을 자기 계정 기준으로 자동 조회해 모델·프로젝트·날짜별 breakdown과 효율 지표·절감 인사이트가 담긴 HTML 리포트로 만든다. |

¹ `gateway-migration`은 2026-08-18 특정 전환 시점에 맞춘 1회성 셋업 스킬이다. 전환이
지난 뒤에도 참고용으로 남겨둔다.

² `avatar-onboarding`, `agent-factory-api`, `bedrock-cost-report`는 원래 저장소를
폐기하고 이 레포로 하드카피되었다 — 앞으로 각자 `plugins/<name>/`에서 직접
수정·버전업한다. `avatar-onboarding`의 `SKILL.md`는 `agent-factory-api`를 스킬
이름으로 참조하도록 고쳐졌다(설치 시 두 플러그인이 같은 디렉터리에 나란히 놓이지
않으므로 상대 경로 참조는 쓸 수 없다).

## 설치

```text
/plugin marketplace add https://github.samsungds.net/aiagent/skill.git
/plugin install skill-cure@skill
/plugin install statusline-kit@skill
/plugin install agent-clinic@skill
/plugin install resolve-conflict@skill
/plugin install git-sweep@skill
/plugin install gateway-migration@skill
/plugin install aws-login@skill
/plugin install github-workflow@skill
/plugin install skill-optimizer@skill
/plugin install plugin-packager@skill
/plugin install avatar-onboarding@skill
/plugin install agent-factory-api@skill
/plugin install bedrock-cost-report@skill
```

원하는 플러그인만 골라서 설치하면 된다 — 서로 완전히 독립적이다. 설치 후 새 스킬이
안 보이면 플러그인을 다시 로드(`/reload-plugins`)한다.

## 이미 설치한 플러그인의 새 버전 받기

각 스킬은 원본 레포의 `main` 브랜치를 그대로 추적한다(커밋 고정 없음). 원작자가
자기 레포에 push하는 즉시 이 마켓플레이스가 별도로 손댈 일은 없지만, 이미 설치한
쪽에서 실제로 새 버전을 받으려면 다음을 실행해야 한다:

```text
/plugin marketplace update skill
/plugin update <name>@skill
```

## 새 스킬 등록하기

레포 유지보수 규칙은 [CLAUDE.md](CLAUDE.md)를 참고한다.
