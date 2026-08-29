# voc-avatar-partner 플러그인 패키징 — 설계

- 날짜: 2026-08-29
- 상태: 승인됨 (구현 대기)
- 관련 배경: `README.md`(VoC 자동 해결 파트너 아바타 프레임워크 소개),
  `agents/agent-factory/*.md`, `scripts/voc_operator_dashboard.py`,
  `.claude/commands/voc-operator-dashboard.md`

## 배경 및 목적

"VoC 자동 해결 파트너"는 운영자(`voc-avatar-operator`)·모니터(`voc-avatar-monitor`)·
자동 해결자(`voc-avatar-resolver`) 3개 subagent가 협업하는 시스템이다. 여기에
voc-operator-dashboard(`~/.voc-hub/operator-decisions.jsonl` 열람/편집)가
더해져 있다.

지금까지 이 셋은 **플러그인이 아니라 수동 배포** 상태였다:
- 3개 agent는 `agents/agent-factory/*.md`(레포 루트, 버전관리용 원본)를 사람이
  `~/.claude/agents/agent-factory/`(유저 스코프, 실제 로드 위치)로 수동 복사해서 썼다.
- 대시보드는 `scripts/voc_operator_dashboard.py` + `.claude/commands/voc-operator-dashboard.md`로
  이 프로젝트에만 존재했다.

이 작업은 이 셋을 하나의 **설치 가능한 Claude Code 플러그인**으로 묶어,
`claude plugin marketplace add` + `claude plugin install`로 배포·재현 가능하게 만든다.

## 범위

**포함**: 3개 agent + 대시보드(스크립트·테스트·슬래시 커맨드) + 이들의 설계 배경
문서(`README.md`)를 하나의 플러그인으로 패키징하고, 이 레포 자체를 그 플러그인이
속한 마켓플레이스로 등록한다.

**제외** (YAGNI):
- Agent Factory Card/Role/Task JSON(`voc-avatar-export/`, `archive/voc-autoresolve-avatar-export/`) —
  Claude Code 플러그인 포맷과 무관한 별도 표현이라 이번 패키징 대상이 아니다.
- 별도 git 레포로의 분리 — `skill-main`/`voc-hub-skills`처럼 완전히 독립된 레포로
  만들지 않는다. 이 레포 안의 하위 디렉터리 마켓플레이스로 충분하다.
- `voc-hub-responder` 스킬 자체의 재패키징 — 이미 별도 마켓플레이스(`voc-hub-skills`)에
  있고 이 작업의 대상이 아니다.

## 아키텍처

```
skill_on_boarding/                              (기존 레포, 다른 용도와 공존)
  voc-avatar-marketplace/                       (신규 — 하위 디렉터리형 마켓플레이스)
    .claude-plugin/
      marketplace.json
    plugins/
      voc-avatar-partner/
        .claude-plugin/
          plugin.json
        README.md                               ← 레포 루트 README.md 이동
        agents/
          voc-avatar-monitor.md                 ← agents/agent-factory/ 에서 이동
          voc-avatar-operator.md
          voc-avatar-resolver.md
        commands/
          voc-operator-dashboard.md             ← .claude/commands/ 에서 이동
        scripts/
          voc_operator_dashboard.py             ← 레포 루트 scripts/ 에서 이동
          __init__.py
          tests/
            __init__.py
            test_voc_operator_dashboard.py
```

`agents/`, `commands/` 디렉터리는 Claude Code가 이름 관례로 자동 인식한다 —
`plugin.json`에 개별 파일을 나열할 필요가 없다(`boris-workflow` 플러그인 등 기존
설치된 다른 플러그인에서 확인된 관례).

**단일 원본 원칙**: 위 이동 대상 파일들은 원래 위치에 사본을 남기지 않는다
(`git mv`). 플러그인 설치가 곧 유일한 사용 경로가 된다.

## 경로 참조 수정 (단순 이동으로 끝나지 않는 부분)

