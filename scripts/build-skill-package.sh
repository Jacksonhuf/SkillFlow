#!/usr/bin/env bash
# Build a Skill Hub upload artifact (maintainers only). End users install from your internal hub.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 - <<'PY'
from browser_skill.install import build_skill_package

skill_dir, zip_path = build_skill_package()
print(f"skill dir: {skill_dir}")
print(f"hub zip:   {zip_path}")
PY
