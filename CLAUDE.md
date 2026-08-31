# skill_on_boarding

## Agent Factory — 로컬 fake 서버를 사용한다

이 프로젝트에서 `agent-factory-api` / `avatar-onboarding` 스킬을 쓸 때,
Agent Factory API의 base URL은 **사내 운영 서버가 아니라 로컬 fake 서버**다.

```
BASE="http://127.0.0.1:9090/api/v1/agent"
AUTH="Authorization: Bearer $AGENT_FACTORY_API_KEY"
```

- 스킬 문서(`agent-factory-api/SKILL.md`)에 적힌 `https://agent.samsungds.net:3355` 는
  이 프로젝트에서는 **사용하지 않는다**. 그 문서의 경로·페이로드·인증 규약은 그대로 유효하고,
  호스트만 위 값으로 치환한다.
- fake 서버 출처: https://github.com/dev-team-404/AgentToolbox (로컬 실행 중)
- 상호작용 문서: http://127.0.0.1:9090/api/docs
- API 키 발급: http://127.0.0.1:9090/me/api-keys
- 키는 `AGENT_FACTORY_API_KEY` 환경변수로 주입된다. 파일·커밋·로그에 값을 쓰지 않는다.

### 연결 실패 시

스킬의 "사내망/VPN/사내 CA" 트러블슈팅 절차를 따르지 말 것. 대신 로컬 서버 상태를 본다.

```
curl -sS -H "Authorization: Bearer $AGENT_FACTORY_API_KEY" \
  http://127.0.0.1:9090/api/v1/agent/me
```

### 알려진 동작 차이

`GET /avatars/tasks` 목록은 호출자 소유의 Task만 반환한다(다른 소유자의 Task는 빈 배열).
반면 `GET /avatars/tasks/{id}` 는 소유자와 무관하게 조회된다. 기존 Task 재사용을 판단할 때
목록이 비었다는 이유만으로 신규 생성하지 말고, Role의 중첩 `tasks[]` 로 교차 확인한다.

## 설치된 플러그인 (project 범주)

`skill-local` 마켓플레이스(`/mnt/c/work/skill-main`)에서 설치:
`avatar-onboarding`, `agent-factory-api`, `bedrock-cost-report`

`voc-hub-skills` 마켓플레이스(`/mnt/c/work/voc-hub/skills/voc-hub-skills`)에서 설치:
`voc-hub-responder`

두 마켓플레이스 모두 `source: directory` 라 경로를 그대로 참조한다. 디렉터리를 옮기면
`cache-miss` 로 로드가 깨지므로, 옮길 때는 `marketplace remove --scope project` →
`marketplace add <새 경로> --scope project` → 플러그인 재설치 순으로 재등록한다.

`voc-avatar-marketplace` 마켓플레이스(이 레포 안 `./voc-avatar-marketplace`)에서 설치:
`voc-avatar-partner`

앞의 둘과 달리 이 마켓플레이스는 레포 안에 있어 레포와 함께 커밋·이동한다. 다만
개발용 git worktree 등 임시 체크아웃에서 `marketplace add`를 실행했다면, 그 워크트리가
사라진 뒤에는 마찬가지로 재등록이 필요하다 — 실제 장기 체크아웃 경로를 기준으로
`marketplace remove` → `marketplace add ./voc-avatar-marketplace` → 플러그인
재설치를 거친다.

### voc-avatar-partner 사용 시 코디네이터(메인 세션) 규칙

`voc-avatar-partner`의 3-Role(운영자·모니터·자동 해결자)을 다룰 때, 이
메인 세션은 설계상 **코디네이터**다
(`voc-avatar-marketplace/plugins/voc-avatar-partner/README.md` §3.1~3.2).

**운영자가 내려야 할 판단(회신 여부·방식, 자동 해결자 위임 여부,
human-in-the-loop 응답)을 메인 세션이 대신 내리지 않는다.** 정답을 이미
알고 있어도 마찬가지다 — 모니터·자동 해결자의 결과를 받아 사람에게
"발송할까요?"라고 직접 묻지 말고, 반드시 `@voc-avatar-operator`
서브에이전트를 실제로 호출한다. 메인 세션이 대신 판단하면 사람에게
나가는 질문은 똑같아 보이지만, 그 판단은 `~/.voc-hub/operator-decisions.jsonl`에
남지 않고 이후 human-in-the-loop 선례 검색의 근거도 비게 된다 — 대화
로그만 봐서는 이 차이가 드러나지 않는다.

**운영자·자동 해결자가 만든 내용을 다른 서브에이전트에게 전달할 때,
내용을 요약·수정하거나 조사 범위·힌트를 덧붙이지 않는다.** 판단은
운영자가 내렸어도, 그 판단(또는 위임 지시문)을 실어 나르는 메인 세션이
"이 로컬 환경에서 확인 가능한 범위는..." 같은 자기 해석을 끼워 넣으면,
받는 쪽(예: 리졸버)이 자신의 실제 역할 정의(`voc-avatar-resolver.md`에
고정된 조사 대상)와 무관한 곳을 조사하게 만들 수 있다(2026-08-30 실제
사고, `voc-avatar-marketplace/plugins/voc-avatar-partner/README.md` §3.5
참고). 핸드오프 파일 경로가 있으면(§5.1) 그 경로만 그대로 전달하고,
파일 없이 대화 텍스트로 옮겨야 하는 내용은 원문 그대로 옮긴다 — 요약·재구성·범위
제안을 하지 않는다.
