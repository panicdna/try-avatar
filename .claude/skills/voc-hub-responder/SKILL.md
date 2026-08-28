---
name: voc-hub-responder
description: Use when triaging VoC Hub records through the X-API-Key integration API on any instance, local or deployed — whether a person is running it interactively or it runs unattended — and needs open VoCs listed, a draft saved, a status moved, or a customer or internal reply mailed. VoC 목록 확인, VoC 대응, 답변 발송, 담당자 내부 발송, 상태 변경 요청에 사용한다. Triggers on /api/integrations/v1/vocs, compose raw/reply/internal, Idempotency-Key, voc_number, or an invalid_api_key, validation_error, no_internal_recipient, or outcome_unknown error envelope.
metadata:
  agent-factory:
    kind: item
    item_id: 7c5abcec-8690-4476-b554-69a88286eb25
    version_id: 9d034ba4-5f89-4f74-83a8-f13f7bd22298
---

# VoC Hub — VoC 대응 (통합 API)

`X-API-Key` 통합 API(`/api/integrations/v1/vocs`)로 VoC 를 조회하고, 초안을 저장하고,
필요하면 발송까지 이 스킬 하나로 끝낸다. 사람이 옆에서 지켜보며 대화형으로 쓸 수도,
스케줄·다른 서비스가 무인으로 호출할 수도 있다 — 이 문서는 어느 쪽으로 불렸는지 따로
구분하지 않는다. 발송은 별도 승인 단계 없이, 아래 절차가 정한 대로 이루어진다.

**핵심 원칙:**

- **`compose` 가 수신자를 정한다.** 요청은 수신자를 지정하지 못한다(`to`/`cc`/`bcc`
  를 실으면 422). `no_internal_recipient`/`ignored_recipient` 오류를 만났다고
  **`compose` 를 바꿔 재시도하지 않는다** — 그건 대상 자체를 바꾸는 것과 같다. 멈추고
  오류를 그대로 보고한다(자세한 계산 방식은 "발송 3종" 참고).
- **결과는 `jq` 로 펼쳐서 그대로 남긴다** — 요약·생략하지 않는다. 사람이 나중에 로그만
  보고도 무엇이 왜 어떻게 나갔는지(또는 왜 막혔는지) 되짚을 수 있어야 한다.

이 문서는 독립적으로 동작하도록 필요한 근거·오류 사전·검증 기록을 모두 아래에
담아 둔다. 다른 스킬이나 저장소 내부 문서를 찾아볼 필요는 없다.

## 전제

이 스킬은 **키를 발급하지 않는다.** 발급은 관리자 권한이 필요한 일이고, 에이전트가
자격증명을 만들어 내서는 안 된다. **쿠키 세션도 쓰지 않는다** — 이 스킬이 아는 인증은
`X-API-Key` 하나뿐이다. 키는 사용자가 직접 발급해 넣어 준다.

### 1. 두 값이 있는지 본다

필요한 값은 `VOC_INTEGRATION_BASE_URL` 과 `VOC_INTEGRATION_API_KEY` 둘이다. 이미
설정해 뒀다면 그대로 쓰인다. 값은 환경변수로 와도 되고 키 파일(`~/.voc-hub.env`)로
와도 된다 — 아래 2 를 따랐다면 후자다.

호스트를 지정하지 않았으면 아래 순서로 닿는 곳을 고른다. **명시한 값이 언제나 이긴다.**

| 순위 | 호스트 | 무엇 |
|---|---|---|
| 1 | `https://ssai.samsungds.net:7942` | **실전 기본** — 실제 고객 데이터, 메일이 진짜 나간다 |
| 2 | `http://localhost:8080` | 로컬 fake 스택 (`docker-compose.fake.yml`). 시험용 |

