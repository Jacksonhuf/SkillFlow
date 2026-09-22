#!/usr/bin/env bash
# Build Skill Hub artifacts.
#   ./scripts/build-skill-package.sh              # standard SKILL zip (~5KB)
#   ./scripts/build-skill-package.sh --full       # Hub full skill (<5MB, no chrome-use exe)
#   ./scripts/build-skill-package.sh --chrome-use-sidecar  # IT-only sidecar (~23MB)
#   ./scripts/build-skill-package.sh --chrome-use-installer # one-click BAT+PS1+exe (~9MB)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FULL=0
SIDECAR=0
INSTALLER=0
for arg in "$@"; do
  case "$arg" in
    --full) FULL=1 ;;
    --chrome-use-sidecar) SIDECAR=1 ;;
    --chrome-use-installer) INSTALLER=1 ;;
  esac
done
python3 - <<PY
from browser_skill.install import (
    build_chrome_use_installer_package,
    build_chrome_use_sidecar_package,
    build_full_skill_package,
    build_skill_package,
)

if ${INSTALLER}:
    _, zip_path = build_chrome_use_installer_package()
elif ${SIDECAR}:
    _, zip_path = build_chrome_use_sidecar_package()
elif ${FULL}:
    skill_dir, zip_path = build_full_skill_package(bundle_chrome_use=False)
    print(f"skill dir: {skill_dir}")
else:
    skill_dir, zip_path = build_skill_package()
    print(f"skill dir: {skill_dir}")
print(f"zip:       {zip_path}")
PY
