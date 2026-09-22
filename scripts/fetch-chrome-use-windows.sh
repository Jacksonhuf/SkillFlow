#!/usr/bin/env bash
# Download chrome-use Windows bundle into vendor/ for offline full skill builds.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${CHROME_USE_INSTALL_VERSION:-v1.5.131}"
ASSET="chrome-use-win32-x64.tar.gz"
URL="https://github.com/leeguooooo/chrome-use/releases/download/${VERSION}/${ASSET}"
DEST="$ROOT/vendor/chrome-use"
mkdir -p "$DEST"
echo "Fetching $URL"
curl -fsSL "$URL" -o "$DEST/$ASSET"
tar -xzf "$DEST/$ASSET" -C "$DEST"
if [[ -f "$DEST/chrome-use.exe" ]]; then
  echo "OK: $DEST/chrome-use.exe"
else
  find "$DEST" -name chrome-use.exe -print
fi
