from __future__ import annotations

from typing import Any
from uuid import uuid4

from spice.protocols import Decision, DeltaOp, ExecutionIntent, ExecutionResult, Observation, Outcome, Reflection, WorldDelta, WorldState

from spice.domain_starter.vocabulary import OPERATION_KINDS


def observation_to_delta(state: WorldState, observation: Observation) -> WorldDelta:
    """Minimal example reducer: Observation -> WorldDelta."""
    return WorldDelta(
        id=f"delta-{uuid4().hex}",
        source_kind="observation",
        source_id=observation.id,
        signal_ops=[
            DeltaOp(
                op="upsert",
                id=f"signal-{observation.id}",
                value={
                    "type": observation.observation_type,
                    "source": observation.source,
                    "attributes": observation.attributes,
                    "observation_id": observation.id,
                },
            )
        ],
        resource_patch={
            "observation_count": state.resources.get("observation_count", 0) + 1,
        },
        provenance_patch={
            "last_observation_id": observation.id,
            "last_observation_source": observation.source,
        },
    )


def outcome_to_delta(outcome: Outcome) -> WorldDelta:
    """Minimal example reducer: Outcome -> WorldDelta."""
    entity_ops = [
        DeltaOp(op="upsert", id=entity_id, value=entity_value)
        for entity_id, entity_value in outcome.changes.items()
    ]
    return WorldDelta(
        id=f"delta-{uuid4().hex}",
        source_kind="outcome",
        source_id=outcome.id,
        entity_ops=entity_ops,
        provenance_patch={"last_outcome_id": outcome.id},
        confidence_patch={"latest_outcome_status": outcome.status},
        recent_outcome_additions=[
            {
                "outcome_id": outcome.id,
                "status": outcome.status,
                "changes": outcome.changes,
            }
        ],
    )


def build_default_decision(state: WorldState) -> Decision:
    """Minimal deterministic decision placeholder."""
    return Decision(
        id=f"dec-{uuid4().hex}",
        decision_type="starter.placeholder",
        status="proposed",
        selected_action=OPERATION_KINDS[0] if OPERATION_KINDS else "starter.noop_action",
        refs=[state.id],
        attributes={"reason": "domain_starter_default_decision"},
    )


def build_execution_intent(decision: Decision) -> ExecutionIntent:
    """Minimal deterministic intent placeholder."""
    operation_name = decision.selected_action or "starter.noop_action"
    return ExecutionIntent(
        id=f"intent-{uuid4().hex}",
        intent_type="starter.placeholder",
        status="planned",
        objective={
            "id": f"objective-{decision.id}",
            "description": "Starter objective placeholder.",
        },
        executor_type="agent",
        target={"kind": "starter_system"},
        operation={"name": operation_name, "mode": "sync", "dry_run": False},
        input_payload={"decision_id": decision.id, "selected_action": operation_name},
        parameters={},
        constraints=[],
        success_criteria=[{"id": "starter.success", "description": "Operation returns success status."}],
        failure_policy={"strategy": "retry", "max_retries": 1},
        refs=[decision.id],
        provenance={"decision_id": decision.id, "domain": "starter"},
    )


def build_outcome_from_result(result: ExecutionResult) -> Outcome:
    """Minimal deterministic outcome placeholder."""
    return Outcome(
        id=f"out-{uuid4().hex}",
        outcome_type="starter.placeholder",
        status="applied",
        changes={},
        refs=[result.id],
        attributes={"execution_status": result.status},
    )


def build_reflection(
    outcome: Outcome,
    *,
    execution_result: ExecutionResult | None = None,
    simulation_artifact: dict[str, Any] | None = None,
) -> Reflection:
    """Minimal deterministic reflection placeholder."""
    insights: dict[str, Any] = {"summary": "Starter reflection placeholder."}
    if execution_result is not None:
        insights["execution_status"] = execution_result.status
    if simulation_artifact:
        insights["simulation"] = simulation_artifact

    return Reflection(
        id=f"ref-{uuid4().hex}",
        reflection_type="starter.placeholder",
        status="recorded",
        refs=[outcome.id],
        insights=insights,
    )
