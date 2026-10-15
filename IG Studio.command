#!/bin/bash
# IG Studio for macOS. Double-click to start. Close this window (or press Ctrl+C) to stop.
cd "$(dirname "$0")" || exit 1

ok_python() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}
find_python() {
  for p in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ "$p" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if command -v "$p" >/dev/null 2>&1 && ok_python "$p"; then command -v "$p"; return 0; fi
  done
  return 1
}

PY="$(find_python)"
if [ -z "$PY" ]; then
  osascript -e 'set r to button returned of (display dialog "IG Studio needs Python 3.9 or newer.\n\nInstall it from python.org (or run: brew install python), then double-click IG Studio again." with title "IG Studio" buttons {"Close", "Open python.org"} default button 2 with icon caution)' \
            -e 'if r is "Open python.org" then open location "https://www.python.org/downloads/macos/"' >/dev/null 2>&1
  echo "Python 3.9+ not found. Install it from https://www.python.org/downloads/ and try again."
  exit 1
fi
echo "Starting IG Studio with $PY"
exec "$PY" app/server.py "$@"
