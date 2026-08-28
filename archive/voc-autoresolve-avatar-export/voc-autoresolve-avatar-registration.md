# VoC 자동 해결 파트너 — Agent Factory 등록 기록

- 등록 서버: 로컬 fake 서버 `http://127.0.0.1:9090/api/v1/agent` (프로젝트 CLAUDE.md 지시대로 사내 운영 서버 대신 사용)
- 등록 일시(대화 시각 기준): 2026-08-26
- 소유자: `u_DHT3eMX90SS2zQp3Mea7tt` (관리자, admin@test.com)

## 요약 표

| 구분 | 이름 | ID |
|---|---|---|
| Card | VoC 자동 해결 파트너 | `b903e69b-d5e3-4b28-808a-7cb884a9a966` |
| Role 1 | VoC Hub 자동 해결 운영 | `20fb435e-eaf1-4bc4-8e24-b9f6695a2719` |
| ↳ Task 1 | 배정된 VoC 자동 해결 | `6858981e-c79e-4067-bdf6-1ef984cc6eb1` |
| Role 2 | 운영자 | `329e3489-0a82-462b-861c-a02a65b8579c` |
| ↳ Task 2 | VoC Hub 수동 트리아지 | `e22a345e-9590-4024-bf2c-b470f78d8cb6` |
| Role 3 | 모니터 | `6399d4a9-0d28-45e5-ab2a-fdc3f9cfd2ab` |
| ↳ Task 3 | VoC 자동 해결 이력·통계 리포트 | `edb6bf4f-ea95-4e90-8c81-c87f33ac1fe3` |

연결된 Skill: `voc-hub-skills` (`scan_status: passed`), 컴포넌트 `voc-hub-responder` — Task 1·2에 링크됨. Task 3은 연결된 skill 없음(전용 자산 부재).

> **주의 — skill_id는 fake 서버 재시작에 안정적이지 않음.** 최초 등록 시 ID는
> `710eb27a-e2e2-4a2c-bb71-e5f1bf1c6960`였으나, 서버 재시작 후 같은 이름·owner로
> 재조회되면서 ID가 `7c5abcec-8690-4476-b554-69a88286eb25`로 바뀌었고, 이 과정에서
> Task 1·2의 `skills` 링크가 에러 없이 조용히 빈 배열로 떨어졌다(2026-08-27
> 발견·복구). Card/Role/Task 자체의 ID는 재시작에도 유지됨 — Skill 카탈로그
> 항목만 이 문제가 있는 것으로 보인다. 재시작 이후엔 항상 `GET /skills?q=voc`로
> 현재 ID를 다시 확인하고, Task의 `skills[].skill_id`가 여전히 유효한지
> (`GET /skills/{id}`가 200인지) 검증한 뒤 사용한다.

## Card

- **name**: VoC 자동 해결 파트너
- **responsibility**: Jira로 본인에게 배정된 VoC Hub 건 중 가장 오래된 1건을 찾아 답변 작성부터 고객 발송·해결 처리까지 승인 없이 자동으로 마칩니다. 실패 시 재시도하지 않고 멈춰서 보고합니다.
- **role_ids**: [Role1, Role2, Role3]
- **manager_emails**: []

## Role 1 — VoC Hub 자동 해결 운영

- **description**: Jira로 배정된 VoC Hub 건을 사람 승인 없이 자동으로 답변·해결 처리한다. 범위를 1건/1회 실행으로 좁혀 위험을 상쇄한다.
- **task_ids**: [Task1]

### Task 1 — 배정된 VoC 자동 해결

- **context**: 사용자가 수동으로 호출할 때만 실행(정기 스케줄 없음). Jira `initial_jira_owner`가 `VOC_ASSIGNEE_EMAIL`과 일치하는, 미해결 VoC 중 가장 오래된 1건만 대상. 1회 실행 = 정확히 1건.
- **text**: voc-hub-autoresolve 절차를 따른다: (1) voc-hub-responder 스킬의 호스트감지·인증·엔드포인트 규약을 재사용하되 (2) 발송 전 사람 승인 대기 단계는 생략하고 답변 작성→POST .../reply(status=resolved)를 1회로 완료한다. 실패(502 mail_send_failed, 409 outcome_unknown/idempotency_conflict/operation_in_progress, 403 insufficient_permission 등)는 자동 재시도 없이 멈추고 실행한 사용자 본인에게만 보고한다. 필요 설정: ~/.voc-hub.env의 VOC_INTEGRATION_BASE_URL·VOC_INTEGRATION_API_KEY·VOC_ASSIGNEE_EMAIL (사용자가 직접 설정, 에이전트가 대신 발급하지 않음). 매 실행 종료 시(성공·실패·후보없음 모두) ~/.voc-hub/autoresolve-log.jsonl에 한 줄 JSON을 append한다: {ts, instance, assignee, voc_number, outcome, error_code, error_message, voc_status_after}. 키 원문은 절대 기록하지 않는다.
- **skills**: `voc-hub-skills` / `voc-hub-responder`

