#!/usr/bin/env bash
# Export every VoC visible to an X-API-Key into one JSON file.
#
# Uses the cursor (sync) mode of GET /api/integrations/v1/vocs: the first page
# pins a sync_watermark, so records edited mid-export are neither duplicated nor
# skipped. The output is written to a temp file and moved into place only after
# the last page succeeds — a failed run never clobbers an earlier export.
#
# Prints a summary only. Record bodies (customer names, emails, messages,
# internal memos) and the API key are never printed.
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
usage: export_vocs.sh [options]

  --out PATH                 output file (default: ~/voc-hub-exports/vocs-<UTC>.json)
  --limit N                  page size, 1-100 (default 100)
  --status S                 registered|pending|reviewing|resolved|closed|jira_failed
  --service-name NAME
  --issue-owner-email EMAIL
  --updated-after ISO8601    incremental: only records updated at/after this instant
                             (pass the sync_watermark of a previous export)
  --allow-in-repo            permit writing inside a git working tree

env / ~/.voc-hub.env: VOC_INTEGRATION_BASE_URL, VOC_INTEGRATION_API_KEY
EOF
}

die() { echo "error: $*" >&2; exit 1; }

out="" limit=100 allow_in_repo=0
filters=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="${2:?--out needs a value}"; shift 2 ;;
    --limit) limit="${2:?--limit needs a value}"; shift 2 ;;
    --status) filters+=(--data-urlencode "status=${2:?}"); shift 2 ;;
    --service-name) filters+=(--data-urlencode "service_name=${2:?}"); shift 2 ;;
    --issue-owner-email) filters+=(--data-urlencode "issue_owner_email=${2:?}"); shift 2 ;;
    --updated-after) filters+=(--data-urlencode "updated_after=${2:?}"); shift 2 ;;
    --allow-in-repo) allow_in_repo=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

command -v curl >/dev/null || die "curl not found"
command -v jq >/dev/null || die "jq not found"
case "$limit" in ''|*[!0-9]*) die "--limit must be 1-100" ;; esac
if [ "$limit" -lt 1 ] || [ "$limit" -gt 100 ]; then die "--limit must be 1-100"; fi

# Read the key file as values only — never source it (a malformed line would be
# executed as a command and echo the key into the log).
if [ -f ~/.voc-hub.env ]; then
  : "${VOC_INTEGRATION_BASE_URL:=$(sed -n 's/^VOC_INTEGRATION_BASE_URL=//p' ~/.voc-hub.env)}"
  : "${VOC_INTEGRATION_API_KEY:=$(sed -n 's/^VOC_INTEGRATION_API_KEY=//p' ~/.voc-hub.env)}"
fi
[ -n "${VOC_INTEGRATION_BASE_URL:-}" ] || die "VOC_INTEGRATION_BASE_URL is not set (env or ~/.voc-hub.env)"
echo "instance: $VOC_INTEGRATION_BASE_URL"   # before the key guard, so it shows even without a key
[ -n "${VOC_INTEGRATION_API_KEY:-}" ] || die "VOC_INTEGRATION_API_KEY is not set (env or ~/.voc-hub.env)"
base="${VOC_INTEGRATION_BASE_URL%/}/api/integrations/v1/vocs"

if [ -z "$out" ]; then
  out="$HOME/voc-hub-exports/vocs-$(date -u +%Y%m%dT%H%M%SZ).json"
fi
out_dir=$(dirname -- "$out")
mkdir -p -- "$out_dir"
if [ "$allow_in_repo" -eq 0 ] && git -C "$out_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  die "$out_dir is inside a git working tree — exports contain customer data; choose another --out or pass --allow-in-repo"
fi

# Temp dir next to the output so the final mv is a same-filesystem rename.
work=$(mktemp -d -- "$out_dir/.voc-export.XXXXXX")
trap 'rm -rf -- "$work"' EXIT

# Fetch one page into $work/page.json; fail with the server's error envelope code.
fetch() {
  local status
  status=$(curl -sS -G "$base" -H "X-API-Key: $VOC_INTEGRATION_API_KEY" \
    -o "$work/page.json" -w '%{http_code}' "$@") || die "request failed (network)"
  if [ "$status" != 200 ]; then
    local detail
    detail=$(jq -r '"\(.error.code // "unknown"): \(.error.message // "")"' "$work/page.json" 2>/dev/null || echo "non-JSON response")
    die "HTTP $status $detail"
  fi
}

# First page carries limit + filters; later pages must send cursor alone
# (the server rejects cursor combined with any other parameter).
fetch --data-urlencode "limit=$limit" ${filters[@]+"${filters[@]}"}
watermark=$(jq -r '.sync_watermark' "$work/page.json")
pages=0
while :; do
  pages=$((pages + 1))
  jq -c '.items[]' "$work/page.json" >> "$work/items.jsonl"
  [ "$(jq -r '.has_more' "$work/page.json")" = true ] || break
  cursor=$(jq -r '.next_cursor // empty' "$work/page.json")
  [ -n "$cursor" ] || die "has_more=true but next_cursor is empty"
  fetch --data-urlencode "cursor=$cursor"
done
touch "$work/items.jsonl"

jq -s \
  --arg base_url "$VOC_INTEGRATION_BASE_URL" \
  --arg exported_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg sync_watermark "$watermark" \
  '{exported_at: $exported_at, base_url: $base_url, sync_watermark: $sync_watermark,
    count: length, items: .}' \
  "$work/items.jsonl" > "$work/out.json"
mv -f -- "$work/out.json" "$out"

echo "count: $(jq '.count' "$out")"
echo "pages: $pages"
echo "sync_watermark: $watermark"
echo "output: $out"
