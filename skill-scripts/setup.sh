#!/usr/bin/env bash
# Optional: install bundled runtime into the current Python (not required if using scripts/invoke.py).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m pip install -q "${ROOT}/runtime"
echo "Installed runtime from ${ROOT}/runtime"
echo "You can also run: python3 ${ROOT}/scripts/invoke.py doctor"
