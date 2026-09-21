#!/usr/bin/env bash
# One-step install for SkillFlow (Python runtime + OpenCode / Agent Skills directories).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GLOBAL=0
if [[ "${1:-}" == "--global" ]] || [[ "${2:-}" == "--global" ]]; then
  GLOBAL=1
fi

echo "==> SkillFlow install (root: $ROOT)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "==> Creating virtualenv .venv"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing Python package (browser-skill CLI)"
pip install -q -U pip
pip install -q -e '.[cli]'

SETUP_ARGS=()
if [[ "$GLOBAL" -eq 1 ]]; then
  SETUP_ARGS+=(--global)
fi

echo "==> Installing standard Skill directories for OpenCode / Agent Skills"
python -m browser_skill.setup "${SETUP_ARGS[@]}"

echo ""
echo "✓ 安装完成"
echo ""
echo "在 Agent 对话里输入:  /universal-browser"
echo "或说: 「列出浏览器任务」"
echo ""
echo "用户指南: docs/QUICKSTART.zh.md"
echo "维护者:   browser-skill templates"
