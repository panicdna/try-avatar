# CLAUDE.md

이 레포는 동료들과 공유하는 Claude Code 플러그인 마켓플레이스다. 기본은
**집계형(aggregator)**: 각 플러그인의 `source`가 원작자 자신의 GHE 레포(`jemings/<name>`)를
가리키는 `{"source":"url", "url":"...", "ref":"main"}` 형태이며, 스킬 본문·스크립트는
이 레포에 두지 않고 각자 자기 레포에서 그대로 독립적으로 유지보수된다.

예외적으로 원본 저장소를 폐기하고 이 레포로 **하드카피**된 플러그인은
`plugins/<name>/`(로컬 경로 `source`)에 파일을 직접 담아 **이 레포에서만** 유지보수한다
(예: `avatar-onboarding`). 새로 추가할 플러그인이 이 방식인지 집계형인지는 요청자가
명시한다 — 기본값은 집계형이다.

## 집계형 플러그인: 본문 수정은 이 레포에서 일어나지 않는다

`plugin.json`의 `version`을 올리거나 `SKILL.md`를 고치는 일은 전부 각 스킬의 **자기
레포**에서 처리한다. `ref: "main"`만 지정하고 `sha`를 고정하지 않았으므로, 원본
레포에 push되는 즉시 이 마켓플레이스가 가리키는 대상도 최신이 된다 — 여기서 버전을
맞춰 올리거나 파일을 다시 복사해 넣을 필요가 없다.

주의: 이는 "새 버전이 즉시 자동으로 이미 설치된 사용자에게 도달함"을 뜻하지
않는다. 이미 설치한 쪽은 `/plugin marketplace update skill` → `/plugin update
<name>@skill`을 실행해야 실제로 새 커밋을 받는다(신규 설치는 항상 최신을 받음).

## 하드카피 플러그인을 수정하면 plugin.json의 version을 반드시 올린다

`plugins/<name>/`에 직접 담긴 플러그인(예: `avatar-onboarding`)은 이 레포 안의
`plugins/<name>/.claude-plugin/plugin.json`의 `version`만 보고 갱신 여부가 판단된다.
버전이 그대로면 파일이 바뀌었어도 이미 설치한 사용자에게 전달되지 않는다. 따라서
`plugins/<name>/` 아래 파일(스크립트·`SKILL.md`·참조 문서 포함)을 고쳤다면 **같은
커밋/PR 안에서** 그 플러그인의 `version`을 올린다 — semver 기준은 동작 변경 없는
정리는 patch, 기능 추가나 사용자에게 보이는 변경은 minor.

## 하드카피 스킬 파일은 AF 보안 스캔 규칙 두 개를 미리 지켜서 쓴다

Agent Factory(AF)는 등록된 스킬을 보안 스캔하고, finding이 남으면 `is_safe: false`가
되어 손으로 고치는 PR을 다시 올려야 한다. 아래 두 규칙은 이미 두 번 반복됐다
(`bedrock-cost-report` a87c633, `avatar-onboarding` 이번 건). 처음부터 지키면 비용이 0이니
`plugins/<name>/skills/` 아래 파일을 만들거나 고칠 때 함께 확인한다.

### 1. `SKILL.md` frontmatter에 `license`를 반드시 넣는다

없으면 `MANIFEST_MISSING_LICENSE`(INFO, `policy_violation`)가 뜬다. 스캐너는 `SKILL.md`
frontmatter의 **최상위 `license` 키 하나만** 본다(skill-scanner 2.0.11
`core/analyzers/static.py:469`의 `if not manifest.license:`). 아래는 전부 이 finding을
지우지 못한다 - 실제로 헷갈려서 놓친 부분이다:

- `.claude-plugin/plugin.json`의 `"license"`: 스캐너는 `plugin.json`을 아예 읽지 않는다.
  이번에 걸린 세 플러그인 모두 `plugin.json`에는 `Apache-2.0`이 있었는데도 flag됐다.
