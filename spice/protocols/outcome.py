from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spice.protocols.base import ProtocolRecord


@dataclass(slots=True)
class Outcome(ProtocolRecord):
    outcome_type: str = "state_change"
    status: str = "observed"
    decision_id: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
