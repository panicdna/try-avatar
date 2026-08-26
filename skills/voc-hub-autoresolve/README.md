# voc-hub-autoresolve

VoC Hub 통합 API로 **담당자 본인에게 Jira로 배정된 미해결 VoC 1건을 사람
승인 없이 끝까지 자동으로 처리**하는 서브 에이전트입니다.

## ⚠️ 승인 없이 고객에게 메일이 나갑니다

이 플러그인은 발송 전 확인 단계가 없습니다. 대신 범위를 좁혀 위험을
상쇄합니다 — 한 번 실행에 정확히 1건, 그것도 Jira 티켓이 실제로 나에게
배정된 건만 대상입니다. 여러 건을 한 번에 처리하지 않습니다.

**`VOC_INTEGRATION_BASE_URL`은 선택 사항이 아닙니다.** 이 에이전트는
`voc-hub-responder` 스킬의 호스트 자동 감지를 그대로 물려받으면서도, 그
스킬의 "감지한 호스트를 사람에게 보여주고 확인받는" 단계는 생략합니다.
자동 감지 1순위는 **운영 인스턴스**입니다 — `~/.voc-hub.env`에 이 값을
비워두면 확인 기회 없이 운영 서버로 실제 고객 메일이 나갈 수 있습니다.
로컬 fake 스택에서 시험하려면 반드시 아래처럼 값을 명시하세요.

승인 기반으로 여러 건을 검토하며 처리하고 싶다면 `voc-hub-skills`
마켓플레이스의 `voc-hub-responder` 플러그인을 대신 쓰세요.

## 설치

```bash
claude plugin marketplace add ./skills/voc-hub-autoresolve --scope local
claude plugin install voc-hub-autoresolve@voc-hub-autoresolve -s local -y
```

에이전트 등록과 본문은 **세션 시작 시 함께 스냅샷**됩니다. `agents/voc-hub-autoresolve.md`를
고쳐도 다음 세션을 새로 시작하기 전까지는 옛 내용이 그대로 로드됩니다. 또한
`claude plugin update`는 버전 번호만 비교하므로, 버전을 올리지 않고 파일만 고친
경우에는 업데이트가 아무 변화도 감지하지 못합니다 — 이때는
`claude plugin uninstall` 로 지운 뒤 플러그인 캐시를 삭제하고 다시
`install` 해야 편집이 반영됩니다.

## 필요한 설정

`~/.voc-hub.env`에 다음 세 줄이 필요합니다 (파일 형식이며 `export`로
넘기지 않습니다 — 이유는 `voc-hub-responder` 스킬 문서 참고):

```
VOC_INTEGRATION_BASE_URL=http://localhost:8080
VOC_INTEGRATION_API_KEY=<발급받은 키>
VOC_ASSIGNEE_EMAIL=<본인 이메일>
```

`VOC_ASSIGNEE_EMAIL`이 없으면 에이전트는 기본값을 채우지 않고 멈춥니다.

`VOC_ASSIGNEE_EMAIL`은 "내 이메일 주소"가 아니라 **VoC 레코드의
`initial_jira_owner` 필드에 실제로 찍히는 값과 문자 그대로 같아야** 합니다.
이 필드는 각 서비스의 Jira 연동 설정 화면에서 관리자가 자유 입력한
문자열이라 이메일 형식이 아닐 수도 있습니다(Jira 계정명 등). 목록 API
응답이나 관리 화면에서 그 값을 먼저 확인한 뒤 그대로 붙여 넣으세요 —
철자나 형식이 조금이라도 다르면 완전 일치 비교라 아무 오류 없이
"배정된 VoC 없음"으로 조용히 실패합니다.

## 사용

`Agent` 도구로 `voc-hub-autoresolve:voc-hub-autoresolve`를 호출합니다.
