from __future__ import annotations

from typing import Any
from uuid import uuid4

from spice.protocols import Observation


class ExampleInputAdapter:
    """
    Minimal adapter example.

    Converts a generic external input dict into an Observation record.
    """

    def to_observation(self, external_input: dict[str, Any]) -> Observation:
        return Observation(
            id=str(external_input.get("id") or f"obs-{uuid4().hex}"),
            observation_type=str(external_input.get("observation_type", "starter.signal")),
            source=external_input.get("source", "starter.adapter"),
            attributes=dict(external_input.get("attributes", {})),
            metadata=dict(external_input.get("metadata", {})),
        )
