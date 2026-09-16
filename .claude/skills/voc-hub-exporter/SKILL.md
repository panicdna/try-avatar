---
name: voc-hub-exporter
description: Use when someone wants every VoC Hub record, or a filtered subset, pulled through the X-API-Key integration API and saved as a JSON file for backup, analysis, or migration, including incremental re-exports of what changed since the last run. VoC 목록 전체 내보내기, VoC 백업, JSON 파일로 저장, 증분 export 에 사용한다. Triggers on export, dump, backup, sync_watermark, next_cursor, has_more, updated_after, or an invalid_pagination error from /api/integrations/v1/vocs. Not for replying to or changing VoCs — that is voc-hub-responder.
---

# VoC Hub — VoC 내보내기 (통합 API)

`GET /api/integrations/v1/vocs` 의 **커서 모드**로 키가 볼 수 있는 VoC 를 끝까지 받아
JSON 파일 하나로 저장한다. 루프는 번들 스크립트가 돈다 — 직접 `curl` 루프를 새로 짜지 않는다.

```
scripts/export_vocs.sh   (이 SKILL.md 옆)
```

읽기 전용이다. 저장·발송·상태 변경은 `voc-hub-responder` 스킬의 일이다.

## 왜 커서 모드인가

| 모드 | 부르는 법 | 전체 export 에 |
|---|---|---|
| 페이지 | `page=N&limit=…`, `created_at` 내림차순 | 받는 도중 새 VoC 가 들어오면 페이지가 밀려 **중복·누락** |
| 커서 | `page` 없이 `limit`, 이후 `cursor` 만 | 첫 요청 시각을 `sync_watermark` 로 고정해 `updated_at, voc_number` 순으로 준다. 도중 수정돼도 중복·누락 없음 |

`voc-hub-responder` 가 "`page` 없이 목록 조회는 실수" 라고 하는 건 트리아지 화면용 규칙이다.
여기서는 반대로 `page` 를 넣지 않는다.

**두 번째 요청부터는 `cursor` 하나만 보낸다.** `cursor` 에 `limit`·`status` 등 다른
파라미터를 하나라도 섞으면 `422 invalid_pagination` 이다 — 필터와 페이지 크기는 이미
커서 안에 들어 있다. 커서는 발급한 키에 묶여 있어 다른 키로 보내도 같은 오류다.

## 전제

키는 **발급하지 않는다.** 사용자가 관리 화면(`/api-keys.html`)에서 **읽기 권한** 키를 만들어
`~/.voc-hub.env` 에 넣는다. 형식·주의점은 `voc-hub-responder` 스킬의 "전제" 와 같다:

```
VOC_INTEGRATION_BASE_URL=http://localhost:8080
VOC_INTEGRATION_API_KEY=<키>
```

- 환경변수가 있으면 그게 이기고, 없으면 파일에서 **값으로만** 읽는다(`source` 하지 않는다).
- **호스트를 자동으로 고르지 않는다.** `VOC_INTEGRATION_BASE_URL` 이 없으면 스크립트가
  멈춘다. 내보내기 결과는 고객 데이터라, 운영에 붙은 줄 모르고 받는 일이 없게 한다.
- 키를 대화창에 붙여넣게 하지 않는다. 키 값·앞자리를 출력하지 않는다.

## 절차

### 1. 무엇을 받을지 정한다

사용자에게 확인할 것은 셋뿐이다. 말하지 않았으면 기본값으로 간다.

| 항목 | 기본값 | 옵션 |
|---|---|---|
| 범위 | 키가 볼 수 있는 전부 | `--status`, `--service-name`, `--issue-owner-email` (각각 단일 값) |
| 증분 | 전체 | `--updated-after <이전 export 의 sync_watermark>` |
| 저장 위치 | `~/voc-hub-exports/vocs-<UTC시각>.json` | `--out PATH` |

`status` 는 단일 값이다. 여러 상태가 필요하면 상태별로 따로 받거나 전체를 받은 뒤 `jq` 로 거른다.

### 2. 실행한다

```bash
S="<이 스킬 디렉터리>/scripts/export_vocs.sh"
"$S"                                          # 전체
"$S" --status resolved --out ~/voc-hub-exports/resolved.json
"$S" --updated-after 2026-09-16T08:47:09.803502Z   # 증분
```

스크립트가 하는 일:

