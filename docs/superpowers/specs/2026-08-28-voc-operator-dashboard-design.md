# VoC Operator 이력 대시보드 — 설계

- 날짜: 2026-08-28
- 상태: 승인됨 (구현 대기)
- 관련 에이전트: `agents/agent-factory/voc-avatar-operator.md`

## 배경 및 목적

`voc-avatar-operator`는 판단할 때마다 `~/.voc-hub/operator-decisions.jsonl`에
한 줄씩 이력을 append한다. 이 파일은 human-in-the-loop 질의에 대한 선례 재사용의
**실제 소스**다 — 운영자가 다음 판단에서 "사실상 동일한 조건"의 선례를 찾을 때
이 파일을 직접 읽는다.

지금까지는 이 파일을 확인하거나 고치려면 `jq`/`cat`으로 터미널에서 다뤄야 했다.
과거 실제로 append 스크립트의 버그(`jq` 변수 누락)로 에러 메시지가 JSON 라인과
섞여 파일이 손상된 사고가 있었다(`operator-decisions.jsonl.corrupted-evidence-*`
로 증거 보존됨). 이 경험 때문에 손상 복원력이 이번 설계의 필수 요구사항이다.

이 프로젝트는 사람이 이 이력을 웹 페이지 형태로 열람하고, 필요하면 항목 단위로
참고·수정·삭제까지 할 수 있는 **개인용(self) 로컬 대시보드**를 제공한다.

## 범위

**포함**: `~/.voc-hub/operator-decisions.jsonl` 열람·검색·수정·삭제.

**제외** (YAGNI, 이번 요청 범위 밖):
- `~/.voc-hub/autoresolve-log.jsonl` (resolver의 발송 로그) — 별도 요청 시 확장
- 여러 사용자 동시 접근, 인증/권한
- 상시 구동(데몬)형 서버, 원격 배포
- `.bak-*` 백업 파일 자체를 대시보드에서 열람/복원하는 UI (수동 복구로 충분)

## 아키텍처

```
[.claude/commands/voc-operator-dashboard.md]  (슬래시 커맨드)
        │  실행: python3 scripts/voc_operator_dashboard.py (백그라운드)
        ▼
[voc_operator_dashboard.py]  (Python3 표준 라이브러리만 사용, 외부 의존성 없음)
        │  http.server 기반, 고정 포트 8765
        │  같은 프로세스가 HTML(뷰)과 /api/entries(REST) 모두 서빙
        ▼
[~/.voc-hub/operator-decisions.jsonl]  ← 유일한 진실의 원천(source of truth)
        │
        └─ 수정/삭제 직전 자동 백업 → ~/.voc-hub/operator-decisions.jsonl.bak-<epoch>
```

단일 파일 스크립트로 구현한다(`scripts/voc_operator_dashboard.py`). pip 설치
없이 `python3` 하나로 동작해야 한다 — "self" 도구로서 설치 마찰이 없어야 하기
때문이다.

## 데이터 모델

JSONL 한 줄 = 한 판단 기록. 필드:

| 필드 | 편집 가능 | 비고 |
|---|---|---|
| `ts` | ❌ (읽기 전용) | ISO8601. 기록 시각을 편집하면 이력이 왜곡되므로 고정 |
| `voc_number` | ✅ | |
| `decision` | ✅ | 자유 텍스트 입력이되 HTML `<datalist>`로 `reply`/`internal`/`pr_delegate`/`hold` 4개를 후보로 제시(강제 아님 — 과거 기록에 이 4개 외 값이 있을 수 있으므로 입력 자체를 막지 않는다) |
| `trigger_condition` | ✅ | |
| `human_instruction` | ✅ | |
| `precedent_used` | ✅ | |

## 행 식별과 동시성

`voc-avatar-operator`는 대시보드가 열려 있는 동안에도 독립적으로 이 파일에 append할
수 있다(별도 Claude 세션/subagent). 그래서 줄 번호(index)나 별도 발급 id로 행을
식별하지 않는다.

- **GET**: 파일을 매 요청마다 새로 읽어 파싱한 배열을 그대로 반환한다(캐시 없음).
- **PATCH/DELETE**: 요청 본문에 클라이언트가 방금 화면에서 읽은 **행 전체 JSON**을
  그대로 실어 보낸다(`original` 필드). 서버는 그 순간 파일을 다시 읽어 해당 줄과
  **완전히 일치하는 줄**을 찾는다.
  - 찾으면: 백업 생성 → 그 줄만 교체(PATCH) 또는 제거(DELETE) → 파일 재작성.
  - 못 찾으면: `409 Conflict` + `"파일이 변경되었습니다. 새로고침 후 다시 시도하세요"`.
    자동 재시도하지 않는다 — 엉뚱한 줄을 잘못 고치는 사고를 막기 위함.

