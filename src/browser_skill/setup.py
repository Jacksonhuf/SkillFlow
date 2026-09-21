"""Install Skill directories for OpenCode / standard Agent Skills layouts."""

from __future__ import annotations

import argparse
from pathlib import Path

from browser_skill.install import default_skill_targets, install_skill_paths, repo_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install universal-browser skill directories")
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Install to ~/.config/opencode/skills (all projects on this machine)",
    )
    parser.add_argument(
        "--skills-root",
        type=Path,
        action="append",
        help="Custom skills root (repeatable). Installs universal-browser/ underneath.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="SkillFlow repository root (auto-detected by default)",
    )
    args = parser.parse_args(argv)

    root = repo_root(args.project)
    if args.skills_root:
        targets = list(args.skills_root)
    else:
        targets = default_skill_targets(global_install=args.global_install)

    installed = install_skill_paths(targets, root=root)
    for path in installed:
        print(f"installed: {path / 'SKILL.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
