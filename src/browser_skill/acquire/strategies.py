from __future__ import annotations

from browser_skill.models import AcquisitionSource, LearnedMapping

DEFAULT_ACQUISITION_ORDER: tuple[AcquisitionSource, ...] = (
    AcquisitionSource.API,
    AcquisitionSource.NETWORK,
    AcquisitionSource.DOM,
    AcquisitionSource.BROWSER,
    AcquisitionSource.VISION,
)


class AcquisitionPlanner:
    """Choose acquisition strategies per field/attachment from learned hints."""

    def __init__(self, order: tuple[AcquisitionSource, ...] | None = None) -> None:
        self.order = order or DEFAULT_ACQUISITION_ORDER

    def preferred(self, mapping: LearnedMapping | None) -> AcquisitionSource:
        if mapping and mapping.preferred_source is not None:
            return mapping.preferred_source
        if mapping and mapping.strategy == "dom_hint":
            return AcquisitionSource.DOM
        return AcquisitionSource.DOM

    def fallback_chain(self, mapping: LearnedMapping | None) -> list[AcquisitionSource]:
        preferred = self.preferred(mapping)
        chain: list[AcquisitionSource] = [preferred]
        for source in self.order:
            if source not in chain:
                chain.append(source)
        return chain