- 레포 루트의 `LICENSE` 파일: 규칙 설명문이 "missing a license **file**"이라 오해하기
  쉽지만, 구현은 파일을 찾지 않는다.
- `metadata:` 아래에 중첩된 `license`, 값이 빈 `license:`(YAML `None`은 falsy).

값 형식 검증은 없지만 `plugin.json`의 `license`와 같은 값으로 맞춘다:

```yaml
---
name: <name>
description: ...
license: Apache-2.0
---
```

### 2. 장식용 non-ASCII 문장부호를 쓰지 않는다 (한국어 본문은 그대로 둔다)

AF는 스킬 파일의 non-ASCII 문장부호를 `UNICODE_OBFUSCATED_INSTRUCTION`(**HIGH**,
`prompt_injection`)으로 잡는다. em dash 하나만 있어도 걸리고, HIGH라서 `is_safe`가 바로
false가 된다. 편집기·LLM이 자동으로 넣는 활자체 문장부호가 주범이니 다음으로 치환한다.
치환 결과는 `bedrock-cost-report`(a87c633)에서 이미 쓰인 표기를 따른다:

| 쓰지 말 것 | 대신 | 비고 |
|---|---|---|
| `—` (em dash) | ` -- ` | 이 레포 관행. 앞뒤 공백 포함 |
| `–` (en dash) | `-` | 범위 표기(`steps 2-4`) |
| `…` | `...` | |
| `→` | `->` | |
| `’ ‘ “ ”` (곡선 인용부호) | `' "` | |
| `✔ ✘ ⏸ ·` 같은 장식 기호 | 뜻을 말로 풀어 쓴다 | 1:1 ASCII 대응이 없다 |

em dash를 한 칸 하이픈(` - `)으로 바꾸지 말고 ` -- `로 바꾼다. 이 문서들은 `entry-point`,
`least-global`처럼 하이픈 복합어가 많아서, 한 칸 하이픈은 복합어 하이픈·목록 불릿과
구분되지 않고 짝을 이룬 삽입구의 경계도 사라진다. `bedrock-cost-report` SKILL.md도
문장 안 ` -- ` 49곳 대 ` - ` 4곳으로 같은 선택을 했다.

두 가지를 특히 주의한다:

- **finding은 파일당 첫 non-ASCII 위치 하나만 보고된 것으로 보인다.** `avatar-onboarding`
  SKILL.md는 em dash가 33개였는데 리포트에는 line 8(파일의 첫 non-ASCII, index 487) 하나만
  찍혔다. 키워드 밀도·줄 길이 가설은 검증해서 기각했지만 규칙 원문을 볼 수 없으니 추정이다.
  어느 쪽이든 지목된 줄만 고치면 다음 스캔에서 다음 줄로 옮겨갈 수 있으니 **파일 전체를**
  치환한다.
- **한국어 본문은 지우지 않는다.** 예시 문자열이나 설명에 필요한 한글은 그대로 둔다
  (`avatar-onboarding` SKILL.md의 `"완료"`). 근거: a87c633이 이 finding을 해소한
  `bedrock-cost-report`에는 지금도 한글이 수천 자 남아 있고(`driver.py`의 `다` 한 자만
  272회) 한국어 아닌 non-ASCII는 0자다. 즉 정리 대상은 장식용 문장부호·기호뿐이다.

### PR 전에 로컬에서 확인한다

```bash
uv tool install cisco-ai-skill-scanner            # 최초 1회
skill-scanner scan plugins/<name>/skills/<name> --format json
```

규칙 1(`MANIFEST_MISSING_LICENSE`)은 이 명령으로 재현·검증된다. 반면 규칙 2는
**skill-scanner에 없는 AF 전용 규칙**이라 로컬 스캔이 깨끗해도 증거가 되지 않는다
(2.0.11 전체에서 해당 rule_id는 물론 `decoded_preview`·`encodings` 문자열조차 0건).
그래서 규칙 2는 스캔이 아니라 아래 grep으로 직접 확인한다 - AF가 스캔하는 경로가
`skills/<name>/`이므로 그 아래만 보면 된다:

