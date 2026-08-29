# voc-avatar-partner 플러그인 패키징 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VoC 자동 해결 파트너의 3개 subagent(monitor/operator/resolver)와 voc-operator-dashboard(스크립트+슬래시커맨드)를 하나의 설치 가능한 Claude Code 플러그인(`voc-avatar-partner`)으로 묶고, 이 레포 안에 그 플러그인을 담는 마켓플레이스(`voc-avatar-marketplace`)를 만들어 `claude plugin marketplace add` + `claude plugin install`로 설치되게 한다.

**Architecture:** 레포 루트에 흩어져 있던 파일(`agents/agent-factory/*.md`, `scripts/`, `.claude/commands/voc-operator-dashboard.md`, `README.md`)을 `git mv`로 `voc-avatar-marketplace/plugins/voc-avatar-partner/` 아래로 이동해 단일 원본으로 만든다. 레포 상대 경로를 참조하던 부분(`README.md` 링크, 스크립트 경로)은 Claude Code가 플러그인 실행 시 주입하는 `${CLAUDE_PLUGIN_ROOT}` 환경변수 참조로 바꾼다. 이동이 끝나면 마켓플레이스 등록 → 플러그인 설치 → 기존 수동 배포 상태(유저 스코프 agent 사본) 정리 순으로 전환한다.

**Tech Stack:** Claude Code 플러그인/마켓플레이스 매니페스트(JSON), 기존 Python3 표준 라이브러리 스크립트(변경 없음, 위치만 이동).

**Spec:** `docs/superpowers/specs/2026-08-29-voc-avatar-partner-plugin-design.md`

## Global Constraints

- 이동 대상 파일은 원래 위치에 사본을 남기지 않는다(`git mv`, 단일 원본 원칙) — spec "아키텍처"
- `agents/`, `commands/` 디렉터리명은 Claude Code가 자동 인식하므로 `plugin.json`에 개별 파일을 나열하지 않는다 — spec "아키텍처"
- 레포 상대 경로 참조(3개 agent의 `README.md` 참조, 슬래시커맨드의 스크립트 경로)는 전부 `${CLAUDE_PLUGIN_ROOT}` 기준으로 바꾼다 — spec "경로 참조 수정"
- `~/.voc-hub/operator-decisions.jsonl` 등 홈 디렉터리 기준 경로는 수정하지 않는다(원래도 레포-상대가 아님) — spec "경로 참조 수정"
- 플러그인은 project 스코프로 설치한다 — 브레인스토밍 확정 사항
- 마켓플레이스 이름 `voc-avatar-marketplace`, 플러그인 이름 `voc-avatar-partner` — spec "plugin.json"/"marketplace.json"

---

## 파일 구조

- Create: `voc-avatar-marketplace/.claude-plugin/marketplace.json`
- Create: `voc-avatar-marketplace/plugins/voc-avatar-partner/.claude-plugin/plugin.json`
- Move: `README.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/README.md`
- Move: `agents/agent-factory/voc-avatar-monitor.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-monitor.md`
- Move: `agents/agent-factory/voc-avatar-operator.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-operator.md`
- Move: `agents/agent-factory/voc-avatar-resolver.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-resolver.md`
- Move: `scripts/` (전체 — `voc_operator_dashboard.py`, `__init__.py`, `tests/`) → `voc-avatar-marketplace/plugins/voc-avatar-partner/scripts/`
- Move: `.claude/commands/voc-operator-dashboard.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/commands/voc-operator-dashboard.md`

---

### Task 1: 마켓플레이스·플러그인 매니페스트 스캐폴딩 + README 이동

**Files:**
- Create: `voc-avatar-marketplace/.claude-plugin/marketplace.json`
- Create: `voc-avatar-marketplace/plugins/voc-avatar-partner/.claude-plugin/plugin.json`
- Move: `README.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/README.md`

**Interfaces:**
- Produces: `voc-avatar-marketplace/plugins/voc-avatar-partner/` 디렉터리(Task 2, 3의 이동 대상)

- [ ] **Step 1: 디렉터리 생성**

```bash
mkdir -p voc-avatar-marketplace/.claude-plugin
mkdir -p voc-avatar-marketplace/plugins/voc-avatar-partner/.claude-plugin
```

- [ ] **Step 2: marketplace.json 작성**

`voc-avatar-marketplace/.claude-plugin/marketplace.json`:

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

- [ ] **Step 3: plugin.json 작성**

`voc-avatar-marketplace/plugins/voc-avatar-partner/.claude-plugin/plugin.json`:

