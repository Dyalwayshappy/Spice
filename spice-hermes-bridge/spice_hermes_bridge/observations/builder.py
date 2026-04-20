from __future__ import annotations

from typing import Any

from spice_hermes_bridge.observations.schema import (
    StructuredObservation,
    generate_observation_id,
    utc_now_iso,
)


def build_observation(
    *,
    observation_type: str,
    source: str,
    attributes: dict[str, Any],
    confidence: float = 1.0,
    provenance: dict[str, Any] | None = None,
    observed_at: str | None = None,
) -> StructuredObservation:
    """Build a bridge-owned observation with generated identity and timestamp."""

    return StructuredObservation(
        observation_id=generate_observation_id(),
        observation_type=observation_type,
        source=source,
        observed_at=observed_at or utc_now_iso(),
        confidence=confidence,
        attributes=attributes,
        provenance=provenance or {},
    )

