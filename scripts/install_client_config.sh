#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

DEFAULT_SAMPLE="${REPO_ROOT}/config/config.sample.json"
DEFAULT_TARGET="/etc/onsitelogistics/config.json"

API_URL=""
API_TOKEN=""
DEVICE_ID=""
TARGET="${DEFAULT_TARGET}"
SAMPLE="${DEFAULT_SAMPLE}"
FORCE=false

usage() {
  cat <<EOF
Usage: sudo ./scripts/install_client_config.sh [options]

Options:
  --target PATH        Destination config file (default: ${DEFAULT_TARGET})
  --sample PATH        Sample JSON file to copy (default: ${DEFAULT_SAMPLE})
  --api-url URL        Override api_url in the generated config
  --api-token TOKEN    Override api_token in the generated config
  --device-id ID       Override device_id in the generated config
  --force              Overwrite target without backup
  --help               Show this help message
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      [[ $# -lt 2 ]] && usage
      TARGET="$2"
      shift 2
      ;;
    --sample)
      [[ $# -lt 2 ]] && usage
      SAMPLE="$2"
      shift 2
      ;;
    --api-url)
      [[ $# -lt 2 ]] && usage
      API_URL="$2"
      shift 2
      ;;
    --api-token)
      [[ $# -lt 2 ]] && usage
      API_TOKEN="$2"
      shift 2
      ;;
    --device-id)
      [[ $# -lt 2 ]] && usage
      DEVICE_ID="$2"
      shift 2
      ;;
    --force)
      FORCE=true
      shift
      ;;
    --help|-h)
      usage
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      ;;
  esac
done

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "This script must be run as root (use sudo)." >&2
  exit 1
fi

if [[ ! -f "${SAMPLE}" ]]; then
  echo "Sample config not found: ${SAMPLE}" >&2
  exit 1
fi

install_dir=$(dirname "${TARGET}")
install -d -o root -g root -m 755 "${install_dir}"

if [[ -f "${TARGET}" && "${FORCE}" != "true" ]]; then
  timestamp=$(date +"%Y%m%d%H%M%S")
  backup="${TARGET}.${timestamp}.bak"
  echo "Backing up existing config to ${backup}"
  install -o root -g root -m 640 "${TARGET}" "${backup}"
fi

python3 <<PY
import json
from pathlib import Path
sample_path = Path("${SAMPLE}")
target_path = Path("${TARGET}")

with sample_path.open("r", encoding="utf-8") as fh:
    data = json.load(fh)

api_url = "${API_URL}".strip()
if api_url:
    data["api_url"] = api_url

api_token = "${API_TOKEN}"
if api_token:
    data["api_token"] = api_token

device_id = "${DEVICE_ID}".strip()
if device_id:
    data["device_id"] = device_id

with target_path.open("w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\\n")
PY

chmod 640 "${TARGET}"
chown root:root "${TARGET}"

cat <<'INFO'
Client configuration installed.

Reminder:
  * Inspect /etc/onsitelogistics/config.json to ensure API URL / token / device ID are correct.
  * Restart the handheld service after updating:
        sudo systemctl restart handheld@<user>.service
INFO
