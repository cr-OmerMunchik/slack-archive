#!/usr/bin/env bash
# Back up your Slack history (macOS / Linux).
# Examples:
#   ./backup.sh                                   # member-only (everything you're in)
#   ./backup.sh --enterprise --workspace acme
#   ./backup.sh --enterprise --channels C0123ABCD # specific public channel(s) + channels.txt
#   ./backup.sh --dry-run
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "Virtual env not found. Run ./setup.sh first."; exit 1; }
export PYTHONPATH="$ROOT"
exec "$PY" -m slackarchive backup "$@"
