from __future__ import annotations

from typing import Any

from spice.memory.base import MemoryProvider
from spice.memory.episode import EpisodePolicyIdentity, EpisodeRecord, serialize_record
from spice.protocols import (
    Decision,
    ExecutionIntent,
    ExecutionResult,
    Observation,
    Outcome,
    Reflection,
    WorldState,
)


class EpisodeWriter:
    """Helper for writing canonical episodic records through MemoryProvider."""

    def __init__(
        self,
        provider: MemoryProvider,
        *,
        include_execution_traces: bool = False,
    ) -> None:
        self.provider = provider
        self.include_execution_traces = include_execution_traces

    def write(
        self,
        episode: EpisodeRecord,
        *,
        namespace: str | None = None,
    ) -> list[str]:
        episode.validate()
        active_namespace = namespace or f"{episode.domain}.episode"
        # Keep canonical episode.refs shape untouched. Some providers merge `refs`
        # as list metadata, which would collide with the episode refs object.
        return self.provider.write(
            [episode.to_dict()],
            namespace=active_namespace,
        )


def build_episode_record(
    *,
    domain: str,
    cycle_index: int,
    world_state_before: WorldState,
    world_state_after: WorldState,
    observation: Observation,
    decision: Decision,
    decision_trace: Any,
    execution_intent: ExecutionIntent,
    execution_result: ExecutionResult,
    outcome: Outcome,
    reflection: Reflection,
    include_execution_traces: bool = False,
    metadata: dict[str, Any] | None = None,
) -> EpisodeRecord:
    if not domain:
        raise ValueError("domain is required for episode construction.")
    if cycle_index <= 0:
        raise ValueError("cycle_index must be > 0 for episode construction.")

    decision_trace_payload = serialize_record(decision_trace)
    policy = _policy_identity(decision_trace_payload, decision)
    execution_result_payload, artifacts = _canonical_execution_result(
        execution_result,
        include_execution_traces=include_execution_traces,
    )

    refs = {
        "observation_id": observation.id,
        "decision_id": decision.id,
        "decision_trace_id": str(decision_trace_payload.get("id", "")),
        "execution_intent_id": execution_intent.id,
        "execution_result_id": execution_result.id,
        "outcome_id": outcome.id,
        "reflection_id": reflection.id,
        "world_state_before_id": world_state_before.id,
        "world_state_after_id": world_state_after.id,
    }

    records = {
        "observation": serialize_record(observation),
        "decision": serialize_record(decision),
        "decision_trace": decision_trace_payload,
        "execution_intent": serialize_record(execution_intent),
        "execution_result": execution_result_payload,
        "outcome": serialize_record(outcome),
        "reflection": serialize_record(reflection),
    }

    timestamps = {
        "cycle_started_at": observation.timestamp.isoformat(),
        "cycle_completed_at": reflection.timestamp.isoformat(),
        "observation_at": observation.timestamp.isoformat(),
        "decision_at": decision.timestamp.isoformat(),
        "execution_intent_at": execution_intent.timestamp.isoformat(),
        "execution_result_at": execution_result.timestamp.isoformat(),
        "outcome_at": outcome.timestamp.isoformat(),
        "reflection_at": reflection.timestamp.isoformat(),
    }

    return EpisodeRecord(
        episode_id=f"episode.{decision.id}",
        domain=domain,
        cycle_index=cycle_index,
        policy=policy,
        refs=refs,
        records=records,
        timestamps=timestamps,
        state={
            "before": _state_summary(world_state_before),
            "after": _state_summary(world_state_after),
        },
        artifacts=artifacts,
        metadata=dict(metadata or {}),
    )


def _policy_identity(decision_trace: dict[str, Any], decision: Decision) -> EpisodePolicyIdentity:
    policy_name = str(
        decision_trace.get("policy_name")
        or decision.attributes.get("policy_name")
        or "unknown.policy"
    )
    policy_version = str(
        decision_trace.get("policy_version")
        or decision.attributes.get("policy_version")
        or "0.1"
    )
    policy_hash = str(
        decision_trace.get("policy_hash")
        or decision.attributes.get("policy_hash")
        or "unknown"
    )
    return EpisodePolicyIdentity(
        policy_name=policy_name,
        policy_version=policy_version,
        policy_hash=policy_hash,
    )


def _canonical_execution_result(
    execution_result: ExecutionResult,
    *,
    include_execution_traces: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = serialize_record(execution_result)
    artifacts: dict[str, Any] = {}

    attributes = payload.pop("attributes", {})
    if isinstance(attributes, dict):
        payload["attributes_keys"] = sorted(attributes.keys())
        if include_execution_traces and attributes:
            artifacts["execution_result_attributes"] = dict(attributes)
    else:
        payload["attributes_keys"] = []

    return payload, artifacts


def _state_summary(state: WorldState) -> dict[str, Any]:
    return {
        "id": state.id,
        "timestamp": state.timestamp.isoformat(),
        "resources": dict(state.resources),
        "confidence": dict(state.confidence),
        "provenance": dict(state.provenance),
        "counts": {
            "entities": len(state.entities),
            "relations": len(state.relations),
            "goals": len(state.goals),
            "constraints": len(state.constraints),
            "signals": len(state.signals),
            "risks": len(state.risks),
            "active_intents": len(state.active_intents),
            "recent_outcomes": len(state.recent_outcomes),
        },
    }
