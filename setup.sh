#!/usr/bin/env bash
# slack-archive setup (macOS / Linux)
# -----------------------------------
# Downloads the slackdump binary, ensures Python + a virtualenv, installs deps.
#   chmod +x setup.sh && ./setup.sh
set -euo pipefail

SLACKDUMP_VERSION="${SLACKDUMP_VERSION:-v4.4.1}"   # pinned, known-good
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$ROOT/bin"

info() { printf '\033[36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m!!  %s\033[0m\n' "$1"; }

# --- 1. slackdump binary ---------------------------------------------------
os="$(uname -s)"; arch="$(uname -m)"
case "$os" in
  Darwin) os_name="macOS" ;;
  Linux)  os_name="Linux" ;;
  *) echo "Unsupported OS: $os (use the Windows setup.ps1 on Windows)"; exit 1 ;;
esac
case "$arch" in
  x86_64|amd64) arch_name="x86_64" ;;
  arm64|aarch64) arch_name="arm64" ;;
  *) echo "Unsupported architecture: $arch"; exit 1 ;;
esac
asset="slackdump_${os_name}_${arch_name}.tar.gz"
sd="$BIN/slackdump"

if [ -x "$sd" ]; then
  info "slackdump already present ($sd) - skipping download."
else
  mkdir -p "$BIN"
  base="https://github.com/rusq/slackdump/releases/download/$SLACKDUMP_VERSION"
  info "Downloading slackdump $SLACKDUMP_VERSION ($asset) ..."
  curl -fsSL "$base/$asset" -o "$BIN/$asset"
  curl -fsSL "$base/checksums.txt" -o "$BIN/checksums.txt"

  expected="$(grep " $asset\$" "$BIN/checksums.txt" | awk '{print $1}')"
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$BIN/$asset" | awk '{print $1}')"
  else
    actual="$(shasum -a 256 "$BIN/$asset" | awk '{print $1}')"
  fi
  if [ -n "$expected" ] && [ "$expected" != "$actual" ]; then
    echo "Checksum mismatch for $asset"; exit 1
  fi
  info "Checksum OK."
  tar -xzf "$BIN/$asset" -C "$BIN" slackdump 2>/dev/null || tar -xzf "$BIN/$asset" -C "$BIN"
  rm -f "$BIN/$asset"
  chmod +x "$sd"
  # macOS: clear the quarantine flag so it runs without a Gatekeeper prompt.
  if [ "$os" = "Darwin" ]; then xattr -d com.apple.quarantine "$sd" 2>/dev/null || true; fi
  info "slackdump installed."
fi

# --- 2. Python -------------------------------------------------------------
find_python() {
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,9) else 1)' 2>/dev/null; then
        command -v "$c"; return 0
      fi
    fi
  done
  return 1
}

if ! PY="$(find_python)"; then
  warn "Python 3.9+ not found."
  if [ "$os" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    info "Installing Python via Homebrew ..."; brew install python
  elif command -v apt-get >/dev/null 2>&1; then
    echo "Install Python, e.g.:  sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip"; exit 1
  elif command -v dnf >/dev/null 2>&1; then
    echo "Install Python, e.g.:  sudo dnf install -y python3 python3-pip"; exit 1
  else
    echo "Please install Python 3.9+ from https://www.python.org/downloads/ and re-run."; exit 1
  fi
  PY="$(find_python)"
fi
info "Using Python: $PY"

# --- 3. virtualenv + deps --------------------------------------------------
VENV="$ROOT/.venv"
# (Re)create the venv if it's missing OR broken (a venv without pip happens when
# python3-venv wasn't installed at creation time, common on fresh Ubuntu).
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  info "Creating virtual environment (.venv) ..."
  rm -rf "$VENV"
  if ! "$PY" -m venv "$VENV"; then
    warn "Could not create a virtualenv. On Debian/Ubuntu install it first:"
    echo "  sudo apt install -y python3-venv python3-pip"
    exit 1
  fi
  # some distros don't bootstrap pip into the venv; make sure it's there
  "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
fi
if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  warn "pip is missing inside the venv. On Debian/Ubuntu: sudo apt install -y python3-venv python3-pip, then re-run."
  exit 1
fi
info "Installing Python dependencies ..."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$ROOT/requirements.txt"

echo
info "Setup complete."
cat <<'EOF'
Next steps:
  1) Back up your Slack history:      ./backup.sh
       (Enterprise Grid:  ./backup.sh --enterprise --workspace <subdomain>)
  2) Build the index + open search:   ./search.sh
EOF