## Role 2 — 운영자

- **description**: VoC 자동 해결 기능을 포함해 VoC Hub 전반의 사람 개입형 대응을 진행하는 창구. 목록 확인부터 승인 기반 발송까지 담당.
- **task_ids**: [Task2]

### Task 2 — VoC Hub 수동 트리아지

- **context**: 사람이 옆에서 진행하는 온디맨드 호출. 목록 조회 → 대상 선택 → 초안 저장 → 발송 전 모드·수신·제목 확인 → 명시 승인 후 발송까지 전 과정.
- **text**: voc-hub-responder 스킬의 human-in-the-loop 절차를 그대로 따른다: page 포함 목록 조회 → voc_number·status·customer_email·issue_owner_email 표로 제시 → 사용자가 대상 고르기 전 아무것도 쓰지 않음 → PATCH로 무발송 초안 저장 가능 → 발송 전 인스턴스·모드·수신·제목 3줄을 사람에게 보여주고 명시 승인('보내'/'발송해') 후에만 POST .../reply → Idempotency-Key 매 시도 신규 생성.
- **skills**: `voc-hub-skills` / `voc-hub-responder`

## Role 3 — 모니터

- **description**: VoC 자동 해결의 진행 상황·오류·이력을 로그 기반으로 집계해 리포트로 제공한다.
- **task_ids**: [Task3]

### Task 3 — VoC 자동 해결 이력·통계 리포트

- **context**: 사용자 요청 시에만 실행(정기 스케줄 없음). Task 1이 기록하는 ~/.voc-hub/autoresolve-log.jsonl을 유일한 데이터 원천으로 삼는다.
- **text**: 로그 파일을 읽어 outcome별 건수, 최근 오류(error_code·시각), 처리 이력을 집계하고 ~/.voc-hub/reports/<타임스탬프>-autoresolve-report.md에 저장한다. 전용 skill 없음 — Bash/jq로 로그를 직접 집계하는 방식이며, Task 1이 아직 실행되지 않았거나 로그가 비어 있으면 '이력 없음'을 그대로 보고한다.
- **skills**: 없음 (알려진 한계)

## 로컬 실행 로직과의 관계 (Agent Factory 밖)

- 실제 실행은 Agent Factory에 새로 만든 subagent가 아니라, 기존에 설치된 플러그인 `voc-hub-autoresolve`가 담당한다 (이번 등록에서 "Card/Role/Task만 등록" 옵션을 선택했기 때문에 `~/.claude/agents/agent-factory/...` 파일은 생성하지 않음).
- Task 1 텍스트의 로그 기록 요구사항을 실제로 반영하기 위해, 플러그인 파일을 직접 수정함:
  `/mnt/c/work/voc-hub/skills/voc-hub-autoresolve/plugins/voc-hub-autoresolve/agents/voc-hub-autoresolve.md`
  → 8절("실행 로그를 남긴다") 신설 + 1·2·5·6절에서 그 8절을 참조하도록 연결 (git diff: +62/-4줄).

## 알려진 한계 / 후속 확인 필요

1. Task 3(모니터)은 Agent Factory Skill로 등록된 전용 자산이 없다 — 커스텀 Bash/jq 집계 절차로만 문서화됨.
2. 8절 로그 기록은 이번 대화에서 처음 추가된 것이라 실제 검증이 필요하다 — 시험 실행(`voc-hub-autoresolve`)을 백그라운드로 돌려 확인 중이었음(완료 시점 기준 이 파일 갱신 필요).
3. `VOC_ASSIGNEE_EMAIL`이 `jazzman.han`처럼 도메인 없는 값으로 설정되어 있었음 — 로컬 fake 데이터에서는 우연히 `initial_jira_owner` 값과 형식이 일치해 매칭됐지만, 실사용 시 이메일 전체 형식인지 재확인 필요.
