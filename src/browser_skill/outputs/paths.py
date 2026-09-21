from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from browser_skill.errors import ErrorCode, SkillError


def safe_filename(value: str, *, fallback: str = "file", max_length: int = 120) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = value.replace("/", "_").replace("\\", "_")
    value = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", value)
    value = re.sub(r"\.{2,}", ".", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if value in {"", ".", ".."}:
        value = fallback
    stem, suffix = Path(value).stem, Path(value).suffix
    allowed_stem = max(1, max_length - len(suffix))
    return f"{stem[:allowed_stem]}{suffix[:16]}"


def contained_path(root: Path, *parts: str) -> Path:
    root = root.resolve()
    candidate = root.joinpath(*parts).resolve()
    if candidate != root and root not in candidate.parents:
        raise SkillError(ErrorCode.UNSAFE_OUTPUT_PATH, "Output path escapes the run workspace")
    return candidate


def safe_relative_subdir(value: str) -> str:
    parts = [safe_filename(part, fallback="dir", max_length=60) for part in Path(value).parts]
    if not parts or any(part in {"..", "."} for part in parts):
        raise SkillError(ErrorCode.UNSAFE_OUTPUT_PATH, "Unsafe output subdirectory")
    return str(Path(*parts))
