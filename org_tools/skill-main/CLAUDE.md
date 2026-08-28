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
4. 위와 동일하게 validate + 표본 설치 검증 후 정리.

## 스킬 이름 변경·제거·이관

원본 레포 이름이 바뀌거나 스킬이 폐기될 때만 이 레포의 `marketplace.json`을
수정한다(플러그인 엔트리 이름·`source` 갱신 또는 삭제). 집계형 스킬을 하드카피로
전환하는 경우(원본 저장소 폐기) `source`를 외부 url에서 로컬 경로로 바꾸고 파일을
`plugins/<name>/`로 옮긴다 — 이후로는 "하드카피 플러그인" 규칙(버전 올리기)을 따른다.
