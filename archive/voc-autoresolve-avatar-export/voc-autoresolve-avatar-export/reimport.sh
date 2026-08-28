#!/usr/bin/env bash
# VoC 자동 해결 파트너 — 재생성 스크립트
#
# Agent Factory에는 Card/Role/Task용 공식 import API가 없다. 이 스크립트는
# 이 폴더의 task_*.json / role_*.json / card.json 스냅샷을 읽어, 같은 구조를
# "새 ID로" 다시 만든다 (원본 ID는 재사용되지 않는다 — 서버가 생성 시점에
# ID를 새로 발급한다).
#
# 실행 전 준비:
#   export AGENT_FACTORY_API_KEY=<aft_... 키>
#   export BASE="http://127.0.0.1:9090/api/v1/agent"   # 대상 서버로 바꿔도 됨
#
# 이 폴더에 이미 같은 이름의 Card/Role/Task가 있는지는 확인하지 않는다 —
# 재실행하면 중복 생성된다. 재사용하려면 avatar-onboarding 스킬의 "기존
# Card/Role/Task 검색" 절차를 먼저 따르는 걸 권장한다.
set -euo pipefail
: "${AGENT_FACTORY_API_KEY:?AGENT_FACTORY_API_KEY 환경변수가 필요합니다}"
BASE="${BASE:-http://127.0.0.1:9090/api/v1/agent}"
AUTH="Authorization: Bearer $AGENT_FACTORY_API_KEY"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail() { echo "STOP: $1" >&2; exit 1; }

echo "== Skill 확인 (Task가 참조하는 skill_id가 대상 서버에도 존재해야 함) =="
for sid in $(jq -r '[.. | .skill_id? // empty] | unique | .[]' "$DIR"/task_*.json 2>/dev/null | sort -u); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' -H "$AUTH" "$BASE/skills/$sid")
  if [ "$code" != "200" ]; then
    echo "경고: skill_id=$sid 가 대상 서버에 없음 (HTTP $code)."
    echo "  -> $DIR/skill_voc_hub_skills.json 을 참고해 먼저 POST \$BASE/skills 로 재등록하고,"
    echo "     새로 받은 skill_id로 아래 task_*.json 의 skills[].skill_id 를 갱신한 뒤 재실행하세요."
    fail "선행 skill 등록 필요"
  fi
done
echo "OK — 모든 skill_id 확인됨"

echo "== Task 재생성 =="
TASK_MAP="$WORK/task_map.json"; echo '{}' > "$TASK_MAP"
for f in "$DIR"/task_*.json; do
  old_id=$(jq -r '.id' "$f")
  title=$(jq -r '.title' "$f")
  payload=$(jq '{title, context, text, skills: (.skills // [] | map({skill_id, component_key})), manager_emails: (.manager_emails // [])}' "$f")
  resp=$(curl -sS -H "$AUTH" -H "Content-Type: application/json" -d "$payload" "$BASE/avatars/tasks")
  new_id=$(echo "$resp" | jq -r '.id // empty')
  [ -n "$new_id" ] || { echo "$resp" >&2; fail "Task 생성 실패: $title"; }
  echo "Task '$title': $old_id -> $new_id"
  jq --arg o "$old_id" --arg n "$new_id" '.[$o]=$n' "$TASK_MAP" > "$TASK_MAP.tmp" && mv "$TASK_MAP.tmp" "$TASK_MAP"
done

echo "== Role 재생성 =="
ROLE_MAP="$WORK/role_map.json"; echo '{}' > "$ROLE_MAP"
for f in "$DIR"/role_*.json; do
  old_id=$(jq -r '.id' "$f")
  title=$(jq -r '.title' "$f")
  new_task_ids=$(jq -r '[.tasks[].avatar_task_id]' "$f" | jq --slurpfile map "$TASK_MAP" '[.[] as $o | $map[0][$o]]')
  payload=$(jq -n --arg title "$(jq -r '.title' "$f")" --arg desc "$(jq -r '.description' "$f")" \
                  --argjson tids "$new_task_ids" \
                  '{title:$title, description:$desc, task_ids:$tids, manager_emails:[]}')
  resp=$(curl -sS -H "$AUTH" -H "Content-Type: application/json" -d "$payload" "$BASE/avatars/roles")
  new_id=$(echo "$resp" | jq -r '.id // empty')
  [ -n "$new_id" ] || { echo "$resp" >&2; fail "Role 생성 실패: $title"; }
  echo "Role '$title': $old_id -> $new_id"
  jq --arg o "$old_id" --arg n "$new_id" '.[$o]=$n' "$ROLE_MAP" > "$ROLE_MAP.tmp" && mv "$ROLE_MAP.tmp" "$ROLE_MAP"
done

echo "== Card 재생성 =="
f="$DIR/card.json"
new_role_ids=$(jq -r '[.roles[].avatar_role_id]' "$f" | jq --slurpfile map "$ROLE_MAP" '[.[] as $o | $map[0][$o]]')
payload=$(jq -n --arg name "$(jq -r '.name' "$f")" --arg resp "$(jq -r '.responsibility' "$f")" \
                --argjson rids "$new_role_ids" \
                '{name:$name, responsibility:$resp, role_ids:$rids, manager_emails:[]}')
resp=$(curl -sS -H "$AUTH" -H "Content-Type: application/json" -d "$payload" "$BASE/avatars/cards")
new_card_id=$(echo "$resp" | jq -r '.id // empty')
[ -n "$new_card_id" ] || { echo "$resp" >&2; fail "Card 생성 실패"; }
echo "Card: $(jq -r '.id' "$f") -> $new_card_id"
echo
echo "완료. 새 Card ID: $new_card_id"
curl -sS -H "$AUTH" "$BASE/avatars/cards/$new_card_id" | jq .
