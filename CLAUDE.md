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