```json
{
  "name": "voc-avatar-partner",
  "description": "VoC 자동 해결 파트너 — VoC Hub를 감시·판단·응답하고 필요하면 GitHub PR까지 만드는 운영자·모니터·자동 해결자 3-role 협업 시스템과, 운영자의 human-in-the-loop 판단 이력을 열람·편집하는 로컬 대시보드.",
  "version": "1.0.0",
  "license": "Apache-2.0",
  "author": { "name": "panicdna" }
}
```

- [ ] **Step 4: 매니페스트 검증**

Run: `claude plugin validate ./voc-avatar-marketplace`
Expected: `Validating marketplace manifest: .../voc-avatar-marketplace/.claude-plugin/marketplace.json` 뒤 `✔ Validation passed`

Run: `claude plugin validate ./voc-avatar-marketplace/plugins/voc-avatar-partner`
Expected: `Validating plugin manifest: .../plugin.json` 뒤 `✔ Validation passed`

- [ ] **Step 5: README 이동**

```bash
git mv README.md voc-avatar-marketplace/plugins/voc-avatar-partner/README.md
```

- [ ] **Step 6: 커밋**

```bash
git add voc-avatar-marketplace/.claude-plugin/marketplace.json \
        voc-avatar-marketplace/plugins/voc-avatar-partner/.claude-plugin/plugin.json \
        voc-avatar-marketplace/plugins/voc-avatar-partner/README.md README.md
git commit -m "feat(voc-avatar-partner): scaffold plugin marketplace and move README

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: 3개 agent 이동 + README 참조 수정

**Files:**
- Move: `agents/agent-factory/voc-avatar-monitor.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-monitor.md`
- Move: `agents/agent-factory/voc-avatar-operator.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-operator.md`
- Move: `agents/agent-factory/voc-avatar-resolver.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-resolver.md`

**Interfaces:**
- Consumes: `voc-avatar-marketplace/plugins/voc-avatar-partner/README.md`(Task 1)

3개 파일 모두 다음 줄을 동일하게 갖고 있다(디자인 배경 설명 문단의 마지막 줄):

```
다이어그램은 프로젝트 루트 `README.md`를 참고한다.
```

이걸 `${CLAUDE_PLUGIN_ROOT}` 기준 참조로 바꾼다. 그 외 내용은 손대지 않는다.

- [ ] **Step 1: 디렉터리 생성 + 이동**

```bash
mkdir -p voc-avatar-marketplace/plugins/voc-avatar-partner/agents
git mv agents/agent-factory/voc-avatar-monitor.md voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-monitor.md
git mv agents/agent-factory/voc-avatar-operator.md voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-operator.md
git mv agents/agent-factory/voc-avatar-resolver.md voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-resolver.md
```

- [ ] **Step 2: 이동 확인 — 원래 디렉터리가 비었는지 확인**

Run: `ls agents/agent-factory/ 2>&1; ls agents/ 2>&1`
Expected: 둘 다 파일 없음(디렉터리 자체는 아직 남아있을 수 있음 — Step 5에서 정리)

- [ ] **Step 3: README 참조를 `${CLAUDE_PLUGIN_ROOT}` 기준으로 수정**

```bash
sed -i 's#다이어그램은 프로젝트 루트 `README.md`를 참고한다.#다이어그램은 `${CLAUDE_PLUGIN_ROOT}/README.md`를 참고한다.#' \
  voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-monitor.md \
  voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-operator.md \
  voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-resolver.md
```

- [ ] **Step 4: 수정 확인 — 남은 "프로젝트 루트" 참조가 없는지 확인**

Run: `grep -rn "프로젝트 루트" voc-avatar-marketplace/plugins/voc-avatar-partner/agents/`
Expected: 아무 결과도 안 나옴(exit code 1)

Run: `grep -c 'CLAUDE_PLUGIN_ROOT' voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-monitor.md voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-operator.md voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-resolver.md`
Expected: 3개 파일 모두 `:1`

- [ ] **Step 5: 빈 디렉터리 정리**

```bash
rmdir agents/agent-factory agents 2>&1 || true
```

- [ ] **Step 6: 플러그인 매니페스트 재검증(agents/ 인식 확인)**

Run: `claude plugin validate ./voc-avatar-marketplace/plugins/voc-avatar-partner`
Expected: `✔ Validation passed`

- [ ] **Step 7: 커밋**

```bash
git add -A agents voc-avatar-marketplace/plugins/voc-avatar-partner/agents
git commit -m "feat(voc-avatar-partner): move 3 subagents into plugin package

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: 대시보드(스크립트+테스트+슬래시커맨드) 이동 + 경로 수정 + 테스트 재확인

