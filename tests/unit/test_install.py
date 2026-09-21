import tempfile
from pathlib import Path

from browser_skill.install import install_skill_paths, repo_root, sync_skill_tree


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
