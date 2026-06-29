#!/usr/bin/env bash
# Back up your Slack history (macOS / Linux).
# Examples:
#   ./backup.sh --enterprise --pick               # interactively choose channels (asks about attachments)
#   ./backup.sh --enterprise                       # everything you're in
#   ./backup.sh --enterprise --no-files            # text only - skip attachments (much smaller)
#   ./backup.sh --enterprise --fresh               # start a new archive instead of resuming
#   ./backup.sh --dry-run
# Backups are resumable + incremental: re-running continues an existing archive in data/archive.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "Virtual env not found. Run ./setup.sh first."; exit 1; }
export PYTHONPATH="$ROOT"
exec "$PY" -m slackarchive backup "$@"
