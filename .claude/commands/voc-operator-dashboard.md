---
description: VoC Operator 이력(~/.voc-hub/operator-decisions.jsonl) 대시보드를 로컬에 띄운다
---

`scripts/voc_operator_dashboard.py`를 백그라운드로 실행해 VoC Operator 이력
대시보드를 띄운다.

1. Bash로 다음을 백그라운드 실행한다(`run_in_background: true`):
   ```bash
   python3 scripts/voc_operator_dashboard.py
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
