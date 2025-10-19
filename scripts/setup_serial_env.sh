#!/usr/bin/env bash
#
# Configure Raspberry Pi handheld environment for serial-mode scanners.
# - Adds udev rule to expose /dev/minjcode0 (VID:PID 152a:880f)
# - Installs systemd override to wait for the serial device before starting handheld@ service
#
# Usage:
#   chmod +x scripts/setup_serial_env.sh
#   sudo ./scripts/setup_serial_env.sh denkonzero
#
# The single argument is the Pi user name (e.g. denkonzero). The script must be run with sudo.

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: This script must be run with sudo/root." >&2
  exit 1
fi

if [[ "$#" -ne 1 ]]; then
  echo "Usage: sudo $0 <pi-user>" >&2
  exit 1
fi

PI_USER="$1"
USER_HOME="/home/${PI_USER}"
SERVICE_DIR="/etc/systemd/system/handheld@.service.d"
UDEV_RULE="/etc/udev/rules.d/60-minjcode.rules"

echo ">>> Writing udev rule to ${UDEV_RULE}"
cat <<'EOF' > "${UDEV_RULE}"
SUBSYSTEM=="tty", ATTRS{idVendor}=="152a", ATTRS{idProduct}=="880f", SYMLINK+="minjcode%n", GROUP="dialout", MODE="0660"
EOF

echo ">>> Reloading udev rules"
udevadm control --reload-rules
udevadm trigger --attr-match=idVendor=152a --attr-match=idProduct=880f || true

echo ">>> Creating systemd override in ${SERVICE_DIR}"
mkdir -p "${SERVICE_DIR}"
cat <<'EOF' > "${SERVICE_DIR}/override.conf"
[Unit]
After=dev-ttyACM0.device
Wants=dev-ttyACM0.device

[Service]
ExecStartPre=/bin/sh -c 'for i in $(seq 1 10); do [ -e /dev/minjcode0 ] || [ -e /dev/ttyACM0 ] && exit 0; sleep 1; done; echo "no serial device"; exit 1'
Restart=always
RestartSec=2
EOF

echo ">>> Reloading systemd manager configuration"
systemctl daemon-reload

echo ">>> Restarting handheld@${PI_USER}.service"
systemctl restart "handheld@${PI_USER}.service"

echo ">>> Done. Recent journal output:"
journalctl -u "handheld@${PI_USER}.service" -n 20 --no-pager || true
