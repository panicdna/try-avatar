# 보관됨 — 구버전 스냅샷

이 폴더의 파일들은 **2026-08-27 3-Role 재설계 이전** 시점의 기록입니다.
최신 설계는 프로젝트 루트의 [`../README.md`](../README.md)를 보세요.

| 파일 | 왜 구버전인가 |
|---|---|
| `voc-autoresolve-avatar-registration.md` | 재설계 전 단일 흐름(자동 해결/수동 트리아지/이력 리포트) 구조를 기록한 문서. Role 이름·Task 내용이 지금 서버 상태와 다름. |
| `voc-autoresolve-avatar-export.zip` / `voc-autoresolve-avatar-export/` | 같은 시점의 Card/Role/Task JSON 스냅샷 + 재생성 스크립트. `reimport.sh`로 이걸 재생성하면 **구버전 설계**가 만들어지므로, 최신 서버 상태를 재현하려면 먼저 서버에서 다시 fresh export해야 한다. |

지우지 않고 남겨둔 이유: 설계가 어떻게 바뀌어왔는지 추적하고, `reimport.sh`의
구조(Task→Role→Card 순서, skill_id 검증 로직)는 여전히 참고할 가치가 있어서다.
