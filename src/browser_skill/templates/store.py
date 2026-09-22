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
from browser_skill.models import BrowserTemplate, LearnedSpec, TemplateStatus
from browser_skill.templates.learned_store import LearnedProfileStore


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
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.learned = LearnedProfileStore(self.root)

    def _template_dir(self, template_id: str) -> Path:
        if not template_id or any(part in template_id for part in ("/", "\\", "..")):
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Unsafe template identifier")
        candidate = self.root / template_id
        if candidate.is_symlink():
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Template directory cannot be a symlink")
        resolved = candidate.resolve()
        if resolved.parent != self.root:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Template path escapes the store")
        return resolved

    def _template_file(self, template_id: str, filename: str) -> Path:
        directory = self._template_dir(template_id)
        path = directory / filename
        if path.is_symlink():
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Template files cannot be symlinks")
        resolved = path.resolve()
        if resolved.parent != directory:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Template file escapes its directory")
        if resolved.exists() and not resolved.is_file():
            raise SkillError(ErrorCode.TEMPLATE_INVALID, "Template path is not a regular file")
        return resolved

    @staticmethod
    def _version_number(value: Any, *, field: str) -> int:
        if isinstance(value, bool):
            raise SkillError(ErrorCode.TEMPLATE_INVALID, f"Invalid metadata field: {field}")
        try:
            version = int(value)
        except (TypeError, ValueError) as exc:
            raise SkillError(
                ErrorCode.TEMPLATE_INVALID, f"Invalid metadata field: {field}"
            ) from exc
        if version < 1:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, f"Invalid metadata field: {field}")
        return version

    def _metadata(self, template_id: str) -> dict[str, Any]:
        path = self._template_file(template_id, "metadata.json")
        if not path.exists():
            return {}
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillError(
                ErrorCode.TEMPLATE_INVALID, f"Invalid metadata for {template_id}"
            ) from exc
        if not isinstance(metadata, dict):
            raise SkillError(ErrorCode.TEMPLATE_INVALID, f"Invalid metadata for {template_id}")
        stored_id = metadata.get("template_id")
        if stored_id is not None and stored_id != template_id:
            raise SkillError(ErrorCode.TEMPLATE_INVALID, f"Invalid metadata for {template_id}")
        for field in ("latest_version", "published_version"):
            if metadata.get(field) is not None:
                self._version_number(metadata[field], field=field)
        return cast(dict[str, Any], metadata)

    def next_version(self, template_id: str) -> int:
        metadata = self._metadata(template_id)
        raw_latest = metadata.get("latest_version")
        if raw_latest is not None:
            return self._version_number(raw_latest, field="latest_version") + 1
        directory = self._template_dir(template_id)
        versions = [
            int(path.stem)
            for path in directory.glob("[0-9]*.yaml")
            if path.is_file() and not path.is_symlink() and path.stem.isdigit()
        ]
        return max(versions, default=0) + 1

    def list(self, *, include_unpublished: bool = False) -> list[TemplateSummary]:
        results: list[TemplateSummary] = []
        for directory in sorted(
            path for path in self.root.iterdir() if path.is_dir() and not path.is_symlink()
        ):
            try:
                metadata = self._metadata(directory.name)
                version = metadata.get(
                    "latest_version" if include_unpublished else "published_version"
                )
                if version is None:
                    versions = sorted(
                        int(p.stem)
                        for p in directory.glob("[0-9]*.yaml")
                        if p.is_file() and not p.is_symlink() and p.stem.isdigit()
                    )
                    version = versions[-1] if versions else None
                if version is None:
                    continue
                template = self.load(
                    directory.name,
                    self._version_number(version, field="template version"),
                    require_published=False,
                )
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
        version = self._version_number(version, field="template version")
        path = self._template_file(template_id, f"{version}.yaml")
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
        return self._hydrate_learned(template)

    def _hydrate_learned(self, template: BrowserTemplate) -> BrowserTemplate:
        profile = self.learned.load(template.template_id, template.version)
        if profile is not None:
            return template.model_copy(update={"learned": profile}, deep=True)
        return template

    def save(self, template: BrowserTemplate) -> Path:
        directory = self._template_dir(template.template_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = self._template_file(template.template_id, f"{template.version}.yaml")
        if target.exists():
            existing = self.load(template.template_id, template.version, require_published=False)
            if existing != template:
                raise SkillError(ErrorCode.TEMPLATE_INVALID, "Template versions are immutable")
            return target
        learned_payload = template.learned
        persisted = template
        if template.schema_version == "2.0" and learned_payload != LearnedSpec():
            self.learned.save(template.template_id, template.version, learned_payload)
            persisted = template.model_copy(update={"learned": LearnedSpec()}, deep=True)
        content = yaml.safe_dump(
            json.loads(persisted.model_dump_json()), allow_unicode=True, sort_keys=False
        )
        self._atomic_write(target, content)
        metadata = self._metadata(template.template_id)
        metadata.update(
            {
                "template_id": template.template_id,
                "latest_version": max(
                    self._version_number(metadata["latest_version"], field="latest_version")
                    if metadata.get("latest_version") is not None
                    else 0,
                    template.version,
                ),
                "published_version": metadata.get("published_version"),
            }
        )
        if template.status == TemplateStatus.PUBLISHED:
            metadata["published_version"] = template.version
        self._atomic_write(
            self._template_file(template.template_id, "metadata.json"),
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        )
        return target

    def save_learned_profile(
        self, template_id: str, version: int, learned: LearnedSpec
    ) -> Path:
        return self.learned.save(template_id, version, learned)

    def publish(self, template_id: str, version: int, *, test_passed: bool) -> BrowserTemplate:
        if not test_passed:
            raise SkillError(
                ErrorCode.VALIDATION_FAILED, "A passing test run is required before publish"
            )
        current = self.load(template_id, version, require_published=False)
        published = current.model_copy(update={"status": TemplateStatus.PUBLISHED})
        path = self._template_file(template_id, f"{version}.yaml")
        content = yaml.safe_dump(
            json.loads(published.model_dump_json()), allow_unicode=True, sort_keys=False
        )
        self._atomic_write(path, content)
        metadata = self._metadata(template_id)
        metadata["published_version"] = version
        metadata["latest_version"] = max(
            self._version_number(metadata["latest_version"], field="latest_version")
            if metadata.get("latest_version") is not None
            else 0,
            version,
        )
        self._atomic_write(
            self._template_file(template_id, "metadata.json"),
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
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
