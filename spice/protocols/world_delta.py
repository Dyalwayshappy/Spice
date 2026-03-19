from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from spice.protocols.base import ProtocolRecord
from spice.protocols.world_state import WorldState


@dataclass(slots=True)
class DeltaOp:
    op: Literal["upsert", "remove"]
    id: str
    value: Any | None = None


@dataclass(slots=True)
class WorldDelta(ProtocolRecord):
    source_kind: str = "observation"
    source_id: str = ""
    entity_ops: list[DeltaOp] = field(default_factory=list)
    relation_ops: list[DeltaOp] = field(default_factory=list)
    signal_ops: list[DeltaOp] = field(default_factory=list)
    risk_ops: list[DeltaOp] = field(default_factory=list)
    active_intent_ops: list[DeltaOp] = field(default_factory=list)
    goal_ops: list[DeltaOp] = field(default_factory=list)
    resource_patch: dict[str, Any] = field(default_factory=dict)
    provenance_patch: dict[str, Any] = field(default_factory=dict)
    confidence_patch: dict[str, Any] = field(default_factory=dict)
    recent_outcome_additions: list[dict[str, Any]] = field(default_factory=list)
    domain_patch: dict[str, Any] = field(default_factory=dict)


def _apply_dict_ops(target: dict[str, Any], ops: list[DeltaOp]) -> None:
    for op in ops:
        if op.op == "remove":
            target.pop(op.id, None)
            continue
        target[op.id] = op.value if op.value is not None else {}


def _normalize_list_value(op: DeltaOp) -> dict[str, Any]:
    if isinstance(op.value, dict):
        normalized = dict(op.value)
        normalized.setdefault("id", op.id)
        return normalized
    return {"id": op.id, "value": op.value}


def _apply_list_ops(target: list[dict[str, Any]], ops: list[DeltaOp]) -> None:
    for op in ops:
        if op.op == "remove":
            target[:] = [item for item in target if item.get("id") != op.id]
            continue

        value = _normalize_list_value(op)
        for idx, item in enumerate(target):
            if item.get("id") == op.id:
                target[idx] = value
                break
        else:
            target.append(value)


def _deep_merge_dict(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge_dict(target[key], value)
            continue
        target[key] = value


def apply_delta(state: WorldState, delta: WorldDelta) -> WorldState:
    _apply_dict_ops(state.entities, delta.entity_ops)
    _apply_list_ops(state.relations, delta.relation_ops)
    _apply_list_ops(state.signals, delta.signal_ops)
    _apply_list_ops(state.risks, delta.risk_ops)
    _apply_list_ops(state.active_intents, delta.active_intent_ops)
    _apply_list_ops(state.goals, delta.goal_ops)

    state.resources.update(delta.resource_patch)
    state.provenance.update(delta.provenance_patch)
    state.confidence.update(delta.confidence_patch)
    state.recent_outcomes.extend(delta.recent_outcome_additions)
    _deep_merge_dict(state.domain_state, delta.domain_patch)

    if delta.source_id:
        state.refs.append(delta.source_id)
    if delta.refs:
        state.refs.extend(delta.refs)
    state.timestamp = delta.timestamp
    return state