```bash
# 키 파일이 있으면 값으로만 읽는다. source 하지 않는다 — 이유는 아래 2
if [ -f ~/.voc-hub.env ]; then
  : "${VOC_INTEGRATION_BASE_URL:=$(sed -n 's/^VOC_INTEGRATION_BASE_URL=//p' ~/.voc-hub.env)}"
  : "${VOC_INTEGRATION_API_KEY:=$(sed -n 's/^VOC_INTEGRATION_API_KEY=//p' ~/.voc-hub.env)}"
fi
if [ -z "${VOC_INTEGRATION_BASE_URL:-}" ]; then
  for h in https://ssai.samsungds.net:7942 http://localhost:8080; do
    if curl -s -o /dev/null --max-time 5 "$h/api/integrations/v1/vocs"; then
      export VOC_INTEGRATION_BASE_URL="$h"; break
    else
      echo "닿지 않음: $h"      # 조용히 다음 순위로 떨어지지 않게 한다
    fi
  done
fi
: "${VOC_INTEGRATION_BASE_URL:?두 호스트 모두 닿지 않는다 — 멈추고 보고한다}"
echo "인스턴스: $VOC_INTEGRATION_BASE_URL"   # 키 가드보다 앞 — 키가 없어도 보여야 한다
: "${VOC_INTEGRATION_API_KEY:?키가 없다 — 멈추고 요청한다}"
export BASE="$VOC_INTEGRATION_BASE_URL/api/integrations/v1/vocs"
export KEY="$VOC_INTEGRATION_API_KEY"
```

인증이 필요 없는 도달 확인이다 — 키 없이 부르면 401 이 오는데, **응답이 왔다는 것 자체가
살아 있다는 뜻**이라 `curl` 은 성공으로 끝난다. `-f` 를 붙이면 401 을 실패로 봐서 살아
있는 호스트를 건너뛰므로 붙이지 않는다.

**고른 인스턴스를 결과에 반드시 남긴다.** 기본값이 운영이므로, 자동 선택을 그냥
넘기면 로컬인 줄 알고 운영에 붙어 고객에게 시험 메일이 나간다. 반대 방향도 조용하다 —
운영 호스트가 방화벽·타임아웃·**인증서 미신뢰**로 실패하면 그냥 로컬로 떨어진다. 그래서
위 스니펫은 건너뛴 호스트마다 `닿지 않음:` 을 찍고, **인스턴스 줄을 키 가드보다 앞에**
둔다 — 키가 없는 첫 실행이 정확히 그 줄을 못 보는 순서였다. 향하는 곳이 예상과 다르면
멈추고 그대로 보고한다.

**키는 절대 출력하지 않는다.** `echo "$KEY"` 도, 로그·요약에 남기는 것도 하지 않는다.
필요한 것은 값이 있느냐지 값이 무엇이냐가 아니다.

키가 빈 채로 요청하면 `401 invalid_api_key` 가 나는데, 이는 키가 **틀렸을** 때와 응답이
같다. 없는 것을 틀린 것으로 착각해 엉뚱한 곳을 뒤지게 되므로 위 가드로 먼저 멈춘다.

### 2. 없으면 사용자에게 발급을 요청한다

대신 발급하지 않는다. **어느 인스턴스의 키가 필요한지 먼저 밝히고**, 그 인스턴스의 관리
화면 주소를 그대로 알려 준 뒤 값을 받을 때까지 기다린다. 키는 인스턴스마다 다르다 —
로컬 키로 운영을 부르면 401 이다.

| 인스턴스 | 관리 화면 |
|---|---|
| 실전 | `https://ssai.samsungds.net:7942/api-keys.html` |
| 로컬 fake 스택 | `http://localhost:8080/api-keys.html` |

> 1. 브라우저로 위 주소의 VoC Hub 에 **관리자 계정**으로 로그인한다.
> 2. `api-keys.html` 화면에서 키를 만든다.
>    - **발송까지 하려면 쓰기 권한이 필요하다.** 읽기 전용 키는 `POST …/reply` 가
>      403 `insufficient_permission` 이다.
>    - 서비스 한정 키로 만들면 그 서비스의 VoC 만 보인다. 스코프 밖 레코드는 목록에서
>      조용히 빠지고, 개별 조회로는 404 `voc_not_found` 로 보인다.
> 3. **원문 키는 만든 직후 한 번만 표시된다.** 이후 목록에는 앞자리(`key_prefix`)만
>    남아 다시 꺼낼 수 없다. 그 자리에서 복사해 둔다.
> 4. 키 파일에 넣는다. 호스트는 키를 만든 그 인스턴스여야 한다.
>    ```bash
>    umask 077
>    cat > ~/.voc-hub.env <<'EOF'
>    # 실전이면 https://ssai.samsungds.net:7942
>    VOC_INTEGRATION_BASE_URL=http://localhost:8080
>    VOC_INTEGRATION_API_KEY=<복사한 키>
>    EOF
>    ```
>    `export` 가 아니라 `이름=값` 으로 적는다. 이 파일은 읽히는 것이지 실행되는 것이
>    아니다.

