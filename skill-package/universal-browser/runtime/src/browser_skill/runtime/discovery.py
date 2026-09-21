from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from browser_skill.models import (
    AttachmentSpec,
    BrowserSnapshot,
    BrowserTemplate,
    FieldSpec,
    LearnedMapping,
    LearnedSpec,
    MappingDiscoveryReport,
)


class MappingDiscoveryService:
    """Discover stable semantic mappings without persisting snapshot refs or coordinates."""

    SAFE_ELEMENT_KEYS = ("text", "name", "label", "aria_label", "role", "title")

    def discover(
        self,
        template: BrowserTemplate,
        snapshot: BrowserSnapshot,
    ) -> MappingDiscoveryReport:
        field_mappings = dict(template.learned.field_mappings)
        attachment_mappings = dict(template.learned.attachment_mappings)
        matched_fields: list[str] = []
        missing_fields: list[str] = []
        matched_attachments: list[str] = []
        missing_attachments: list[str] = []

        for field in template.target.fields:
            confidence = self._confidence(field.semantic, snapshot.elements)
            if confidence:
                field_mappings[field.key] = LearnedMapping(
                    page=field.source,
                    strategy="semantic",
                    hints=list(field.semantic),
                    confidence=confidence,
                )
                matched_fields.append(field.key)
            elif field.required:
                missing_fields.append(field.key)

        for attachment in template.target.attachments:
            confidence = self._confidence(attachment.semantic, snapshot.elements)
            if confidence:
                attachment_mappings[attachment.key] = LearnedMapping(
                    page=attachment.source,
                    strategy="semantic",
                    hints=list(attachment.semantic),
                    confidence=confidence,
                )
                matched_attachments.append(attachment.key)
            elif attachment.required:
                missing_attachments.append(attachment.key)

        learned = LearnedSpec(
            page_hints=list(template.learned.page_hints),
            field_mappings=field_mappings,
            attachment_mappings=attachment_mappings,
            validated_at=datetime.now(UTC),
        )
        return MappingDiscoveryReport(
            learned=learned,
            matched_fields=matched_fields,
            missing_required_fields=missing_fields,
            matched_attachments=matched_attachments,
            missing_required_attachments=missing_attachments,
            page_url=snapshot.url,
        )

    def discover_many(
        self,
        template: BrowserTemplate,
        snapshots: list[BrowserSnapshot],
    ) -> MappingDiscoveryReport:
        """Combine bounded observations while respecting list/detail source annotations."""
        elements = [element for snapshot in snapshots for element in snapshot.elements]
        combined = BrowserSnapshot(
            url=snapshots[-1].url if snapshots else "",
            title=" | ".join(snapshot.title for snapshot in snapshots if snapshot.title),
            text="\n".join(snapshot.text for snapshot in snapshots if snapshot.text),
            elements=elements,
        )
        field_mappings = dict(template.learned.field_mappings)
        attachment_mappings = dict(template.learned.attachment_mappings)
        matched_fields: list[str] = []
        missing_fields: list[str] = []
        matched_attachments: list[str] = []
        missing_attachments: list[str] = []

        def map_item(
            item: FieldSpec | AttachmentSpec,
            mappings: dict[str, LearnedMapping],
            matched: list[str],
            missing: list[str],
        ) -> None:
            scoped = [
                element
                for element in combined.elements
                if element.get("_source_page") in {None, item.source.value}
            ]
            confidence = self._confidence(item.semantic, scoped)
            if confidence:
                mappings[item.key] = LearnedMapping(
                    page=item.source,
                    strategy="semantic",
                    hints=list(item.semantic),
                    confidence=confidence,
                )
                matched.append(item.key)
            elif item.required:
                missing.append(item.key)

        for field in template.target.fields:
            map_item(field, field_mappings, matched_fields, missing_fields)
        for attachment in template.target.attachments:
            map_item(
                attachment,
                attachment_mappings,
                matched_attachments,
                missing_attachments,
            )

        learned = LearnedSpec(
            page_hints=list(template.learned.page_hints),
            field_mappings=field_mappings,
            attachment_mappings=attachment_mappings,
            validated_at=datetime.now(UTC),
        )
        return MappingDiscoveryReport(
            learned=learned,
            matched_fields=matched_fields,
            missing_required_fields=missing_fields,
            matched_attachments=matched_attachments,
            missing_required_attachments=missing_attachments,
            page_url=combined.url,
        )

    def _confidence(self, semantics: list[str], elements: list[dict[str, Any]]) -> float:
        candidates = [
            str(element.get(key, "")).strip().casefold()
            for element in elements
            for key in self.SAFE_ELEMENT_KEYS
            if element.get(key) is not None and element.get(key) != ""
        ]
        for semantic in semantics:
            normalized = semantic.strip().casefold()
            if normalized and normalized in candidates:
                return 1.0
        for semantic in semantics:
            normalized = semantic.strip().casefold()
            if normalized and any(normalized in candidate for candidate in candidates):
                return 0.8
        return 0.0
