from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from browser_skill.errors import ErrorCode, SkillError
from browser_skill.models import BrowserTemplate, TemplateStatus


@dataclass(frozen=True, slots=True)
class TemplateSummary:
    template_id: str
    version: int
    name: str
    description: str
    status: TemplateStatus


class TemplateStore:
    """Filesystem-backed immutable template versions with atomic metadata pointers."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _template_dir(self, template_id: str) -> Path:
        if not template_id or any(part in template_id for part in ("/", "\\", "..")):
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Unsafe template identifier")
        return self.root / template_id

    def _metadata(self, template_id: str) -> dict[str, Any]:
        path = self._template_dir(template_id) / "metadata.json"
        if not path.exists():
            return {}
        try:
            return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillError(
                ErrorCode.TEMPLATE_INVALID, f"Invalid metadata for {template_id}"
            ) from exc

    def next_version(self, template_id: str) -> int:
        metadata = self._metadata(template_id)
        latest = int(metadata.get("latest_version", 0))
        if latest:
            return latest + 1
        directory = self._template_dir(template_id)
        versions = [int(path.stem) for path in directory.glob("[0-9]*.yaml")]
        return max(versions, default=0) + 1

    def list(self, *, include_unpublished: bool = False) -> list[TemplateSummary]:
        results: list[TemplateSummary] = []
        for directory in sorted(path for path in self.root.iterdir() if path.is_dir()):
            try:
                metadata = self._metadata(directory.name)
                version = metadata.get(
                    "latest_version" if include_unpublished else "published_version"
                )
                if version is None:
                    versions = sorted(int(p.stem) for p in directory.glob("[0-9]*.yaml"))
                    version = versions[-1] if versions else None
                if version is None:
                    continue
                template = self.load(directory.name, int(version), require_published=False)
                if not include_unpublished and template.status != TemplateStatus.PUBLISHED:
                    continue
                results.append(
                    TemplateSummary(
                        template_id=template.template_id,
                        version=template.version,
                        name=template.name,
                        description=template.description,
                        status=template.status,
                    )
                )
            except SkillError:
                continue
        return sorted(results, key=lambda item: (item.name.casefold(), item.template_id))

    def load(
        self,
        template_id: str,
        version: int | None = None,
        *,
        require_published: bool = True,
    ) -> BrowserTemplate:
        metadata = self._metadata(template_id)
        if version is None:
            version = metadata.get("published_version" if require_published else "latest_version")
        if version is None:
            raise SkillError(ErrorCode.TEMPLATE_NOT_FOUND, f"Template not found: {template_id}")
        path = self._template_dir(template_id) / f"{version}.yaml"
        if not path.exists():
            raise SkillError(
                ErrorCode.TEMPLATE_NOT_FOUND, f"Template version not found: {template_id}@{version}"
            )
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            template = BrowserTemplate.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError, TypeError) as exc:
            raise SkillError(
                ErrorCode.TEMPLATE_INVALID, f"Invalid template: {template_id}@{version}"
            ) from exc
        if template.template_id != template_id or template.version != version:
            raise SkillError(
                ErrorCode.TEMPLATE_INVALID, "Template identity does not match its path"
            )
        if require_published and template.status != TemplateStatus.PUBLISHED:
            raise SkillError(
                ErrorCode.TEMPLATE_INVALID, f"Template is not published: {template_id}@{version}"
            )
        return template

    def save(self, template: BrowserTemplate) -> Path:
        directory = self._template_dir(template.template_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{template.version}.yaml"
        if target.exists():
            existing = self.load(template.template_id, template.version, require_published=False)
            if existing != template:
                raise SkillError(ErrorCode.TEMPLATE_INVALID, "Template versions are immutable")
            return target
        content = yaml.safe_dump(
            json.loads(template.model_dump_json()), allow_unicode=True, sort_keys=False
        )
        self._atomic_write(target, content)
        metadata = self._metadata(template.template_id)
        metadata.update(
            {
                "template_id": template.template_id,
                "latest_version": max(int(metadata.get("latest_version", 0)), template.version),
                "published_version": metadata.get("published_version"),
            }
        )
        if template.status == TemplateStatus.PUBLISHED:
            metadata["published_version"] = template.version
        self._atomic_write(
            directory / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
        )
        return target

    def publish(self, template_id: str, version: int, *, test_passed: bool) -> BrowserTemplate:
        if not test_passed:
            raise SkillError(
                ErrorCode.VALIDATION_FAILED, "A passing test run is required before publish"
            )
        current = self.load(template_id, version, require_published=False)
        published = current.model_copy(update={"status": TemplateStatus.PUBLISHED})
        path = self._template_dir(template_id) / f"{version}.yaml"
        content = yaml.safe_dump(
            json.loads(published.model_dump_json()), allow_unicode=True, sort_keys=False
        )
        self._atomic_write(path, content)
        metadata = self._metadata(template_id)
        metadata["published_version"] = version
        metadata["latest_version"] = max(int(metadata.get("latest_version", 0)), version)
        self._atomic_write(
            path.parent / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
        )
        return published

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