```bash
# 한글을 뺀 non-ASCII가 남았는지. 매치된 '문자'만 보고 걸러내므로 한글과 em dash가
# 같은 줄에 섞여 있어도 놓치지 않는다. 아무것도 안 나와야(exit 1) 통과.
grep -roP '[^\x00-\x7F]' plugins/<name>/skills/ |
  grep -Pv ':[\x{1100}-\x{11FF}\x{3130}-\x{318F}\x{AC00}-\x{D7A3}]$'
```

주의: 위 두 규칙은 **앞으로 만들거나 고치는 파일**에 적용하는 기준이고, 기존 하드카피
플러그인이 이미 전부 통과하는 상태는 아니다. 2026-09 기준 규칙 2 미적용:
`agent-factory-api`(32자), `avatar-distill`(87자), `avatar-load`(30자),
`claude-delegation`(36자). 해당 플러그인을 만질 일이 생기면 그 PR에서 같이 정리한다.

`skill-cure` 스킬에 이 두 finding의 상세 대응 문서가 있으니 실제로 리포트를 받았을 때는
그쪽을 따른다.

## 새 스킬을 집계형으로 추가할 때

1. 새 스킬이 아직 자기 GHE 레포에서 단일-플러그인 마켓플레이스로 패키징돼 있지
   않다면 먼저 `plugin-packager` 스킬로 패키징한다(`.claude-plugin/plugin.json` +
   `skills/<name>/SKILL.md` 구조, `author` 필수).
2. 이 레포의 `.claude-plugin/marketplace.json` `plugins` 배열에 항목 하나만 추가:
   ```json
   {
     "name": "<name>",
     "description": "<원본 repo plugin.json의 description 그대로>",
     "category": "<development|productivity|security 등>",
     "source": {
       "source": "url",
       "url": "https://github.samsungds.net/jemings/<name>.git",
       "ref": "main"
     }
   }
   ```
3. `README.md` 표에도 한 줄 추가(유지보수 칸에 원본 레포 링크 + "(외부)").
4. `claude plugin validate . --strict`로 정적 검증 후, 로컬 경로로
   `claude plugin marketplace add`→ 표본 설치 → `claude plugin details`까지 확인하고
   나서(plugin-packager 스킬의 검증 규율과 동일), 검증에 쓴 user-scope 마켓플레이스/설치는
   반드시 정리(`uninstall`/`marketplace remove`)한 뒤 push한다.

## 새 스킬을 하드카피로 추가할 때

원본 저장소를 폐기하고 이 레포에서만 유지보수하기로 한 경우:

1. `plugins/<name>/.claude-plugin/plugin.json` + `plugins/<name>/skills/<name>/SKILL.md`
   구조로 파일을 그대로 옮긴다(스킬 본문 내용 변경 금지, 위치만 이동).
2. `marketplace.json`에 `"source": "./plugins/<name>"`(로컬 경로) 항목 추가.
3. `README.md` 표의 유지보수 칸에 "`plugins/<name>/`(이 레포에서 직접)"으로 표시.
4. 위 "AF 보안 스캔 규칙" 절의 두 규칙(`license` frontmatter, ASCII 문장부호)을 옮겨온
   파일에 적용하고 같은 절의 grep 게이트로 확인한다. 하드카피는 이 레포가 스캔 대상이 되므로
   원본 레포에서 통과했는지와 무관하게 여기서 다시 확인해야 한다.
5. 위와 동일하게 validate + 표본 설치 검증 후 정리.

## 스킬 이름 변경·제거·이관

원본 레포 이름이 바뀌거나 스킬이 폐기될 때만 이 레포의 `marketplace.json`을
수정한다(플러그인 엔트리 이름·`source` 갱신 또는 삭제). 집계형 스킬을 하드카피로
전환하는 경우(원본 저장소 폐기) `source`를 외부 url에서 로컬 경로로 바꾸고 파일을
`plugins/<name>/`로 옮긴다 — 이후로는 "하드카피 플러그인" 규칙(버전 올리기)을 따른다.
