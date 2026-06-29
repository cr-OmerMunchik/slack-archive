#!/usr/bin/env bash
# Build the search index (if needed) and open the local search UI (macOS / Linux).
# Examples:
#   ./search.sh                  # index if needed, then open browser
#   ./search.sh --reindex
#   ./search.sh --port 9000 --no-browser
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "Virtual env not found. Run ./setup.sh first."; exit 1; }
export PYTHONPATH="$ROOT"

REINDEX=0; SERVE_ARGS=()
for a in "$@"; do
  case "$a" in
    --reindex) REINDEX=1 ;;
    *) SERVE_ARGS+=("$a") ;;
  esac
done

if [ "$REINDEX" = "1" ] || [ ! -f "$ROOT/data/search.db" ]; then
  "$PY" -m slackarchive index
fi
exec "$PY" -m slackarchive serve "${SERVE_ARGS[@]}"
