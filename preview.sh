#!/usr/bin/env bash
# preview.sh — bring up the dashboard browser preview, repairing deps if needed.
#
# The preview needs fastapi/uvicorn/cryptography/python-multipart, which are not
# part of the desktop app's requirements. This launcher keeps them in a venv
# outside the repo and reinstalls them automatically when the venv is missing or
# incomplete (e.g. on a fresh checkout or after a sandbox restart).
#
#   ./preview.sh                     # http://0.0.0.0:8000
#   JARVIS_PREVIEW_PORT=9000 ./preview.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="${JARVIS_PREVIEW_VENV:-$HOME/.jarvis-preview-venv}"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
  echo "[preview] creating venv at $VENV"
  python3 -m venv "$VENV"
  "$PY" -m pip install --quiet --upgrade pip
fi

if ! "$PY" -c 'import fastapi, uvicorn, cryptography, multipart' >/dev/null 2>&1; then
  echo "[preview] installing dashboard dependencies…"
  "$PY" -m pip install --quiet fastapi "uvicorn[standard]" cryptography python-multipart
fi

# Unbuffered so startup/status lines reach the log immediately (no TTY here).
export PYTHONUNBUFFERED=1
exec "$PY" -m dashboard.preview