이동 후에도 정상 동작하려면 레포 상대 경로를 참조하던 부분을 플러그인 설치
위치에 무관하게 만들어야 한다. Claude Code는 플러그인 실행 컨텍스트에서
`${CLAUDE_PLUGIN_ROOT}` 환경변수를 그 플러그인의 실제 설치 루트로 주입한다
(기존 설치된 `github-workflow`, `superpowers` 플러그인의 스킬·훅에서 실사용
확인됨).

| 파일 | 기존 | 변경 |
|---|---|---|
| 3개 agent `.md` | `프로젝트 루트 \`README.md\`를 참고한다` | `\`${CLAUDE_PLUGIN_ROOT}/README.md\`를 참고한다` |
| `commands/voc-operator-dashboard.md` | `python3 scripts/voc_operator_dashboard.py` | `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/voc_operator_dashboard.py"` |

`~/.voc-hub/operator-decisions.jsonl` 등 홈 디렉터리 기준 경로는 원래도
레포-상대가 아니므로 수정 대상이 아니다.

## `plugin.json`

기존 관례(`avatar-onboarding`, `voc-hub-responder`)를 그대로 따른다:

```json
{
  "name": "voc-avatar-partner",
  "description": "VoC 자동 해결 파트너 — VoC Hub를 감시·판단·응답하고 필요하면 GitHub PR까지 만드는 운영자·모니터·자동 해결자 3-role 협업 시스템과, 운영자의 human-in-the-loop 판단 이력을 열람·편집하는 로컬 대시보드.",
  "version": "1.0.0",
  "license": "Apache-2.0",
  "author": { "name": "panicdna" }
}
```

## `marketplace.json`

```json
{
  "name": "voc-avatar-marketplace",
  "owner": { "name": "panicdna", "url": "https://github.com/panicdna" },
  "description": "VoC 자동 해결 파트너(운영자·모니터·자동 해결자 + 이력 대시보드) 플러그인 마켓플레이스.",
  "plugins": [
    {
      "name": "voc-avatar-partner",
      "source": "./plugins/voc-avatar-partner",
      "description": "VoC 자동 해결 파트너 — 운영자·모니터·자동 해결자 3-role 협업 시스템과 이력 대시보드.",
      "category": "developer-tools"
    }
  ]
}
```

## 등록·전환 절차 (기존 수동 배포 상태 정리 포함)

1. `claude plugin marketplace add ./voc-avatar-marketplace`
2. `claude plugin install voc-avatar-partner@voc-avatar-marketplace --scope project`
3. **정리(중복 정의 방지)**: 기존 `~/.claude/agents/agent-factory/*.md`(유저 스코프
   수동 복사본) 3개를 삭제한다. 지우지 않으면 같은 이름의 agent가 유저 스코프(수동
   복사본)와 project 스코프(플러그인)에 동시에 존재해 어느 쪽이 실제로 로드되는지
   불분명해진다.
4. `git mv`로 이동했으므로 원래 위치(`agents/agent-factory/`,
   `.claude/commands/voc-operator-dashboard.md`, 레포 루트 `scripts/`, `README.md`)엔
   더 이상 파일이 없다.

## 검증

- `claude plugin list`에서 `voc-avatar-partner@voc-avatar-marketplace`가
  project 스코프로 `enabled` 확인
- `/voc-operator-dashboard` 슬래시 커맨드를 실행해 새 경로(`${CLAUDE_PLUGIN_ROOT}`
  기준)에서도 정상 기동하는지 확인 — `http://localhost:8765` 응답 확인
- `python3 -m unittest`로 이동된 테스트 스위트(35개)가 이동 후에도 그대로
  통과하는지 확인 — 특히 `sys.path.insert` 기준 상대 경로가 이동 후에도 유효한지
- `@voc-avatar-monitor`, `@voc-avatar-operator`, `@voc-avatar-resolver` 세
  agent를 대화창에서 한 번씩 멘션해 플러그인 설치본이 정상 응답하는지 확인
- 3개 agent의 `README.md` 참조(`${CLAUDE_PLUGIN_ROOT}/README.md`)가 실제로
  파일을 찾아 읽히는지 확인