**키를 대화창에 붙여넣게 하지 않는다.** 파일에 넣도록 안내한다 — 대화에 들어온 값은
요약·로그에 남는다. 사용자가 이미 붙여넣었다면 그 사실을 알리고, 그 키는 폐기하고 새로
발급하도록 권한다.

**`export` 만으로는 에이전트에 닿지 않는다.** Claude Code 는 Bash 호출마다 새 셸을 띄운다.
한 호출에서 `export` 한 값은 다음 호출에서 사라지고, 사용자가 자기 터미널에서 export 해도
그건 다른 프로세스다. 그래서 키는 **파일에 두고 호출마다 읽는다.** (`~/.bashrc` 에 넣으면
매 호출 로드되긴 하지만, 시험용 키가 모든 프로젝트의 모든 세션에 상주하게 된다.)

**키 파일을 `source` 하지 않는다.** `.` 와 `source` 는 파일 내용을 **명령으로 실행**한다.
형식이 어긋난 파일 — 예컨대 키 한 줄만 들어 있는 파일 — 을 읽으면 셸이 그 줄을 명령어로
해석해 `command not found: <키>` 로 **키를 그대로 출력한다.** 실제로 이 경로에서 키가
로그에 남은 적이 있다. 값으로만 꺼낸다:

```bash
KEY=$(sed -n 's/^VOC_INTEGRATION_API_KEY=//p' ~/.voc-hub.env)
```

같은 이유로 키 확인은 **존재 여부까지만** 한다. 앞자리 몇 글자라도 찍으면 그게 로그다 —
`[ -n "$KEY" ]` 로 충분하다.

### 3. 받은 키가 동작하는지 확인한다

넣었다고 해서 맞는 것은 아니다. 첫 쓰기 전에 읽기로 확인한다.

```bash
: "${KEY:?}" "${BASE:?}"
curl -s -G "$BASE" -H "X-API-Key: $KEY" \
  --data-urlencode page=1 --data-urlencode limit=1 \
| jq -r 'if .error then "실패 \(.error.code): \(.error.message)" else "OK total=\(.total)" end'
```

`OK total=0` 은 키는 유효한데 보이는 VoC 가 없다는 뜻이다 — 스코프를 의심한다.
실패하면 아래 표로 원인을 가리고, **에이전트가 키를 바꿔 가며 재시도하지 않는다.**

### 4. 키 관리는 사용자 몫이다

API 키는 **만료되지 않는다.** 폐기도 사용자가 관리 화면에서 한다. 시험용으로 만든 키를
그대로 두지 말라고 알리되, 폐기 요청을 대신 보내지 않는다.

### 5. 인증 오류 읽는 법

| 응답 | 뜻 |
|---|---|
| `401 invalid_api_key` | 만료가 아니다 — 키가 비었거나·틀렸거나·폐기됨 |
| `403 insufficient_permission` | 그 키에 쓰기 권한이 없다. 사용자에게 쓰기 키를 요청 |
| `404 voc_not_found` | 번호 오타 **또는** 키 스코프 밖 |

### 6. 연동 등록도 사용자 몫이다

사람이 직접 부르는 게 아니라 다른 서비스가 VoC Hub 를 호출하게 하려면, 그 서비스 설정에
원문 키를 넣고 `X-API-Key` 헤더로 보내게 한다(예: Agent Factory 는 `VOC_HUB_API_KEY`).

