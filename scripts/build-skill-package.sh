#!/usr/bin/env bash
# Build Skill Hub artifacts. Default: standard skill only. Use --full for runtime + templates.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FULL=0
if [[ "${1:-}" == "--full" ]]; then
  FULL=1
fi
python3 - <<PY
from browser_skill.install import build_full_skill_package, build_skill_package

if ${FULL}:
    skill_dir, zip_path = build_full_skill_package()
else:
    skill_dir, zip_path = build_skill_package()
print(f"skill dir: {skill_dir}")
print(f"zip:       {zip_path}")
PY
