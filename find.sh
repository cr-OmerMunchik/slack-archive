#!/usr/bin/env bash
# Search public channels by name so you can add them to channels.txt (macOS/Linux).
# Examples:
#   ./find.sh --enterprise incident
#   ./find.sh release
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "Virtual env not found. Run ./setup.sh first."; exit 1; }
export PYTHONPATH="$ROOT"
exec "$PY" -m slackarchive find-channels "$@"
