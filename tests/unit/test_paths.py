from pathlib import Path

import pytest

from browser_skill.errors import SkillError
from browser_skill.outputs.paths import contained_path, safe_filename


def test_safe_filename_removes_traversal_and_reserved_characters() -> None:
    name = safe_filename("../../contract:01?.pdf")
    assert "/" not in name
    assert "\\" not in name
    assert ":" not in name
    assert "?" not in name
    assert name.endswith(".pdf")


def test_contained_path_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(SkillError):
        contained_path(tmp_path, "..", "escape")
