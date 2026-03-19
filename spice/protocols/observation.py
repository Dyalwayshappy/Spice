from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spice.protocols.base import ProtocolRecord


@dataclass(slots=True)
class Observation(ProtocolRecord):
    observation_type: str = "generic"
    source: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