**Files:**
- Move: `scripts/` (전체 디렉터리) → `voc-avatar-marketplace/plugins/voc-avatar-partner/scripts/`
- Move: `.claude/commands/voc-operator-dashboard.md` → `voc-avatar-marketplace/plugins/voc-avatar-partner/commands/voc-operator-dashboard.md`

**Interfaces:**
- Consumes: 없음(독립적으로 이동 가능 — Task 2와 파일을 공유하지 않음)

- [ ] **Step 1: scripts/ 전체를 하나의 git mv로 이동**

```bash
git mv scripts voc-avatar-marketplace/plugins/voc-avatar-partner/scripts
```

`git mv`로 디렉터리를 통째로 옮기면 그 안의 `__pycache__/`(`.gitignore`로 추적
제외된 캐시)까지 실제 OS 레벨 rename으로 함께 이동하고 원래 디렉터리는 완전히
사라진다(실측 확인됨 — 별도 정리 불필요).

- [ ] **Step 2: 이동 확인**

Run: `ls scripts/ 2>&1`
Expected: `No such file or directory` (디렉터리 자체가 통째로 옮겨져 없어짐)

- [ ] **Step 3: 커맨드 디렉터리 생성 + 이동**

```bash
mkdir -p voc-avatar-marketplace/plugins/voc-avatar-partner/commands
git mv .claude/commands/voc-operator-dashboard.md voc-avatar-marketplace/plugins/voc-avatar-partner/commands/voc-operator-dashboard.md
rmdir .claude/commands 2>&1 || true
```

- [ ] **Step 4: 슬래시 커맨드 내용을 `${CLAUDE_PLUGIN_ROOT}` 기준으로 재작성**

`voc-avatar-marketplace/plugins/voc-avatar-partner/commands/voc-operator-dashboard.md`
전체를 아래 내용으로 교체한다(기존 안내 로직은 동일, 경로 참조만 변경):

```markdown
---
description: VoC Operator 이력(~/.voc-hub/operator-decisions.jsonl) 대시보드를 로컬에 띄운다
---

`${CLAUDE_PLUGIN_ROOT}/scripts/voc_operator_dashboard.py`를 백그라운드로 실행해
VoC Operator 이력 대시보드를 띄운다.

1. Bash로 다음을 백그라운드 실행한다(`run_in_background: true`):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/voc_operator_dashboard.py"
   ```
2. 몇 초 뒤 해당 백그라운드 프로세스의 출력을 확인한다.
   - `VoC Operator 대시보드: http://localhost:8765 ...` 가 보이면 그 URL을
     사용자에게 그대로 알려준다.
   - `포트 8765가 이미 사용 중입니다 ...` 가 보이면(대상 파일: `~/.voc-hub/operator-decisions.jsonl`
     읽기 전용 안내), 새로 띄우려 하지 말고 이미 다른 인스턴스가 떠 있을 수
     있다는 그 안내를 그대로 전달한다 — `http://localhost:8765` 를 열어보라고
     안내한다.
3. 대상 파일은 `~/.voc-hub/operator-decisions.jsonl`이 기본값이다 — 이
   커맨드는 인자를 받지 않으며 항상 기본 경로를 그대로 쓴다.
4. 사용자가 "종료해줘"라고 하면 해당 백그라운드 프로세스를 정리한다(상시
   구동 데몬이 아니다).
```

- [ ] **Step 5: 이동된 위치에서 테스트 스위트 재확인**

`cd`로 디렉터리를 옮기는 대신(작업 환경에 따라 격리 검증이 걸릴 수 있는 복합
명령을 피하기 위해) `unittest discover`로 경로만 지정해서 실행한다:

Run:
```bash
python3 -m unittest discover -s voc-avatar-marketplace/plugins/voc-avatar-partner -p "test_voc_operator_dashboard.py" -v
```
Expected: `Ran 35 tests in ...s` / `OK` — 테스트 파일의
`sys.path.insert(0, str(Path(__file__).resolve().parents[1]))`가 `__file__` 기준
상대 경로라 어느 위치에서 실행하든, 어느 방식으로 임포트되든 이동 후에도 그대로
유효하다.

- [ ] **Step 6: 플러그인 매니페스트 재검증(commands/ 인식 확인)**

Run: `claude plugin validate ./voc-avatar-marketplace/plugins/voc-avatar-partner`
Expected: `✔ Validation passed`

- [ ] **Step 7: 커밋**

```bash
git add -A scripts .claude/commands voc-avatar-marketplace/plugins/voc-avatar-partner/scripts voc-avatar-marketplace/plugins/voc-avatar-partner/commands
git commit -m "feat(voc-avatar-partner): move dashboard script and slash command into plugin package

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: 마켓플레이스 등록 + 플러그인 설치 + 기존 수동 배포 정리

