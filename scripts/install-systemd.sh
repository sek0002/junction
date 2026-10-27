#!/usr/bin/env bash
# Run from the checkout at /opt/junction: sudo bash scripts/install-systemd.sh
set -euo pipefail
if [[ $(id -u) != 0 ]]; then
  echo 'Run with sudo.' >&2
  exit 1
fi
if [[ $(uname -s) != Linux ]] || ! command -v systemctl >/dev/null; then
  echo 'A Linux server with systemd is required.' >&2
  exit 1
fi
junction_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$junction_dir" != /opt/junction ]]; then
  echo 'Clone the repository to /opt/junction before installing this service.' >&2
  exit 1
fi
junction_python=$(bash "$junction_dir/scripts/select-python.sh")
printf 'Using Python: %s\n' "$junction_python"
if [[ -x "$junction_dir/.venv/bin/python" ]] && ! "$junction_dir/.venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo 'The existing /opt/junction/.venv uses an older Python. Move that directory aside, then rerun this installer.' >&2
  exit 1
fi
if ! id junction >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/junction --no-create-home --shell /usr/sbin/nologin junction
fi
install -d -m 0700 -o junction -g junction /var/lib/junction
install -d -m 0755 /etc/junction
if [[ ! -x "$junction_dir/.venv/bin/python" ]]; then
  "$junction_python" -m venv "$junction_dir/.venv"
fi
"$junction_dir/.venv/bin/python" -m pip install -r "$junction_dir/requirements.txt"
"$junction_dir/.venv/bin/python" "$junction_dir/scripts/configure_service.py" "$@"
install -m 0644 "$junction_dir/deploy/junction.service" /etc/systemd/system/junction.service
systemctl daemon-reload
systemctl enable --now junction.service
printf '\nJunction is installed. Settings:\n'
cat /etc/junction/junction.env
printf '\nStatus: sudo systemctl status junction\nLogs: sudo journalctl -u junction -f\n'