반대 방향인 상태 콜백은 **VoC Hub 쪽에** 등록한다 — 관리 화면 `services.html`
(실전 `https://ssai.samsungds.net:7942/services.html`, 로컬 `http://localhost:8080/services.html`)
의 `status_callback_url`. 등록돼 있지 않으면 저장·발송 때 콜백이 조용히 건너뛰어지고
`warnings` 에도 아무 표시가 남지 않는다. 둘 다 사용자가 화면에서 하는 일이고, 에이전트가
대신 설정하지 않는다.

## 절차 (이 순서를 건너뛰지 않는다)

### 1. 대상 목록을 서버에서 걸러 온다

**`page` 를 반드시 넣는다.** 빠뜨리면 목록 모드가 아니라 증분 동기화(커서) 모드로 빠진다.
`jq` 에는 **`.error` 분기를 반드시 넣는다** — 오류 응답에는 `items` 가 없어서, 분기가
없으면 오류가 "결과 0건" 으로 보인다.

```bash
curl -s -G "$BASE" -H "X-API-Key: $KEY" \
  --data-urlencode "status=registered" \
  --data-urlencode "page=1" --data-urlencode "limit=50" \
| jq -r 'if .error then "ERROR \(.error.code): \(.error.message)"
         else (.items[] | "\(.voc_number)  \(.status)  \(.customer_email) -> \(.issue_owner_email // "-")  [Jira 담당자: \(.initial_jira_owner // "-")]")
         end'
```

`status` 는 단일 값이라 미처리 두 상태를 보려면 두 번 호출한다. 목록이 비면 "처리할
VoC 가 없다" 고 단정하기 전에 **키 스코프**를 의심한다 — 스코프 밖 레코드는 조용히
빠지고, 개별 조회로는 `404 voc_not_found` 로 보인다.

**`issue_owner_email` 을 곧 Jira 매핑 담당자로 읽지 않는다.** 서비스의 라우팅 규칙
(`assignee_routing_rules`)이 매치했을 때만 그 값이 매핑에서 온 것이다 — 매치가 없으면
등록 요청이 보낸 값이거나, 그마저 없으면 고객 이메일로 떨어진다. **실제 Jira 담당자는
`initial_jira_owner` 를 본다** — 목록·상세 응답 모두에 있고, 티켓이 실제로 만들어진
순간에 쓰인 담당자를 그대로 저장해 둔 값이다. 다만 이건 **스냅샷**이다 — 이후 관리자가
`service_jira_mappings` 의 규칙을 바꿔도 이미 만들어진 티켓의 이 값은 그대로 남는다(지금
매핑이 아니라 그때의 매핑을 본다). 티켓 자체가 없으면(Jira 미연동 서비스, 또는
`jira_failed` 로 재시도 전) `null` 이다 — 그때는 `services.html` 관리 화면에서 현재
매핑 설정을 직접 봐야 한다.

**`null` 이 곧 "담당자가 배정된 적 없다" 는 뜻은 아니다.** 이 필드가 생기기 전에 이미
만들어진 Jira 티켓은 그때 누가 배정받았는지 기록된 적이 없어 영영 `null` 로 남는다.
`jira_ticket_key` 는 있는데 `initial_jira_owner` 만 `null` 이면 이 경우를 의심한다.

### 1-1. 한 건을 자세히 볼 때

번호를 이미 알면 목록을 훑지 말고 바로 부른다.

```bash
curl -s "$BASE/V260806" -H "X-API-Key: $KEY" \
| jq 'if .error then {FAIL:.error.code, msg:.error.message}
      else {voc_number, status, service_name, customer_name, customer_email,
            issue_owner_email, jira_ticket_key, initial_jira_owner, reply_body_type,
            message, suggested_reply, reply_body, internal_memo} end'
```

**목록 항목과 상세는 필드가 완전히 같다.** 상세 스키마가 목록 스키마를 상속만 하고
아무 필드도 더하지 않기 때문이다 — 고객 원문 `message` 도 이미 목록에 들어 있다.
그러니 **답변 초안을 쓰겠다고 상세를 또 부르지 않는다.** 상세가 필요한 경우는 둘뿐이다:

- `voc_number` 를 이미 알아서 목록을 넘길 필요가 없을 때
- 저장·발송 **직전에** 최신 `status`·`reply_body` 를 다시 확인할 때

