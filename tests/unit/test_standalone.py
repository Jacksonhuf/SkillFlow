from pathlib import Path

from browser_skill.standalone import resolve_skill_root


def test_resolve_skill_root_from_repo_full_package(tmp_path: Path) -> None:
    skill = tmp_path / "universal-browser"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: universal-browser\ndescription: test\n---\n", encoding="utf-8")
    (skill / "templates").mkdir()
    found = resolve_skill_root(skill)
    assert found == skill.resolve()
