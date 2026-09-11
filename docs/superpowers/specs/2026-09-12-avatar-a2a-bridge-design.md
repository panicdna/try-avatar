# 아바타 간 A2A(Agent2Agent) 원격 통신 — 설계

- 날짜: 2026-09-12
- 상태: 1단계 구현 완료 (검증됨) — `org_tools/avatar-a2a-bridge/plugins/avatar-a2a-bridge/`
  (독립 마켓플레이스 `avatar-a2a-bridge-marketplace`; 2026-09-12 사용자 지시로
  `org_tools/skill`에 얹혀 있던 것을 `voc-avatar-marketplace`와 같은 패턴의
  독립 마켓플레이스로 옮김)
- 관련 배경: `CLAUDE.md`(Agent Factory 로컬 fake 서버, voc-avatar-partner 코디네이터
  규칙), `agent-factory-api/SKILL.md`, `voc-avatar-marketplace/plugins/voc-avatar-partner/README.md` §3

## 배경 및 목적

지금까지 이 프로젝트의 "다중 에이전트 협업"(`voc-avatar-partner`의 운영자·모니터·
자동 해결자)은 전부 **하나의 Claude Code 세션 안에서** 서브에이전트(Task tool /
`@voc-avatar-*` 멘션)로 호출된다. 메인 세션이 항상 코디네이터로 사이에 끼고,
세 Role은 프로세스도 네트워크도 공유하지 않는 진짜 원격 통신을 한 적이 없다.