`404 voc_not_found` 는 번호 오타 **또는** 키 스코프 밖이다. 둘이 구분되지 않으므로
번호를 다시 치기 전에 스코프부터 의심한다.

원문을 옮길 때는 `message` 를 그대로 남긴다. 요약해서 남기면 나중에 검토할 근거가
사라진다.

### 2. 처리 대상을 정한다

각 건의 **`voc_number`, `status`, `customer_email`, `issue_owner_email`** 을 `jq` 로
그대로 펼쳐 남긴 뒤, 그 목록을 근거로 어떤 건을 어떻게 처리할지 정한다. 사람이 옆에
있다면 그 표를 보고 고를 수도 있고, 무인 호출이라면 주어진 기준(상태·담당자 등)으로
스스로 고른다 — 어느 쪽이든 무엇을 근거로 골랐는지는 남긴다.

이 표면의 키는 처음부터 끝까지 `voc_number`("V260805") 다. 정수 `id` 는 `/web/*` 것이다.

### 3. 초안을 무발송으로 저장한다

```bash
jq -n --arg body "답변 초안 본문" --arg memo "내부 메모" \
   '{reply_body:$body, reply_body_type:"text", internal_memo:$memo, status:"reviewing"}' \
   > /tmp/voc-patch.json

curl -s -X PATCH "$BASE/V260805" -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' --data-binary @/tmp/voc-patch.json \
| jq 'if .error then {FAIL:.error.code, msg:.error.message}
      else {changed, voc_status_updated, warnings} end'
```

보낸 필드만 반영된다. **`reply_body_type` 을 반드시 함께 보낸다** — 생략하면 레코드에
남아 있던 값이 그대로 유지되어, 기존이 `html` 인 건에 평문을 저장하면 조립 시 줄바꿈이
사라진다.

**메일은 안 나가지만 외부로는 나간다.** 무언가 실제로 바뀌면 서버가 서비스 연동 3종을
돌린다 — 서비스에 `status_callback_url` 이 등록돼 있으면 `reply_body` 와
`internal_memo` 가 그 URL 로 POST 되고, Jira 가 연결돼 있으면 같은 값이 코멘트로 달리며
상태가 바뀐 경우 티켓 전이까지 일어난다. "내부 메모" 는 고객에게 안 보인다는 뜻이지
시스템 밖으로 안 나간다는 뜻이 아니다. 아무것도 바뀌지 않으면(`changed:false`) 연동도
돌지 않는다.

### 4. "모드 · 수신 · 제목" 을 계산해 남긴다

이 API 에는 발송 전 미리보기가 없다. 대신 아래 세 줄을 발송 직전에 계산해 결과에
남긴다 — 나중에 무엇이 왜 누구에게 나갔는지 되짚을 유일한 단서이기 때문이다.

```
인스턴스: https://ssai.samsungds.net:7942   ← 운영이면 실제 고객에게 나간다
모드    : internal
수신    : panicdna@gmail.com          (issue_owner_email 에서 유도)
제목    : (Internal Only) [V260807] VoC reply - SLSI Agent Factory
```

**세 줄은 짐작이 아니라 계산해서 채운다.**

- **제목**은 서버가 `[<voc_number>] VoC reply - <service_name>` 로 고정한다. `service_name`
  은 목록/상세 응답에 그대로 있으니 그 값을 쓴다. `internal` 만 `(Internal Only) ` 가 붙는다.
- **수신**은 모드가 정한다. `raw`·`reply` 는 `customer_email` 그대로다. `internal` 은
  `issue_owner_email` 에서 ① 고객 주소 제거 ② `@test.com` 등 무시 주소 제거
  ③ 대소문자 무시 중복 제거(첫 표기 채택) 를 거친 결과다 — 그 컬럼에
  `"a@x.com,a@x.com,"` 처럼 같은 사람이 여러 번 들어 있는 일이 실제로 있으므로,
  컬럼 값을 그대로 읽어 주면 안 된다.

수신·제목을 요청이 못 정한다는 것은 확인해 볼 수 있다. `to` 나 `subject` 를 실어 보내면
`extra="forbid"` 때문에 **본문 검증 단계에서 422** 로 끊겨 발송이 일어나지 않는다.

