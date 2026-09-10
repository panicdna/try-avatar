---
name: voc-operator-dashboard
description: Use when a person wants to view, search, edit, or delete entries in a VoC operator's decision history (operator-decisions.jsonl), or browse its handoff/*.md files, through a local web page. 판단 이력(operator-decisions.jsonl) 열람·검색·수정·삭제, 핸드오프 파일 현황 확인, "대시보드 띄워줘"에 사용한다. Launches a local-only (127.0.0.1) read/write dashboard server — never call this to view someone else's history without checking whose $VOC_HUB_DIR is being targeted first.
---

# VoC Operator 이력 대시보드

VoC 운영자(operator) Role이 쌓은 판단 이력(`operator-decisions.jsonl`)과 핸드오프
파일(`handoff/*.md`)을 로컬 웹페이지로 열람·검색·수정·삭제한다. 이 스킬은
`voc-avatar-marketplace` 플러그인의 `voc-operator-dashboard` 커맨드와 같은
스크립트(`scripts/voc_operator_dashboard.py`, 표준 라이브러리만 사용)를 그대로
쓴다 — 원본과 바이트 단위로 동일하게 유지할 것. 이 파일은 그 스크립트를 **커맨드가
아니라 Task/Role 경유로도** 실행할 수 있게 만드는 wrapper 문서다.

`voc-hub-responder`와는 **독립적인 별도 plugin**이다 — VoC 발송/수신만 필요한
프로젝트는 `voc-hub-responder`만 설치하고 이 스킬은 설치하지 않는 선택이 가능해야
하므로, 그 plugin의 `skills/` 밑에 넣지 않는다.

## 이 설치의 $VOC_HUB_DIR을 먼저 정확히 알아낸다

**스크립트의 기본 경로 추정(`resolve_voc_hub_dir` — 실행 시점 디렉터리의 git 루트로부터
`~/.voc-hub-<slug>/`를 계산)을 그대로 믿지 않는다.** 이 값은 `voc-avatar-marketplace`
플러그인 설치를 전제로 한 계산법이고, Agent Factory Role/Task로 설치된 환경은 다른
규칙을 쓸 수 있다 — 실제로 한 설치(예: `avatar_inst6`)는 `$VOC_HUB_DIR`을
`~/.voc-hub-<slug>/`가 아니라 프로젝트 상대 경로(`<project>/voc_hub`)로 고정해 두고
있었다. 항상 다음 순서로 실제 값을 확인한 뒤 `--file`/`--handoff-dir`로 **명시
지정**한다 — 스크립트의 자동 계산에 맡기지 않는다:

1. 이 Task/Role을 호출한 설치의 개인 프로파일(`~/.agent-factory/avatars/<card-slug>/profile.md`
   "지식 참조" 절)에 `$VOC_HUB_DIR` 값이 문서화돼 있으면 그걸 그대로 쓴다.
2. 프로파일에 없고 `voc-avatar-marketplace` 플러그인이 설치된 프로젝트라면
   `python3 <해당 플러그인>/scripts/voc_operator_dashboard.py --print-dir`로 계산된
   값을 확인한다.
3. 어느 쪽도 없으면 사람에게 물어본다 — 짐작해서 엉뚱한(또는 남의) 이력 파일을 열지
   않는다.

## 실행 절차

1. 위에서 확정한 경로로 다음을 백그라운드 실행한다(`run_in_background: true`):
   ```bash
   python3 scripts/voc_operator_dashboard.py \
     --file "$VOC_HUB_DIR/operator-decisions.jsonl" \
     --handoff-dir "$VOC_HUB_DIR/handoff"
   ```
2. 몇 초 뒤 출력을 확인한다.
   - `VoC Operator 대시보드: http://localhost:8765 ...`가 보이면 그 URL을 그대로 알려준다.
   - `포트 8765가 이미 사용 중입니다 ...`가 보이면, 새로 띄우려 하지 말고 이미 다른
     인스턴스가 떠 있을 수 있다는 안내를 그대로 전달한다. 그 인스턴스가 지금 요청받은
     `$VOC_HUB_DIR`을 가리키고 있는지는 `curl -s http://localhost:8765/ | grep -o 'value="[^"]*"'`로
     확인하고, 다르면 `/api/source`·`/api/handoff-source`에 POST해 그 인스턴스를
     원하는 경로로 다시 가리킨다(UI의 "열기" 버튼과 같은 동작 — 서버를 새로 띄울
     필요 없음). 다만 그 인스턴스가 언제부터 떠 있었는지(`ps -eo pid,lstart,cmd | grep
     voc_operator_dashboard`) 함께 확인한다 — 오래된 프로세스는 코드가 갱신되기 전
     버전으로 떠 있을 수 있다(파일을 최신으로 바꿔도 이미 뜬 프로세스의 동작은 안
     바뀐다).
3. 사람이 "종료해줘"라고 하면 해당 백그라운드 프로세스를 정리한다 — 상시 구동
   데몬이 아니다.

## 항목별 수정·삭제에 대한 주의

이 대시보드는 판단 이력을 **직접 지우거나 고칠 수 있다**(`do_PATCH`/`do_DELETE`,
쓰기 전 항상 `<파일>.bak-<epoch>` 백업). 이 이력은 운영자의 human-in-the-loop
선례 검색·재활용의 유일한 근거이므로, 수정·삭제를 실행하기 전에 **어떤 항목을 왜
바꾸는지 사람에게 확인**한다 — 검색·열람에는 확인이 필요 없지만, 쓰기 동작은
되돌리기 어려운 감사 기록 변경이다.
