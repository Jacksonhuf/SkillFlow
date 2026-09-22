from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import LearnedProfileDocument, LearnedSpec


class LearnedProfileStore:
    """Filesystem-backed learned profiles, one file per template version."""

    def __init__(self, templates_root: Path) -> None:
        self.root = templates_root.resolve()

    def _learned_dir(self, template_id: str) -> Path:
        if not template_id or any(part in template_id for part in ("/", "\\", "..")):
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Unsafe template identifier")
        directory = (self.root / template_id / "learned").resolve()
        store_root = (self.root / template_id).resolve()
        if store_root.parent != self.root:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Template path escapes the store")
        if directory.parent != store_root:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Learned path escapes template directory")
        return directory

    def _learned_file(self, template_id: str, version: int) -> Path:
        directory = self._learned_dir(template_id)
        path = (directory / f"{version}.yaml").resolve()
        if path.parent != directory:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Learned file escapes its directory")
        if path.is_symlink():
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Learned profile cannot be a symlink")
        return path

    def load(self, template_id: str, version: int) -> LearnedSpec | None:
        path = self._learned_file(template_id, version)
        if not path.is_file():
            return None
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if raw is None:
                return LearnedSpec()
            if isinstance(raw, dict) and "learned" in raw:
                document = LearnedProfileDocument.model_validate(raw)
                if document.template_id != template_id or document.template_version != version:
                    raise SkillError(
                        ErrorCode.TEMPLATE_INVALID,
                        "Learned profile identity does not match template version",
                    )
                return document.learned
            return LearnedSpec.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError, TypeError) as exc:
            raise SkillError(
                ErrorCode.TEMPLATE_INVALID,
                f"Invalid learned profile: {template_id}@{version}",
            ) from exc

    def save(self, template_id: str, version: int, learned: LearnedSpec) -> Path:
        directory = self._learned_dir(template_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = self._learned_file(template_id, version)
        document = LearnedProfileDocument(
            template_id=template_id,
            template_version=version,
            learned=learned,
        )
        content = yaml.safe_dump(
            json.loads(document.model_dump_json()),
            allow_unicode=True,
            sort_keys=False,
        )
        self._atomic_write(target, content)
        return target

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
