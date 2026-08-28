# VoC 자동 해결 파트너 — export 번들

이 zip은 Agent Factory의 공식 export 기능이 아니라 개인 백업/재현용 번들입니다.
Agent Factory API(`agent-factory-api` 스킬 문서 기준)엔 **Skill 전용 `archive`
엔드포인트만 있고, Card/Role/Task용 import/export 엔드포인트는 없습니다.**

## 안에 든 것

| 파일 | 내용 |
|---|---|
| `card.json` | Card "VoC 자동 해결 파트너" 전체 (원본 서버에서 재조회한 스냅샷) |
| `role_1_auto_resolve_ops.json` | Role "VoC Hub 자동 해결 운영" |
| `role_2_operator.json` | Role "운영자" |
| `role_3_monitor.json` | Role "모니터" |
| `task_1_auto_resolve.json` | Task "배정된 VoC 자동 해결" |
| `task_2_manual_triage.json` | Task "VoC Hub 수동 트리아지" |
| `task_3_monitor_report.json` | Task "VoC 자동 해결 이력·통계 리포트" |
| `skill_voc_hub_skills.json` | 연결된 Skill "voc-hub-skills" (컴포넌트 `voc-hub-responder`) 스냅샷 |
| `reimport.sh` | 아래 Task→Role→Card 순서로 재생성하는 스크립트 |

## 나중에 import하려면

```bash
cd voc-autoresolve-avatar-export
export AGENT_FACTORY_API_KEY=<대상 서버의 aft_ 키>
export BASE="http://127.0.0.1:9090/api/v1/agent"   # 대상 서버로 교체 가능
bash reimport.sh
```

**주의할 점:**

- 원본 ID는 재사용되지 않습니다. 서버가 생성 시점에 새 ID를 발급하므로,
  재생성된 Card/Role/Task는 이 zip에 적힌 ID와 다릅니다.
- Task가 참조하는 `skill_id`(`voc-hub-skills`, 이 스냅샷 기준
  `7c5abcec-8690-4476-b554-69a88286eb25`)가 **대상 서버에도 등록되어 있어야**
  합니다. 스크립트가 이를 먼저 확인하고, 없으면 멈춰서
  `skill_voc_hub_skills.json`을 참고해 먼저 등록하라고 안내합니다.
- **이 skill_id는 fake 서버 재시작에도 안정적이지 않은 것으로 확인됐습니다**
  (2026-08-27: 서버 재시작 후 같은 skill이 새 ID로 재등록되면서 원래 ID가
  404로 바뀌었고, Task 1·2의 `skills` 링크가 조용히 빠졌던 적이 있음). 이
  zip을 나중에 쓸 때도 재사용 전에 `GET /skills/{skill_id}`로 살아있는
  ID인지 먼저 확인하세요.
- 같은 서버에 이미 같은 이름의 Card/Role/Task가 있어도 중복 여부를 검사하지
  않습니다 — 재실행하면 그대로 새로 하나 더 생깁니다. 재사용이 목적이면
  `avatar-onboarding` 스킬의 "기존 자산 검색" 절차를 먼저 따르세요.
- 이 번들은 **Agent Factory 쪽 구조만** 담고 있습니다. 실제 실행 로직인
  로컬 플러그인 `voc-hub-autoresolve`(`~/.claude/plugins/cache/...`)는
  별도로 관리되며 이 zip에 포함되지 않습니다.

## 참고: 원본 등록 배경

전체 설계 배경(왜 Role이 3개인지, 왜 Task 3엔 skill이 없는지 등)은
프로젝트 루트의 `voc-autoresolve-avatar-registration.md`를 참고하세요.
