from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spice.protocols.base import ProtocolRecord


@dataclass(slots=True)
class Reflection(ProtocolRecord):
    reflection_type: str = "post_execution"
    status: str = "recorded"
    insights: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
