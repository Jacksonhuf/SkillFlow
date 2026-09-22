#!/usr/bin/env bash
# Universal Browser - open the local console (macOS / Linux). Double-click or run from a terminal.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVOKE="$HERE/scripts/invoke.py"
[ -f "$INVOKE" ] || INVOKE="$HERE/invoke.py"
if [ ! -f "$INVOKE" ]; then
  echo "Cannot find invoke.py next to this launcher. Please re-extract the skill package." >&2
  exit 2
fi
PY=""
for candidate in python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.12+ is required: https://www.python.org/downloads/" >&2
  exit 2
fi
echo "Starting Universal Browser console... A browser tab opens automatically."
echo "Keep this terminal open while you use the console. Press Ctrl+C to stop."
exec "$PY" "$INVOKE" ui "$@"