### 5. compose 를 정했으면 바로 발송한다

목적(단발 통지·고객 회신·담당자 이관)에 맞는 `compose` 를 정했으면 별도 확인 단계 없이
`POST …/reply` 를 호출한다. 한 번 정한 `compose` 는 오류가 나도 바꿔서 재시도하지
않는다(핵심 원칙 참고) — 오류는 그대로 보고하고 멈춘다.

## 발송 3종

| compose | 조립 | 수신자 | 쓰는 때 |
|---|---|---|---|
| `raw` (기본값) | 없음 — `reply_body` 그대로 | `customer_email` | 인용이 필요 없는 단발 통지 |
| `reply` | `[답변]` + `[질문 원문]` 인용 | `customer_email` | 고객 회신 |
| `internal` | reply + VoC Hub 링크 + 제목에 `(Internal Only) ` | `issue_owner_email` 파생, **고객 제거** | 담당자에게 이관 |

인용문에 들어가는 식별 행은 모드마다 다르다. **Jira 티켓 키는 `internal` 에만 실린다** —
고객을 향하는 `reply` 로 내부 티켓 번호가 새 나가지 않게 한 것이므로, "고객 회신에도
티켓 번호를 넣어 달라" 는 요청이 오면 설계 의도임을 알리고 확인받는다.

**요청이 정하지 못하는 것** (넣으면 422): `to`·`cc`·`bcc`(수신자는 `compose` 가 정한다),
`subject`(서버가 `[번호] VoC reply - 서비스` 로 고정), `voc_status`(이 표면의 이름은
`status`). 받는 필드는 `reply_body`·`reply_body_type`·`internal_memo`·`status`·`compose`
뿐이다.

`Idempotency-Key` 는 **필수**다. 같은 키 + 같은 본문이면 저장된 응답을 되돌려주므로 두 번
나가지 않고, 같은 키 + 다른 본문이면 409 `idempotency_conflict` 다. 시도마다 새로 만든다.

페이로드는 `jq -n --arg` 로 만들고, **변수 가드를 앞에 둔다.** `IDEM` 이 비면 curl 이
헤더를 통째로 빠뜨려 422 가 나는데 서버가 이유를 알려주지 않는다.

```bash
# ① raw — 조립 없음, 고객에게
VOC=V260805; MODE=raw; IDEM="voc-$VOC-$MODE-$(date +%H%M%S)"
: "${KEY:?}" "${BASE:?}" "${VOC:?}" "${IDEM:?}"
jq -n --arg body "안내드립니다: 오늘 21시~22시 사이 정기 점검이 예정되어 있습니다." \
   '{reply_body:$body, compose:"raw", status:"reviewing"}' > /tmp/voc-$MODE.json
curl -s -X POST "$BASE/$VOC/reply" -H "X-API-Key: $KEY" -H "Idempotency-Key: $IDEM" \
  -H 'Content-Type: application/json' --data-binary @/tmp/voc-$MODE.json \
| jq 'if .error then {FAIL:.error.code, msg:.error.message, retry:.error.retry_action}
      else {ok:.status, log_id, voc_status_updated, warnings} end'
```

```bash
# ② reply — 고객에게, 인용 붙음
VOC=V260805; MODE=reply; IDEM="voc-$VOC-$MODE-$(date +%H%M%S)"
: "${KEY:?}" "${BASE:?}" "${VOC:?}" "${IDEM:?}"
jq -n --arg body "문의 주신 증상은 실행 노드 타임아웃으로 확인되었습니다. 다시 실행해 보시고, 재발하면 실행 ID 를 알려주세요." \
      --arg memo "고객 회신 발송" \
   '{reply_body:$body, internal_memo:$memo, compose:"reply", status:"resolved"}' > /tmp/voc-$MODE.json
curl -s -X POST "$BASE/$VOC/reply" -H "X-API-Key: $KEY" -H "Idempotency-Key: $IDEM" \
  -H 'Content-Type: application/json' --data-binary @/tmp/voc-$MODE.json \
| jq 'if .error then {FAIL:.error.code, msg:.error.message, retry:.error.retry_action}
      else {ok:.status, log_id, voc_status_updated, warnings} end'
```

