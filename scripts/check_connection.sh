#!/usr/bin/env bash
set -euo pipefail

CONFIG=${ONSITE_CONFIG:-/etc/onsitelogistics/config.json}
DRY_RUN=false

usage(){
  cat <<EOS
Usage: $0 [--config PATH] [--dry-run]
  --config PATH   Use specific config file (default: /etc/onsitelogistics/config.json or ONSITE_CONFIG)
  --dry-run       Show API URL / token presence and exit without sending HTTP request
EOS
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

TMP=$(mktemp)
cleanup(){ rm -f "$TMP"; }
trap cleanup EXIT

if [[ ! -f "$CONFIG" ]]; then
  echo "Config not found: $CONFIG" >&2
  exit 1
fi

python3 - "$CONFIG" <<'PY' > "$TMP"
import json, sys
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as fh:
    data = json.load(fh)
print(data.get('api_url') or '')
print(data.get('api_token') or '')
PY

API_URL=$(sed -n '1p' "$TMP")
API_TOKEN=$(sed -n '2p' "$TMP")

echo "Config: $CONFIG"
echo "API URL: ${API_URL:-<not set>}"
if [[ -n "$API_TOKEN" ]]; then
  echo "API Token: <provided>"
else
  echo "API Token: <empty>"
fi

if [[ -z "$API_URL" ]]; then
  echo "api_url not set in $CONFIG" >&2
  exit 1
fi

if [[ "$DRY_RUN" = true ]]; then
  echo "Dry run: skipping HTTP request"
  exit 0
fi

PAYLOAD=$(cat <<JSON
{"part_code":"PING","location_code":"CHECK","scanned_at":"$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
JSON
)

AUTH_ARGS=()
if [[ -n "$API_TOKEN" ]]; then
  AUTH_ARGS+=("-H" "Authorization: Bearer ${API_TOKEN}")
fi

set +e
OUTPUT=$(curl -s -o /dev/null -w '%{http_code}' "${AUTH_ARGS[@]}" -H 'Content-Type: application/json' -d "$PAYLOAD" "$API_URL")
STATUS=$?
set -e

if [[ $STATUS -ne 0 ]]; then
  echo "Curl failed with status $STATUS" >&2
  exit 1
fi

echo "HTTP status: $OUTPUT"
if [[ "$OUTPUT" = "200" || "$OUTPUT" = "201" ]]; then
  echo "Connection OK"
else
  echo "Warning: unexpected HTTP status"
fi
