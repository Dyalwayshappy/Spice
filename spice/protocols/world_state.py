from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spice.protocols.base import ProtocolRecord


@dataclass(slots=True)
class WorldState(ProtocolRecord):
    schema_version: str = "0.1"
    status: str = "current"
    entities: dict[str, Any] = field(default_factory=dict)
    relations: list[dict[str, Any]] = field(default_factory=list)
    goals: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    resources: dict[str, Any] = field(default_factory=dict)
    risks: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    active_intents: list[dict[str, Any]] = field(default_factory=list)
    recent_outcomes: list[dict[str, Any]] = field(default_factory=list)
    confidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    domain_state: dict[str, Any] = field(default_factory=dict)