**Files:** (코드 변경 없음 — CLI 등록·설치·정리만)

**Interfaces:**
- Consumes: Task 1-3에서 완성된 `voc-avatar-marketplace/` 전체

- [ ] **Step 1: 마켓플레이스 등록**

```bash
claude plugin marketplace add ./voc-avatar-marketplace
```
Expected: `✔ Successfully added marketplace: voc-avatar-marketplace`

- [ ] **Step 2: 플러그인을 project 스코프로 설치**

```bash
claude plugin install voc-avatar-partner@voc-avatar-marketplace --scope project -y
```
Expected: `✔ Successfully installed plugin: voc-avatar-partner@voc-avatar-marketplace (scope: project)`

- [ ] **Step 3: 설치 확인**

Run: `claude plugin list 2>&1 | grep -A3 "voc-avatar-partner"`
Expected: `Scope: project`, `Status: ✔ enabled`

- [ ] **Step 4: 기존 유저 스코프 수동 복사본 정리(방어적 — 없어도 에러 아님)**

```bash
rm -rf ~/.claude/agents/agent-factory
```
Expected: 있으면 삭제, 없으면 조용히 종료(에러 아님). 이 저장소를 다른 환경에
재현할 때도 안전하도록 존재 여부와 무관하게 실행한다.

- [ ] **Step 5: 최종 레포 상태 확인**

Run: `git status`
Expected: `nothing to commit, working tree clean` (이전부터 있던 무관한 untracked
zip 파일 2개는 예외)

이 태스크는 CLI 상태 변경만 하고 레포에 커밋할 파일 변경이 없으므로 별도 커밋이
없다.

---

### Task 5: 종단 검증 (컨트롤러 직접 수행, subagent 없음)

**Files:** (변경 없음 — 검증만)

**Interfaces:**
- Consumes: Task 4에서 설치된 `voc-avatar-partner@voc-avatar-marketplace`

- [ ] **Step 1: 슬래시 커맨드로 대시보드 기동 확인**

`/voc-operator-dashboard`를 실행한다.

Expected: `http://localhost:8765`가 안내되고, `curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/`가 200을 반환한다.
(이미 다른 인스턴스가 떠 있다면 "이미 실행 중" 안내가 정상 — 새 대시보드를
띄우지 않고 기존 URL을 그대로 안내하면 통과.)

- [ ] **Step 2: 3개 agent 개별 호출 확인**

대화창에서 `@voc-avatar-monitor`, `@voc-avatar-operator`, `@voc-avatar-resolver`를
각각 한 번씩 멘션해 정상적으로 응답(각 역할 설명에 맞는 반응)하는지 확인한다.
플러그인 설치본이 실제로 로드되고 있다는 증거로, 각 응답 안에서
`${CLAUDE_PLUGIN_ROOT}/README.md` 참조가 실제 파일을 가리켜 읽히는지(예: 운영자가
설계 배경을 물었을 때 README 내용을 인용할 수 있는지) 간접 확인한다.

- [ ] **Step 3: 최종 정리 확인**

Run: `ls agents/ .claude/commands/ scripts/ README.md 2>&1`
Expected: 전부 `No such file or directory`(레포 루트에 흔적이 남지 않음).

Run: `find voc-avatar-marketplace -type f | sort`
Expected:
```
voc-avatar-marketplace/.claude-plugin/marketplace.json
voc-avatar-marketplace/plugins/voc-avatar-partner/.claude-plugin/plugin.json
voc-avatar-marketplace/plugins/voc-avatar-partner/README.md
voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-monitor.md
voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-operator.md
voc-avatar-marketplace/plugins/voc-avatar-partner/agents/voc-avatar-resolver.md
voc-avatar-marketplace/plugins/voc-avatar-partner/commands/voc-operator-dashboard.md
voc-avatar-marketplace/plugins/voc-avatar-partner/scripts/__init__.py
voc-avatar-marketplace/plugins/voc-avatar-partner/scripts/tests/__init__.py
voc-avatar-marketplace/plugins/voc-avatar-partner/scripts/tests/test_voc_operator_dashboard.py
voc-avatar-marketplace/plugins/voc-avatar-partner/scripts/voc_operator_dashboard.py
```