## 손상 복원력

라인 단위로 `json.loads` 시도. 실패한 라인은 **건너뛰고** 원본 텍스트와 줄 번호를
별도로 수집해 `GET /api/entries` 응답의 `parse_errors` 배열에 담는다. 프론트엔드는
`parse_errors`가 비어있지 않으면 상단에 경고 배너("N개 줄 파싱 실패, 무시됨 — 원본
파일에서 직접 확인하세요")를 띄운다. 손상된 줄이 있어도 나머지 정상 줄은 정상
표시·편집·삭제된다.

파일 자체가 없으면(아직 판단 이력이 없는 최초 상태) 빈 목록 + "아직 기록된 판단이
없습니다" 안내로 처리한다(에러 아님).

## 백업

PATCH/DELETE 처리 직전, 현재 파일 전체를
`~/.voc-hub/operator-decisions.jsonl.bak-<unix epoch seconds>` 로 복사한다(수정
1건당 백업 1개). 복사 실패 시(디스크 문제 등) **쓰기 자체를 중단**하고 에러를
반환한다 — 백업 없이 원본을 고치지 않는다.

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 대시보드 HTML(인라인 CSS/JS 포함, 외부 CDN 의존 없음) |
| GET | `/api/entries` | `{items: [...], parse_errors: [{line_no, raw}]}` |
| PATCH | `/api/entries` | body: `{original: {...}, updated: {...}}` → 성공 시 갱신된 `items` 반환 |
| DELETE | `/api/entries` | body: `{original: {...}}` → 성공 시 갱신된 `items` 반환 |

`original`이 현재 파일 내용과 정확히 일치하지 않으면 위 "행 식별과 동시성" 규칙에
따라 409.

## 프론트엔드

- 순수 HTML/CSS/vanilla JS, 외부 라이브러리 없음(단일 파일 서버가 통째로 서빙하므로
  네트워크 의존성을 만들지 않는다).
- 표: 최신순(`ts` 내림차순) 정렬. 컬럼 = 위 5개 편집 가능 필드 + `ts`(읽기전용 표시).
- 행마다 "수정"(인라인 폼으로 전환) / "삭제"(확인창 후 실행) 버튼.
- 상단 검색창: `voc_number` 또는 `decision`에 대한 클라이언트 사이드 텍스트 필터
  (서버 요청 없이 이미 받아온 배열을 필터링 — 데이터가 로컬 개인용 규모라 서버
  사이드 검색은 불필요).
- 삭제 확인창 문구에 "이 항목은 향후 자동 판단의 선례로 쓰일 수 있습니다"라고
  명시해, 단순 UI 텍스트 삭제가 아니라 자동화 동작에 영향을 준다는 걸 알린다.

## 실행 방법

`.claude/commands/voc-operator-dashboard.md` 슬래시 커맨드(`/voc-operator-dashboard`):
1. `python3 scripts/voc_operator_dashboard.py` 를 백그라운드로 실행.
2. 포트 8765가 이미 사용 중이면(다른 인스턴스가 떠 있을 가능성) 새로 띄우지 않고
   "이미 실행 중일 수 있습니다 — http://localhost:8765 를 열어보세요"라고 안내한다.
3. 성공 시 `http://localhost:8765` 를 사용자에게 알려준다.

서버 종료는 사용자가 직접 요청하면 백그라운드 프로세스를 정리한다(상시 구동 데몬이
아니다).

## 에러 처리 요약

| 상황 | 동작 |
|---|---|
| JSONL 라인 파싱 실패 | 해당 라인만 스킵, 배너로 경고, 나머지는 정상 |
| 파일 없음 | 빈 목록으로 정상 처리(에러 아님) |
| PATCH/DELETE 시 대상 줄을 못 찾음(동시 변경) | 409, 자동 재시도 없음 |
| 백업 파일 생성 실패 | 쓰기 중단, 에러 반환, 원본 불변 |
| 포트 사용 중 | 새 프로세스를 띄우지 않고 안내만 |

## 테스트 계획

- 정상 JSONL 파싱 → 5개 필드 + ts 그대로 반환
- 손상된 줄(과거 사고 재현 데이터로) 포함 시 해당 줄만 `parse_errors`로 빠지고
  나머지는 정상 반환
- PATCH: 정상 케이스(필드 변경 반영 + 백업 파일 생성 확인)
- PATCH: `original`이 현재 파일과 불일치 → 409, 파일 불변, 백업 미생성
- DELETE: 정상 케이스(해당 줄 제거 + 백업 생성), 존재하지 않는 줄 → 409
- 파일이 아예 없는 상태에서 GET → 빈 목록, 에러 아님
