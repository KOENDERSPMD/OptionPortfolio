#!/usr/bin/env bash
# Start __TITLE__: sets up the Python environment when needed, starts the server and opens the app
# in its own window (Chrome/Chromium app mode) or, failing that, in the default browser.
# Everything the server prints also goes to data/__pkg__.log.
# Options: __ENV___PORT=8800 ./start.sh   ·   __ENV___NO_BROWSER=1 ./start.sh (server only)
set -uo pipefail
cd "$(dirname "$0")"

PORT="${__ENV___PORT:-__PORT__}"
URL="http://127.0.0.1:${PORT}/"
mkdir -p data
LOG="data/__pkg__.log"

fail() {
  echo
  echo "ERROR: $1"
  echo "The full log is in $(pwd)/$LOG"
  # When started from the applications menu the terminal would close at once; keep it open.
  [ -t 0 ] && read -r -p "Press Enter to close this window..." _
  exit 1
}

# Is this app answering on the port? (Checks /api/health, so another program doesn't count.)
is_up() {
  python3 - "${URL}api/health" <<'PY' 2>/dev/null
import json, sys, urllib.request
try:
    assert json.load(urllib.request.urlopen(sys.argv[1], timeout=3))["app"] == "__pkg__"
except Exception:
    sys.exit(1)
PY
}

# Is anything at all listening on the port?
port_taken() {
  python3 - "$PORT" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(1)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

command -v python3 >/dev/null 2>&1 || fail "python3 is not installed (sudo apt install python3 python3-venv)."

# ---- Python environment (packages are only (re)installed when requirements.txt changes) --------
if [ ! -x .venv/bin/python ]; then
  echo "First run: creating the Python environment in .venv ..."
  python3 -m venv .venv >>"$LOG" 2>&1 || fail "Could not create the Python environment. On Ubuntu/Debian run: sudo apt install python3-venv  (then delete the .venv folder and try again)"
  .venv/bin/pip install --upgrade pip >>"$LOG" 2>&1
fi
STAMP=".venv/.requirements.sha"
WANT="$(sha256sum requirements.txt | cut -d' ' -f1)"
if [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
  echo "Installing/updating Python packages ..."
  if .venv/bin/pip install -r requirements.txt >>"$LOG" 2>&1; then
    echo "$WANT" > "$STAMP"
  else
    tail -n 15 "$LOG"
    fail "Installing the Python packages failed (see above). Check your internet connection and try again."
  fi
fi

# ---- server --------------------------------------------------------------------------------------
if is_up; then
  echo "__TITLE__ is already running at $URL"
  echo "(If you just updated the app, stop the running one first: click Quit in the app, or run: pkill -f '__pkg__.main')"
elif port_taken; then
  fail "Port ${PORT} is already in use by another program.
Start __TITLE__ on another port:  __ENV___PORT=$((PORT + 1)) ./start.sh"
else
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') starting __TITLE__ ====" >>"$LOG"
  __ENV___PORT="$PORT" .venv/bin/python -u -m __pkg__.main >>"$LOG" 2>&1 &
  SERVER_PID=$!
  trap 'kill $SERVER_PID 2>/dev/null' EXIT INT TERM
  for _ in $(seq 1 75); do
    is_up && break
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "---- last lines of $LOG ----"
      tail -n 30 "$LOG"
      fail "The server stopped during start-up (see the lines above)."
    fi
    sleep 0.2
  done
  is_up || { tail -n 30 "$LOG"; fail "The server did not respond on $URL within 15 seconds."; }
fi

open_app() {
  for b in google-chrome google-chrome-stable chromium chromium-browser brave-browser microsoft-edge; do
    if command -v "$b" >/dev/null 2>&1; then
      "$b" --app="$URL" --new-window >/dev/null 2>&1 &
      return
    fi
  done
  xdg-open "$URL" >/dev/null 2>&1 || echo "Open $URL in your browser."
}
[ "${__ENV___NO_BROWSER:-}" = "1" ] || open_app

if [ -n "${SERVER_PID:-}" ]; then
  echo "__TITLE__ is running at $URL — press Ctrl+C here to stop it. Log: $(pwd)/$LOG"
  tail -n 0 -f "$LOG" --pid="$SERVER_PID" &
  wait "$SERVER_PID"
  STATUS=$?
  [ "$STATUS" -eq 0 ] || [ "$STATUS" -eq 130 ] || [ "$STATUS" -eq 143 ] || fail "The server stopped unexpectedly (exit code $STATUS)."
fi