1. `instance:` 줄을 **키 확인보다 먼저** 찍는다 — 어디에 붙었는지 항상 남긴다
2. 첫 페이지는 `limit`(기본 100, 최대 100)+필터로, 이후는 `cursor` 만으로 `has_more=false` 까지
3. 출력 파일 옆 임시 디렉터리에 받고, **마지막 페이지까지 성공했을 때만** `mv` 로 교체한다.
   중간에 실패하면 기존 파일은 그대로고 임시 파일은 지워진다
4. 파일 권한 `600`, 저장 위치가 git 작업 트리 안이면 거부(`--allow-in-repo` 로만 허용)
5. 요약만 출력한다: `count`, `pages`, `sync_watermark`, `output`

### 3. 결과를 보고한다

요약 네 줄과 `instance:` 줄을 그대로 전한다. **레코드 내용은 출력하지 않는다** — 필요하면
사용자가 파일을 연다. 건수·분포처럼 집계만 필요하면 `jq` 로 집계값만 뽑는다:

```bash
jq '.items | group_by(.status) | map({status: .[0].status, n: length})' "$OUT"
```

`sync_watermark` 는 다음 증분 export 의 `--updated-after` 값이니 반드시 전한다.

## 출력 형식

```json
{
  "exported_at": "2026-09-16T08:47:10Z",
  "base_url": "http://localhost:8080",
  "sync_watermark": "2026-09-16T08:47:09.803502Z",
  "count": 18,
  "items": [ { "voc_number": "V260805", "status": "resolved", "...": "..." } ]
}
```

`items` 의 각 항목은 목록 API 응답 그대로다: `voc_number`, `customer_name`,
`customer_email`, `issue_owner_email`, `message`, `service_name`, `status`,
`jira_ticket_key`, `initial_jira_owner`, `error_msg`, `suggested_reply`, `reply_body`,
`reply_body_type`, `internal_memo`, `auto_reply_sent`, `created_at`, `resolved_at`, `updated_at`.
단건 조회(`GET /{voc_number}`)도 필드가 같으므로 더 받을 것이 없다.

## 이 파일에 들어가지 않는 것

- **삭제된 VoC** — 서버가 `deleted_at` 이 있는 레코드를 뺀다
- **키 스코프 밖 VoC** — 서비스 한정 키면 그 서비스 것만. `count: 0` 이면 먼저 스코프를 의심한다
- **메일 발송 이력**(EmailLog)·첨부 — 통합 API 에 없다. 필요하면 DB 에서 꺼내야 하고, 이 스킬의 범위가 아니다

## 데이터 취급

결과물에는 고객 이름·이메일·문의 원문·내부 메모가 들어 있다.

- 저장소 안(특히 `docs/public/`)에 두거나 커밋하지 않는다
- 파일 내용을 대화·이슈·PR 에 붙여넣지 않는다
- 다 쓴 export 파일을 어떻게 할지는 사용자 몫이다 — 대신 지우지 않되, 남아 있다는 사실은 알린다

## 오류

스크립트는 실패 시 `error: HTTP <코드> <code>: <message>` 를 찍고 종료 코드 1 로 끝난다.

| 출력 | 뜻 · 조치 |
|---|---|
| `VOC_INTEGRATION_BASE_URL is not set` | 어느 인스턴스인지 사용자에게 묻는다. 추측해서 채우지 않는다 |
| `401 invalid_api_key` | 키가 비었거나·틀렸거나·폐기됨(만료는 없다). 키를 바꿔 가며 재시도하지 않는다 |
| `403 insufficient_permission` | 읽기 권한이 없는 키 |
| `422 validation_error` | 옵션 값 오류 — `--status` 철자, `--updated-after` 형식(ISO 8601) |
| `422 invalid_pagination` | `--updated-after` 가 서버 현재 시각보다 미래, 또는 커서가 깨짐. 스크립트를 고친 게 아니라면 전체 export 로 다시 받는다 |
| `request failed (network)` | 호스트 불통·인증서 문제. 다른 호스트로 조용히 바꾸지 않는다 |
| `inside a git working tree` | `--out` 을 저장소 밖으로 |

## 멈춰야 하는 신호

- 사용자가 지정하지 않았는데 운영 인스턴스를 골라 받으려 한다
- export 결과를 대화에 통째로 또는 레코드 단위로 출력하려 한다
- `--allow-in-repo` 로 저장소 안에 저장하거나 커밋하려 한다
- 스크립트 대신 `page=` 루프를 새로 짜서 "전체" 라고 보고하려 한다
- 실패한 export 를 부분 결과로 보고하려 한다 — 스크립트는 부분 파일을 남기지 않는다
