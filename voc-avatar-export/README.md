# VoC 자동 해결 파트너 — export 번들 (3-Role 설계, 2026-08-27 / 2026-08-28 재수출)

Agent Factory 공식 export 기능이 아닌 개인 백업/재현용 번들입니다(Card/Role/Task용
import/export API가 없음 — `agent-factory-api` 스킬 문서 기준).

> **2026-08-28 갱신**: 소유 계정을 admin 테스트 계정에서 한동구(panicdna@gmail.com)
> 계정으로 옮기면서(API에 소유권 이전이 없어 재생성+기존 삭제 방식) Card/Role/Task
> ID가 전부 바뀌었습니다. 이 폴더의 JSON 7개는 새 ID 기준으로 다시 export한
> 최신본입니다 — 내용(title/description/context/text)은 이전과 동일, ID·
> owner_user_id·team_id만 바뀌었습니다.

## 안에 든 것

| 파일 | 내용 |
|---|---|
| `card.json` | Card "VoC 자동 해결 파트너" |
| `role_operator.json` | Role "운영자" — 판단·이력 관리, 사람과 대화하는 유일한 Role |
| `role_monitor.json` | Role "VoC Hub 모니터" — 감시·발송 실행 전담 |
| `role_resolver.json` | Role "자동 해결자" — GitHub PR 전담 |
| `task_operator_decision.json` | Task "VoC 처리 판단·실행·이력 관리" |
| `task_monitor_watch.json` | Task "배정 VoC 감시·보고·발송 실행" (`voc-hub-responder` 연결) |
| `task_resolver_pr.json` | Task "GitHub 기반 자동 수정 및 PR 발행" |
| `skill_voc_hub_skills.json` | 연결된 Skill 스냅샷 (모니터에만 연결됨) |
| `reimport.sh` | Task→Role→Card 순서로 재생성하는 스크립트(파일명 접두사 기반이라 이 세트 그대로 동작) |
| `README.md`(이 파일) / `voc-avatar-framework-intro.md` | 설계 배경·다이어그램(프로젝트 루트 README.md 사본) |

## 나중에 import하려면

```bash
cd voc-avatar-export
export AGENT_FACTORY_API_KEY=<대상 서버의 aft_ 키>
export BASE="http://127.0.0.1:9090/api/v1/agent"
bash reimport.sh
```

- 원본 ID는 재사용되지 않음(서버가 새 ID 발급).
- Task가 참조하는 skill_id(`voc-hub-skills`, 이 스냅샷 기준
  `6c702480-9655-4f3e-b828-756e71b5b7f6`)가 대상 서버에도 있어야 함 — 스크립트가
  먼저 확인. **이 ID는 fake 서버 재시작에 안정적이지 않은 것으로 확인된 바 있음**
  (`skill_voc_hub_skills.json` 참고, 재사용 전 `GET /skills/{id}`로 생존 확인 권장).
- 이 번들은 **Agent Factory 카탈로그(설계)** 를 담고 있다. 로컬 subagent 파일
  자체(`~/.claude/agents/agent-factory/voc-avatar-{operator,monitor,resolver}.md`)는
  이미 설치돼 있지만, 3개 Role이 **자동으로 서로 메시지를 주고받는 것은 아니다**
  — 지금은 사람이 매번 맞는 `@voc-avatar-*`를 직접 호출해 중계한다(자세한 내용은
  `voc-avatar-framework-intro.md` 7절 참고).
