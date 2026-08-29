# voc-hub-skills

VoC Hub 운영용 에이전트 스킬을 담은 Claude Code 플러그인 마켓플레이스.
구조는 [convert-skill-to-opencode](https://github.com/panicdna/convert-skill-to-opencode)
를 따른다.

```
skills/voc-hub-skills/
├── .claude-plugin/
│   └── marketplace.json
└── plugins/
    └── voc-hub-responder/
        ├── .claude-plugin/
        │   └── plugin.json
        └── skills/
            └── voc-hub-responder/
                └── SKILL.md
```

## 플러그인

| 이름 | 설명 |
|---|---|
| `voc-hub-responder` | `X-API-Key` 통합 API 로 VoC 를 조회·초안·저장·발송한다. `compose` 가 수신자를 정하므로, 발송은 사람이 **모드·수신·제목**을 보고 승인한 뒤에만 한다. |

## 설치

둘 중 **하나만** 쓴다. 같이 쓰면 같은 이름이 두 번 등록된다.

```bash
# A. 플러그인으로 설치
/plugin marketplace add <repo>/skills/voc-hub-skills
/plugin install voc-hub-responder@voc-hub-skills

# B. 프로젝트 스킬로 복사 (개발 중일 때)
mkdir -p .claude/skills/voc-hub-responder
cp skills/voc-hub-skills/plugins/voc-hub-responder/skills/voc-hub-responder/SKILL.md \
   .claude/skills/voc-hub-responder/SKILL.md
```

**B 는 심볼릭 링크가 아니라 복사다.** WSL 에서 저장소가 `/mnt/c`(v9fs) 위에 있으면
`.claude/skills/` 안의 심볼릭 링크가 조용히 사라진다 — 이 저장소에서 두 번 겪었다.
링크가 끊겨도 `ls` 로는 티가 안 나고, 로더는 그냥 "스킬 없음" 으로 처리하므로 재시작 후
목록에서 사라진 걸 보고서야 알게 된다.

복사본이므로 **갈라질 수 있다.** 편집은 언제나 `skills/` 쪽 추적본에 하고, 그 다음 위
`cp` 를 다시 돌린다. 시험 전에 확인한다:

```bash
diff -q skills/voc-hub-skills/plugins/voc-hub-responder/skills/voc-hub-responder/SKILL.md \
        .claude/skills/voc-hub-responder/SKILL.md && echo 동일
```

스킬은 등록과 본문이 **세션 시작 시 함께 스냅샷**된다. 파일을 고쳐도 재시작 전까지는
옛 내용이 로드되므로, 반드시 `수정 → 복사 → 재시작 → 시험` 순서로 돈다.

## 이 스킬이 다루는 표면

`/api/integrations/v1/vocs` (`X-API-Key`). 레코드 키는 `voc_number`, 상태 필드는
`status`, 발송은 `POST /{voc_number}/reply` 에 `Idempotency-Key` 필수다.
쿠키 세션 표면(`/web/*`)과는 필드 이름부터 다르므로 섞지 않는다. 근거·검증 기록·오류
사전은 저장소의 `docs/voc-web-triage-runbook.md` 에 있다.

`skills/responding-to-voc` 는 같은 API 를 다루는 **다른** 스킬이다 — 무인·외부 호출용
정책 스킬로, 응답 비노출과 임시파일 파기를 강제한다. 이 플러그인과 목적이 다르다.

## OpenCode 로 변환할 때

변환 규칙 기준으로 이 스킬은 이미 통과 상태다 — `name` 이 정규식
`^[a-z0-9]+(-[a-z0-9]+)*$` 에 맞고, `description` 이 447자(1–1024)이며,
`allowed-tools` 가 없어 `opencode.json` 권한 패치가 필요 없고, 평탄화할 `metadata` 도
없다. 유일한 차이는 `compatibility` 키가 없다는 점으로, 변환 시 `opencode` 로 채우면 된다.
