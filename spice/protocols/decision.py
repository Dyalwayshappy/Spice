from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spice.protocols.base import ProtocolRecord


@dataclass(slots=True)
class Decision(ProtocolRecord):
    decision_type: str = "generic"
    status: str = "proposed"
    selected_action: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