```bash
# ③ internal — 담당자에게. 인용 + 제목 접두 + 링크, 고객은 서버가 제거
VOC=V260807; MODE=internal; IDEM="voc-$VOC-$MODE-$(date +%H%M%S)"
: "${KEY:?}" "${BASE:?}" "${VOC:?}" "${IDEM:?}"
jq -n --arg body "담당자 확인 부탁드립니다. 재현 절차와 실행 로그를 VoC Hub 에 정리해 두었습니다." \
      --arg memo "내부 기록용 메모" \
   '{reply_body:$body, internal_memo:$memo, compose:"internal", status:"reviewing"}' > /tmp/voc-$MODE.json
curl -s -X POST "$BASE/$VOC/reply" -H "X-API-Key: $KEY" -H "Idempotency-Key: $IDEM" \
  -H 'Content-Type: application/json' --data-binary @/tmp/voc-$MODE.json \
| jq 'if .error then {FAIL:.error.code, msg:.error.message, retry:.error.retry_action}
      else {ok:.status, log_id, voc_status_updated, warnings} end'
```

응답의 `status` 가 `"success"` 일 때만 발송된 것이다. `voc_status_updated: false` 면
상태는 안 바뀐 것이고, `warnings` 는 삼키지 말고 그대로 보고한다 — `APP_BASE_URL` 이
없으면 `missing_voc_hub_link` 가 붙고 **링크 없는 내부 메일이 그대로 나간다.**

## 검증 기록

아래 세 가지는 실제 로컬 fake 스택에서 호출해 받은편지함으로 확인된 결과다
(2026-08-24). 새 인스턴스에 처음 붙일 때는 이 결과가 재현되는지 한 번은 실제로
확인한다.

| compose | 수신 | 제목 | 본문 |
|---|---|---|---|
| `raw` | 고객 | `[V260805] VoC reply - …` | 보낸 그대로 |
| `reply` | 고객 | `[V260805] VoC reply - …` | `[답변]` + `[질문 원문]` 인용 |
| `internal` | 담당자 | `(Internal Only) [V260807] …` | 인용 + VoC Hub 링크 + 안내 |

## 오류

| code | 조치 |
|---|---|
| `validation_error` (422) | 어느 필드인지 알려주지 않는다. 위 허용 필드 목록과 변수 가드를 대조 |
| `voc_not_found` (404) | 번호 오타 **또는** 키 스코프 밖 |
| `no_internal_recipient` (422) | `issue_owner_email` 이 비었거나 고객뿐. 멈추고 보고 |
| `ignored_recipient` (400) | 수신자가 전부 `@test.com` 등. 멈추고 보고 |
| `idempotency_conflict` (409) | 새 키로. 같은 키를 다른 요청에 다시 쓰지 않는다 |
| `operation_in_progress` (409) | **완전히 같은 요청 + 같은 키**로 재조회. 새 시도를 만들지 않는다 |
| `outcome_unknown` (409) | 자동 재발송 금지. 멈추고 결과에 그대로 남겨 나중에 메일함으로 확인하게 한다 |
| `mail_send_failed` (502) | 새 `Idempotency-Key` 로 한 번만 다시 시도한다. 두 번째도 실패하면 멈추고 보고 — 반복 재시도하지 않는다 |

`retry_action` 이 조치를 그대로 알려준다: `same_request` / `new_idempotency_key` /
`manual_review` / `none`.

## 상태 값

읽기(`?status=`)로는 6종 전부 되지만 **쓰기(`status`)는 4종뿐**이다:
`pending`·`reviewing`·`resolved`·`closed`. `registered`/`jira_failed` 는 서버 전용이라
넘기면 422 다 — `registered` 인 건을 `reviewing` 으로 옮기는 방향만 가능하고 되돌릴 수 없다.

## 흔한 실수

