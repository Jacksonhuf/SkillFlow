import tempfile
from pathlib import Path

from browser_skill.install import (
    build_full_skill_package,
    build_skill_package,
    install_skill_paths,
    repo_root,
    sync_skill_tree,
)


def test_sync_skill_tree_copies_skill_and_references() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        dest = sync_skill_tree(Path(tmp))
        assert (dest / "SKILL.md").exists()
        assert (dest / "references" / "runbook.md").exists()
        assert "universal-browser" in str(dest)


def test_install_skill_paths() -> None:
    root = repo_root()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "skills"
        paths = install_skill_paths([target], root=root)
        assert len(paths) == 1
        assert paths[0].name == "universal-browser"


def test_build_skill_package_produces_zip() -> None:
    root = repo_root()
    with tempfile.TemporaryDirectory() as tmp:
        _, zip_path = build_skill_package(root=root, output_dir=Path(tmp))
        assert zip_path.exists()
        assert zip_path.name == "universal-browser-0.3.7.zip"


def test_full_skill_package_under_five_megabytes() -> None:
    root = repo_root()
    with tempfile.TemporaryDirectory() as tmp:
        _, zip_path = build_full_skill_package(root=root, output_dir=Path(tmp))
        assert zip_path.stat().st_size <= 5 * 1024 * 1024


def test_build_full_skill_package_includes_runtime_and_templates() -> None:
    root = repo_root()
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir, zip_path = build_full_skill_package(root=root, output_dir=Path(tmp))
        assert (skill_dir / "templates" / "inventory_feedback" / "1.yaml").exists()
        assert (skill_dir / "runtime" / "src" / "browser_skill" / "app.py").exists()
        assert zip_path.name.endswith(".zip")
        assert "full" in zip_path.name
        # One-click entry points sit at the skill root next to SKILL.md
        assert (skill_dir / "open-console.bat").is_file()
        assert (skill_dir / "open-console.sh").is_file()
        assert (skill_dir / "QUICKSTART.zh.md").is_file()
