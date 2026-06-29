#!/usr/bin/env bash
# Generate an editable channels.txt listing the conversations you're in (macOS/Linux).
# Examples:
#   ./pick.sh --enterprise   # Slack Enterprise Grid
#   ./pick.sh                # standard workspace
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "Virtual env not found. Run ./setup.sh first."; exit 1; }
export PYTHONPATH="$ROOT"
exec "$PY" -m slackarchive pick-channels "$@"
