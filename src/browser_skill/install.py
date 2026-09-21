from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

_PACKAGE_VERSION = "0.1.0"
_SKILL_ID = "universal-browser"


def repo_root(start: Path | None = None) -> Path:
    path = (start or Path(__file__)).resolve()
    for parent in [path, *path.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "SKILL.md").exists():
            return parent
    raise FileNotFoundError("Could not locate SkillFlow repository root")


def skill_source(root: Path | None = None) -> Path:
    base = repo_root(root)
    packaged = base / "skill-package" / _SKILL_ID
    if (packaged / "SKILL.md").exists():
        return packaged
    bundled = base / ".opencode" / "skills" / _SKILL_ID
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
    dest = destination / _SKILL_ID
    if dest.exists():
        shutil.rmtree(dest)
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

    return dest


def build_skill_package(
    *,
    root: Path | None = None,
    output_dir: Path | None = None,
    include_hub_manifest: bool = False,
) -> tuple[Path, Path]:
    """Build ``skill-package/universal-browser`` and ``dist/universal-browser-<version>.zip``.

    The zip contains only the standard skill tree (``universal-browser/SKILL.md`` and optional
    ``references/``). ``hub.manifest.json`` is optional SkillFlow publish metadata, not part of
    OpenCode / Open Agent Skills.
    """
    base = repo_root(root)
    package_root = base / "skill-package"
    skill_dir = sync_skill_tree(package_root, root=base)

    manifest_path = package_root / "hub.manifest.json"
    if include_hub_manifest and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = _PACKAGE_VERSION
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    dist = output_dir or (base / "dist")
    dist.mkdir(parents=True, exist_ok=True)
    zip_path = dist / f"{_SKILL_ID}-{_PACKAGE_VERSION}.zip"

    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in skill_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(package_root).as_posix())
        if include_hub_manifest and manifest_path.exists():
            archive.write(manifest_path, "hub.manifest.json")

    install_skill_paths([base / ".opencode" / "skills"], root=base)
    install_skill_paths([base / ".agents" / "skills"], root=base)

    return skill_dir, zip_path


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
