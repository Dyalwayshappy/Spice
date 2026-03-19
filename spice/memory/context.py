from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from spice.protocols import utc_now


def _next_context_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


@dataclass(slots=True)
class CompiledContextBase:
    id: str
    context_type: str
    timestamp: datetime = field(default_factory=utc_now)
    schema_version: str = "0.1"
    world_state_id: str = ""
    domain: str = "generic"
    trace_id: str | None = None
    budget: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DecisionContext(CompiledContextBase):
    objectives: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)
    signals: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    resources: dict[str, Any] = field(default_factory=dict)
    active_intents: list[dict[str, Any]] = field(default_factory=list)
    recent_outcomes: list[dict[str, Any]] = field(default_factory=list)
    retrieved_memory: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        world_state_id: str,
        domain: str,
        **kwargs: Any,
    ) -> "DecisionContext":
        return cls(
            id=_next_context_id("decision-ctx"),
            context_type="decision",
            world_state_id=world_state_id,
            domain=domain,
            **kwargs,
        )


@dataclass(slots=True)
class SimulationContext(CompiledContextBase):
    decision_context_ref: str | None = None
    candidate_decisions: list[dict[str, Any]] = field(default_factory=list)
    candidate_intents: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    evaluation_axes: list[dict[str, Any]] = field(default_factory=list)
    historical_analogs: list[dict[str, Any]] = field(default_factory=list)
    retrieved_memory: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        world_state_id: str,
        domain: str,
        **kwargs: Any,
    ) -> "SimulationContext":
        return cls(
            id=_next_context_id("simulation-ctx"),
            context_type="simulation",
            world_state_id=world_state_id,
            domain=domain,
            **kwargs,
        )


@dataclass(slots=True)
class ReflectionContext(CompiledContextBase):
    executed_path: dict[str, Any] = field(default_factory=dict)
    expected_vs_actual: dict[str, Any] = field(default_factory=dict)
    impact_summary: dict[str, Any] = field(default_factory=dict)
    retrieved_lessons: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    retrieved_memory: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        world_state_id: str,
        domain: str,
        **kwargs: Any,
    ) -> "ReflectionContext":
        return cls(
            id=_next_context_id("reflection-ctx"),
            context_type="reflection",
            world_state_id=world_state_id,
            domain=domain,
            **kwargs,
        )
