from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

_PACKAGE_VERSION = "0.1.4"
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


def _runtime_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {"__pycache__", ".mypy_cache", "tests"}}


def sync_full_skill_tree(
    destination: Path,
    *,
    root: Path | None = None,
) -> Path:
    """Standard skill tree plus bundled templates/ and runtime/ Python source."""
    base = repo_root(root)
    skill_dir = sync_skill_tree(destination, root=base)

    templates_src = base / "templates"
    templates_dest = skill_dir / "templates"
    if templates_src.is_dir():
        if templates_dest.exists():
            shutil.rmtree(templates_dest)
        shutil.copytree(templates_src, templates_dest)

    runtime_dest = skill_dir / "runtime"
    if runtime_dest.exists():
        shutil.rmtree(runtime_dest)
    runtime_dest.mkdir(parents=True)
    shutil.copy2(base / "pyproject.toml", runtime_dest / "pyproject.toml")
    shutil.copytree(
        base / "src" / "browser_skill",
        runtime_dest / "src" / "browser_skill",
        ignore=_runtime_ignore,
    )

    runtime_doc = base / "docs" / "RUNTIME.zh.md"
    if runtime_doc.exists():
        shutil.copy2(runtime_doc, skill_dir / "RUNTIME.zh.md")

    hub_doc = base / "docs" / "STANDALONE.zh.md"
    if hub_doc.exists():
        shutil.copy2(hub_doc, skill_dir / "STANDALONE.zh.md")

    scripts_src = base / "skill-scripts"
    scripts_dest = skill_dir / "scripts"
    if scripts_src.is_dir():
        if scripts_dest.exists():
            shutil.rmtree(scripts_dest)
        shutil.copytree(scripts_src, scripts_dest)
        (scripts_dest / "invoke.py").chmod(0o755)
        (scripts_dest / "setup.sh").chmod(0o755)

    vendor_src = base / "vendor" / "chrome-use"
    if vendor_src.is_dir() and any(vendor_src.iterdir()):
        vendor_dest = skill_dir / "vendor" / "chrome-use"
        vendor_dest.parent.mkdir(parents=True, exist_ok=True)
        if vendor_dest.exists():
            shutil.rmtree(vendor_dest)
        shutil.copytree(vendor_src, vendor_dest)

    return skill_dir


def _write_skill_zip(
    package_root: Path,
    skill_dir: Path,
    zip_path: Path,
    *,
    include_hub_manifest: bool,
    manifest_path: Path,
) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in skill_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(package_root).as_posix())
        if include_hub_manifest and manifest_path.exists():
            archive.write(manifest_path, "hub.manifest.json")


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


def build_full_skill_package(
    *,
    root: Path | None = None,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Build zip with SKILL.md, references/, templates/, and installable runtime/ source."""
    base = repo_root(root)
    package_root = base / "skill-package"
    skill_dir = sync_full_skill_tree(package_root, root=base)

    dist = output_dir or (base / "dist")
    dist.mkdir(parents=True, exist_ok=True)
    zip_path = dist / f"{_SKILL_ID}-full-{_PACKAGE_VERSION}.zip"
    manifest_path = package_root / "hub.manifest.json"
    _write_skill_zip(
        package_root,
        skill_dir,
        zip_path,
        include_hub_manifest=False,
        manifest_path=manifest_path,
    )
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
