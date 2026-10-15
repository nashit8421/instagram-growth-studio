#!/bin/sh
# IG Studio for Linux. Run ./ig-studio.sh (or double-click "IG Studio.desktop").
# Stop it with Ctrl+C here, or Settings > Quit in the app.
cd "$(dirname "$0")" || exit 1
for p in python3 python /usr/local/bin/python3 /usr/bin/python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    exec "$p" server.py "$@"
  fi
done
MSG="IG Studio needs Python 3.9 or newer. Install it with your package manager (for example: sudo apt install python3), then start IG Studio again."
if command -v zenity >/dev/null 2>&1; then zenity --error --title="IG Studio" --text="$MSG"
elif command -v kdialog >/dev/null 2>&1; then kdialog --title "IG Studio" --error "$MSG"
elif command -v notify-send >/dev/null 2>&1; then notify-send "IG Studio" "$MSG"
fi
echo "$MSG" >&2
exit 1
