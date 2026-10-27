#!/usr/bin/env bash
# Print a Python 3.10+ executable; an explicit choice must pass validation.
set -euo pipefail
if [[ -n ${JUNCTION_PYTHON:-} ]]; then
  candidates=("$JUNCTION_PYTHON")
else
  candidates=(python3 python3.14 python3.13 python3.12 python3.11 python3.10)
fi
for candidate in "${candidates[@]}"; do
  executable=$(command -v "$candidate" 2>/dev/null) || continue
  if "$executable" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    printf '%s\n' "$executable"
    exit 0
  fi
done
printf '%s\n' 'Python 3.10+ is required. No compatible interpreter was found.' \
  'Install Python 3.10+ and its matching venv package, then retry, for example:' \
  '  sudo env JUNCTION_PYTHON=/usr/bin/python3.11 bash scripts/install-systemd.sh' \
  'Check your Linux release with: cat /etc/os-release' >&2
exit 1