| 하기 쉬운 것 | 실제 |
|---|---|
| `reply_body_type` 없이 `reply_body` 만 PATCH | 기존 타입이 유지된다. `html` 건에 평문을 넣으면 줄바꿈이 사라진다 |
| PATCH 는 "아무데도 안 나간다" 고 설명 | 콜백 URL·Jira 로 `reply_body`·`internal_memo` 가 나간다 |
| `warnings: []` 를 "연동 성공" 으로 읽음 | 건너뛴 채널도 `[]` 다. 실패했을 때만 `integration_failed` 가 붙는다 |
| `compose` 를 생략 | 기본값이 `raw` 라 **조립 없이 고객에게 나간다.** 무발송이 아니다 |
| `"voc_id": 5` / `"voc_status": …` | `/web/*` 의 이름이다. 여기서는 경로에 `voc_number`, 본문에 `status` |
| `"to"`/`"subject"` 를 실어 보냄 | `extra="forbid"` 라 422. 수신자와 제목은 서버가 정한다 |
| `no_internal_recipient` 를 만나 `compose` 를 바꿔 재시도 | 수신자가 바뀐다. 멈추고 그대로 보고한다 |
| `-d '{"body":"'"$VAR"'"}'` | 한글·따옴표·개행에서 깨진다. `jq -n --arg` + `--data-binary @` |
| `IDEM` 을 안 채우고 실행 | curl 이 헤더를 빠뜨려 422. `: "${IDEM:?}"` 가드를 앞에 둔다 |
| `page` 없이 목록 조회 | 커서 모드로 빠진다. 목록을 뽑을 때는 `page=1` |
| `.items[]` 만 있는 `jq` 필터 | 오류가 "결과 0건" 으로 보인다. `.error` 분기를 넣는다 |
| 목록이 비어서 "처리할 게 없다" | 키 스코프 밖일 수 있다 |
| 저장된 `reply_body` 를 `compose:"reply"` 로 재발송 | 이미 조립본이면 인용이 한 겹 더 감긴다. `[질문 원문]` 유무 확인 |
| `issue_owner_email` 을 한 명으로 가정 | 문자열 컬럼이라 `"a@x.com,b@x.com,"` 이 들어올 수 있다 |
| 목록의 `issue_owner_email` 을 "Jira 매핑 담당자" 로 단정 | 실제 Jira 담당자는 `initial_jira_owner` 다. `issue_owner_email` 은 라우팅 규칙이 매치했을 때만 매핑에서 온 값이고, 아니면 등록 요청이 보낸 임의 값이거나 고객 이메일이다 |
| `initial_jira_owner` 를 "지금 매핑 설정" 으로 읽음 | 티켓 생성 시점의 스냅샷이다. 이후 매핑을 바꿔도 이미 만들어진 티켓의 이 값은 안 바뀐다 — 현재 설정은 `services.html` 에서 |
| 401 을 보고 세션 만료를 의심 | API 키는 만료되지 않는다. 키를 잘못 넘긴 것이다 |
| 키가 없어서 발급해 주려 함 | 발급은 사용자가 관리 화면에서 한다. 요청하고 기다린다 |
| 키를 `export` 로 넘겨받으려 함 | Bash 호출마다 새 셸이라 다음 호출에서 사라진다. 키 파일로 받는다 |
| 키 파일을 `. ~/.voc-hub.env` 로 읽음 | 형식이 어긋나면 셸이 키를 명령어로 실행해 로그에 노출된다. `sed` 로 값만 꺼낸다 |

## 멈춰야 하는 신호

- **키를 대신 발급하려 한다** (관리자 쿠키를 따거나 `/admin/api-keys` 를 부르려 한다)
- **어느 인스턴스에 붙었는지 남기지 않고 발송한다** — 기본값이 운영이다
- 키를 화면·요약·로그에 출력한다
- `no_internal_recipient` / `ignored_recipient` 를 만나고 `compose` 를 바꿔 우회한다
- `outcome_unknown` 을 보고 자동으로 재발송한다
- 여러 건을 처리하면서 건별 `Idempotency-Key`·결과를 남기지 않고 뭉뚱그려 보고한다
- 발송 실패(`status != "success"`)나 `warnings` 를 요약에서 생략한다

모두 **멈추고 그 사실을 결과에 그대로 남긴다** — 나중에 로그만 보고도 무엇이 왜
막혔는지 알 수 있어야 한다.