이 작업은 서로 다른 **프로세스**(1단계: 같은 머신의 다른 Claude Code 세션)에
떠 있는 두 아바타가 코디네이터 없이 직접 HTTP로 통신하도록, 실제 오픈 표준인
**A2A(Agent2Agent) 프로토콜 v1.0**(Google → Linux Foundation, 150+ 조직 지원,
공식 스펙: https://a2a-protocol.org/latest/specification/)을 준수하는 skill을
만든다.

**용어 충돌 주의**: A2A 프로토콜의 "Agent Card"(`/.well-known/agent-card.json`,
discovery용 공개 문서)와 Agent Factory의 "Avatar Card/Agent Card"
(`agent-factory-api`의 `POST /avatars/cards`, 내부 책임 카탈로그)는 이름만
같고 다른 개념이다. 이 문서와 이후 구현에서 전자는 **A2A Agent Card**, 후자는
**Avatar Card**로만 부른다.

## 범위

**포함 (1단계)**:
- 같은 머신, 서로 다른 Claude Code 세션(별도 프로세스, 별도 로컬 포트) 간 A2A
  통신
- 아바타를 A2A 서버로 노출하는 `serve` 기능 + 원격 아바타를 호출하는 `call` 기능
- A2A v1.0의 최소 부분집합: A2A Agent Card discovery, `message/send`
  (JSON-RPC 2.0 동기 호출), task 상태 조회(`tasks/get`)
- Avatar Card/Role/Task(Agent Factory) → A2A Agent Card `skills[]` 변환 계층

**제외 (YAGNI, 1단계)**:
- 실제 다른 머신 간 통신(공인 도메인·TLS 인증서·방화벽) — 로컬 검증 이후 2단계
- `message/stream`(SSE 스트리밍), push notification(webhook) — 필요해지면 추가
- gRPC / REST 바인딩 — JSON-RPC 2.0 바인딩만 먼저
- 조직 밖 실제 A2A 에이전트(다른 벤더)와의 상호운용 실측 — 스펙 준수까지가
  목표이고, 외부 에이전트 연동 테스트는 범위 밖

## 아키텍처

```
Claude Code 세션 A (아바타 "voc-avatar-operator" 로드)
  └─ skill: avatar-a2a-bridge --serve
       └─ 로컬 A2A 서버, bind 127.0.0.1:<portA>
            GET /.well-known/agent-card.json  ← Avatar Card에서 변환해 캐싱
            POST /  (JSON-RPC 2.0: message/send, tasks/get)

Claude Code 세션 B (아바타 "voc-avatar-resolver" 로드)
  └─ skill: avatar-a2a-bridge --call <peer-name> "<message>"
       └─ 로컬 레지스트리에서 peer-name → agent-card URL 조회
       └─ GET http://127.0.0.1:<portA>/.well-known/agent-card.json (discovery)
       └─ POST http://127.0.0.1:<portA>/ {"method":"message/send", ...}
       └─ task 상태를 폴링해 완료/실패 결과를 세션 B에 반환
```

- **레지스트리**: 로컬 파일 하나(예: `~/.a2a-avatars/registry.json`)에
  `{avatar_name: {port, agent_card_url, started_at}}`. `serve` 시작 시 등록,
  `call` 시 조회. 실제 DNS가 없는 localhost 환경이므로 A2A 표준 discovery
  (`/.well-known/agent-card.json`을 도메인에서 바로 GET)를 흉내 내는 대체 수단.
- **A2A Agent Card 생성**: `serve`가 시작할 때 `agent-factory-api` 스킬로
  해당 Avatar Card를 조회하고, `responsibility` → A2A `description`, 연결된
  Role/Task 제목·설명 → A2A `skills[]` 항목으로 변환해 캐싱한다. Avatar Card가
  바뀌면(예: `PATCH /avatars/cards/{id}`) 캐시가 stale해질 수 있음 — 재기동 또는
  명시적 refresh로 갱신(자동 watch는 1단계 범위 밖).
- **인증**: 같은 머신의 로컬 프로세스 간이므로 시작하기는 쉽지만, A2A 스펙의
  권고("Agent Card에 정적 비밀 넣지 말고 out-of-band 동적 자격증명 사용")를
  1단계부터 지킨다 — `serve`가 기동 시 랜덤 토큰을 생성해 퍼미션 600 파일에
  쓰고, 레지스트리에는 토큰이 아니라 "토큰 파일 경로"만 남긴다. `call`은 같은
  사용자 권한으로 그 파일을 읽어 `Authorization: Bearer`로 사용한다.
- **구현 기반**: 공식 참조 SDK `a2a-sdk`(PyPI, 현재 1.1.2, 이 환경에서 설치
  가능 확인됨)를 재사용한다. 사용자가 "공식 스펙 준수"를 택했으므로, JSON-RPC
  메시지 포맷·task 상태 머신을 직접 구현해 스펙 버그를 만드는 대신 SDK에 위임한다.

## 코디네이터 순수성 규칙의 확장

`CLAUDE.md`가 명시한 "운영자·자동 해결자가 만든 내용을 다른 서브에이전트에게
전달할 때 요약·수정하거나 조사 범위·힌트를 덧붙이지 않는다"는 원칙은 지금까지
같은 세션 안의 서브에이전트 relay(Agent tool)에만 적용됐다. `avatar-a2a-bridge`가
생기면 이 원칙은 **A2A `message/send`의 아웃바운드 payload에도 그대로 적용돼야
한다** — `call`을 실행하는 세션이 호출자(사람 또는 다른 Role)가 준 텍스트를
그대로 A2A message part에 담아 보내고, "이 로컬 환경에서 확인 가능한 범위는..."
같은 자기 해석을 끼워 넣지 않는다. 핸드오프 파일 경로가 있으면 그 경로를 그대로
전달하는 기존 규칙과 동일한 이유(2026-08-30 사고 사례)다.

## 미해결 질문 — 결정 (2026-09-12, 사용자 확인)

1. **레지스트리 위치**: 유저 홈 `~/.a2a-avatars/`(`$A2A_AVATARS_DIR`로 override
   가능). 여러 프로젝트에서 동시에 아바타를 띄울 가능성을 고려.
2. **포트 정책**: OS가 임의 할당 + 레지스트리에 실제 포트 기록.
3. **배포 대상**: 처음엔 `org_tools/skill` plugin 마켓플레이스에 얹었으나,
   2026-09-12에 사용자 지시로 `voc-avatar-marketplace`와 같은 패턴의 **독립
   마켓플레이스** `org_tools/avatar-a2a-bridge/`(자체 `marketplace.json` +
   `plugins/avatar-a2a-bridge/`)로 옮겼다 — CLAUDE.md가 기록한 기존 4개
   마켓플레이스 중 `voc-hub-skills`/`voc-operator-dashboard`도 `org_tools/`
   밑 독립 디렉터리 패턴이라 이쪽이 기존 관례에 더 맞는다. `npx skills add`
   경로는 1단계 대상 아님.
4. **`serve` 생명주기**: 띄운 Claude Code 세션과 함께 종료. `SIGINT`/`SIGTERM`에서
   레지스트리 등록을 정리하고, `SIGKILL` 등으로 정리 없이 죽으면 다음 레지스트리
   읽기 때 pid 생존 여부로 자동 prune(수동 정리 불필요).

## 구현 노트 — 로컬 환경에서 실측으로 발견한 것

- **A2A Python 참조 SDK(`a2a-sdk` 1.1.2, PyPI)를 그대로 재사용**했다 —
  `AgentCard`/`AgentSkill`/`DefaultRequestHandler`/`TaskUpdater`/`create_client`
  등은 실제 설치된 패키지를 파이썬으로 introspect해서 시그니처를 확인한
  것이지, 문서만 보고 짐작한 것이 아니다. 공식 helloworld 샘플과 대부분
  일치했지만 몇 군데는 샘플과 실제 설치 버전(1.1.2)이 달랐다:
  - `create_client()`와 `client.close()`는 **coroutine**이라 `await` 필요
    (샘플 코드엔 이 부분이 생략돼 있었다).
  - `client.send_message()`가 돌려주는 `Task`는 `TASK_STATE_SUBMITTED` 상태의
    스냅샷 하나뿐이다 — 실제 완료를 보려면 호출자가 **직접 `tasks/get`을
    폴링**해야 한다(자동으로 완료까지 기다려주지 않는다).
- **포트를 "bind → close → 재사용" 방식으로 고르면 이 환경에서 5번 중
  4번꼴로 `EADDRINUSE`가 났다** — 교과서적으로는 안전한 패턴인데도. 원인을
  더 파고들진 않았고, 대신 **소켓을 한 번 bind한 뒤 닫지 않고 그 파일
  디스크립터를 그대로 `uvicorn.run(fd=...)`에 넘기는 방식**으로 바꿔
  경쟁 자체를 없앴다(`serve.py`의 `bind_socket()`). 동시에 3개 인스턴스를
  띄워도 포트 충돌 없이 전부 정상 기동하는 것으로 재현 확인했다.
- **인증 미들웨어**(Agent Card GET은 공개, JSON-RPC POST만 Bearer 토큰 요구)를
  토큰 없음/틀린 토큰/올바른 토큰 세 경우 모두 실제 HTTP 왕복으로 확인했다 —
  틀린 토큰은 `a2a.client.A2AClientError`로 깔끔하게 예외가 올라온다(잡아서
  사람이 읽을 메시지로 바꿔줌).

## 검증

- 실제 설치된 `a2a-sdk[http-server]==1.1.2` + `uvicorn` 기준, 서버 기동 →
  Agent Card GET(무인증) → `message/send`(Bearer 인증) → `tasks/get` 폴링 →
  `TASK_STATE_COMPLETED` + 아티팩트 텍스트까지 실제 HTTP 왕복으로 확인.
- 서로 다른 이름으로 **3개 서버를 동시에 기동**해 포트 충돌 없이 각자
  독립적으로 응답하는 것 확인(같은 머신, 다른 프로세스 시나리오의 최소 재현).
- `--exec-command`가 실제 서브프로세스를 거치는지 `rev`로 왕복 확인(입력을
  뒤집어 돌려받음 — 내부 echo가 아니라 진짜 subprocess 경유임을 입증).
- `--skills-file`로 넘긴 skill 목록이 서빙되는 Agent Card JSON에 그대로
  반영되는지 확인.
- `SIGTERM` 후 레지스트리에서 정상 등록 해제(`call.py --list`에서 사라짐)
  확인. 테스트에 쓴 레지스트리는 전부 `$A2A_AVATARS_DIR`로 격리했고, 실사용자
  홈의 `~/.a2a-avatars/`는 이 작업 동안 생성된 적이 없음을 확인했다.

## 다음 단계

- (선택) `voc-avatar-partner`의 한 Role을 `--skills-file`로 실제 매핑해
  두 번째 Claude Code 세션에서 걸어보는 실전 시나리오 검증.
- `--exec-command`로 실제 `claude -p` 연동을 한 아바타에 한정해 붙여볼지
  결정(비용 발생하므로 사용자 승인 후).
- 2단계(실제 다른 머신 간 통신: TLS, 실 도메인, 방화벽)는 1단계가 실사용에서
  검증된 뒤 별도 설계 문서로 진행.
