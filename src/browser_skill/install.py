from __future__ import annotations

import shutil
from pathlib import Path


def repo_root(start: Path | None = None) -> Path:
    path = (start or Path(__file__)).resolve()
    for parent in [path, *path.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "SKILL.md").exists():
            return parent
    raise FileNotFoundError("Could not locate SkillFlow repository root")


def skill_source(root: Path | None = None) -> Path:
    base = repo_root(root)
    bundled = base / ".opencode" / "skills" / "universal-browser"
    if (bundled / "SKILL.md").exists():
        return bundled
    return base


def sync_skill_tree(
    destination: Path,
    *,
    root: Path | None = None,
) -> Path:
    """Copy universal-browser skill (SKILL.md + references) into an OpenCode-style directory."""
    base = repo_root(root)
    dest = destination / "universal-browser"
    dest.mkdir(parents=True, exist_ok=True)

    skill_md = base / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"Missing {skill_md}")

    shutil.copy2(skill_md, dest / "SKILL.md")

    references_src = base / "references"
    references_dest = dest / "references"
    if references_src.is_dir():
        if references_dest.exists():
            shutil.rmtree(references_dest)
        shutil.copytree(references_src, references_dest)

    quickstart_src = base / "docs" / "QUICKSTART.zh.md"
    if quickstart_src.exists():
        shutil.copy2(quickstart_src, dest / "QUICKSTART.zh.md")

    return dest


def default_skill_targets(*, global_install: bool = False) -> list[Path]:
    if global_install:
        return [Path.home() / ".config" / "opencode" / "skills"]
    return [
        Path(".opencode") / "skills",
        Path(".agents") / "skills",
    ]


def install_skill_paths(
    targets: list[Path],
    *,
    root: Path | None = None,
) -> list[Path]:
    installed: list[Path] = []
    for target in targets:
        installed.append(sync_skill_tree(target.resolve(), root=root))
    return installed
