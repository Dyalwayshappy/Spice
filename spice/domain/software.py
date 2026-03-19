from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from spice.domain.base import DomainPack
from spice.memory import DecisionContext, ReflectionContext, SimulationContext
from spice.protocols import (
    Decision,
    DeltaOp,
    ExecutionIntent,
    ExecutionResult,
    Observation,
    Outcome,
    Reflection,
    WorldDelta,
    WorldState,
    apply_delta,
)


class SoftwareDomainPack(DomainPack):
    """Minimal placeholder domain pack for software-oriented environments."""
    domain_name = "software"

    def reduce_observation(self, state: WorldState, observation: Observation) -> WorldState:
        normalized_observation = observation
        if self.perception_model is not None:
            try:
                candidate = self.perception_model.interpret(
                    {
                        "id": observation.id,
                        "observation_type": observation.observation_type,
                        "source": observation.source,
                        "attributes": observation.attributes,
                        "metadata": observation.metadata,
                    },
                    context={"domain": "software", "stage": "reduce_observation"},
                )
                if isinstance(candidate, Observation):
                    normalized_observation = candidate
            except Exception:
                # Fall back to deterministic behavior if model invocation fails.
                normalized_observation = observation

        delta = self._delta_from_observation(state, normalized_observation)
        return apply_delta(state, delta)

    def reduce_outcome(self, state: WorldState, outcome: Outcome) -> WorldState:
        delta = self._delta_from_outcome(state, outcome)
        return apply_delta(state, delta)

    def decide(
        self,
        state: WorldState,
        *,
        decision_context: DecisionContext | None = None,
    ) -> Decision:
        if self.decision_model is not None:
            state_for_model = self._state_for_model(state, has_compiled_context=decision_context is not None)
            model_context: dict[str, Any] = {"domain": "software", "stage": "decide"}
            if decision_context is not None:
                model_context["compiled_context"] = asdict(decision_context)
            try:
                candidates = self.decision_model.propose(
                    state_for_model,
                    context=model_context,
                    max_candidates=3,
                )
            except Exception:
                candidates = []

            valid_candidates = [candidate for candidate in candidates if isinstance(candidate, Decision)]
            if valid_candidates:
                return self._select_decision(
                    state,
                    valid_candidates,
                    decision_context=decision_context,
                )

        return Decision(
            id=self._next_id("dec"),
            decision_type="software.placeholder",
            status="proposed",
            selected_action="noop_software_action",
            refs=[state.id],
            attributes={"reason": "software_domain_placeholder"},
        )

    def plan_execution(self, decision: Decision) -> ExecutionIntent:
        operation_name = decision.selected_action or "noop_software_action"
        return ExecutionIntent(
            id=self._next_id("intent"),
            intent_type="software.placeholder",
            status="planned",
            objective={
                "id": f"objective-{decision.id}",
                "description": "Stabilize software runtime state.",
                "priority": "medium",
                "horizon": "immediate",
            },
            executor_type="agent",
            target={"kind": "software_system"},
            operation={
                "name": operation_name,
                "mode": "sync",
                "dry_run": False,
            },
            input_payload={
                "decision_id": decision.id,
                "decision_type": decision.decision_type,
                "selected_action": operation_name,
            },
            parameters={},
            constraints=[],
            success_criteria=[
                {"id": "exec.completed", "description": "Operation reported success."}
            ],
            failure_policy={"strategy": "retry", "max_retries": 1},
            refs=[decision.id],
            provenance={"decision_id": decision.id, "domain": "software"},
        )

    def interpret_execution_result(self, result: ExecutionResult) -> Outcome:
        return Outcome(
            id=self._next_id("out"),
            outcome_type="software.placeholder",
            status="applied",
            changes={},
            refs=[result.id],
            attributes={"execution_status": result.status},
        )

    def reflect(
        self,
        state: WorldState,
        outcome: Outcome,
        *,
        execution_result: ExecutionResult | None = None,
        reflection_context: ReflectionContext | None = None,
    ) -> Reflection:
        if self.reflection_model is not None:
            state_for_model = self._state_for_model(state, has_compiled_context=reflection_context is not None)
            model_context: dict[str, Any] = {"domain": "software", "stage": "reflect"}
            if reflection_context is not None:
                model_context["compiled_context"] = asdict(reflection_context)
            try:
                proposal = self.reflection_model.synthesize(
                    state_for_model,
                    outcome,
                    execution_result=execution_result,
                    context=model_context,
                )
                if isinstance(proposal, Reflection):
                    if outcome.id not in proposal.refs:
                        proposal.refs.append(outcome.id)
                    return proposal
            except Exception:
                # Fall back to deterministic behavior if model invocation fails.
                pass

        return Reflection(
            id=self._next_id("ref"),
            reflection_type="software.placeholder",
            status="recorded",
            refs=[outcome.id],
            insights={"summary": "Cycle completed with placeholder logic."},
        )

    def _delta_from_observation(self, state: WorldState, observation: Observation) -> WorldDelta:
        observation_count = state.resources.get("observation_count", 0) + 1
        active_intent_ops: list[DeltaOp] = []
        if observation.observation_type == "software.build_failure":
            active_intent_ops.append(
                DeltaOp(
                    op="upsert",
                    id="intent-software-remediation",
                    value={
                        "status": "pending_execution",
                        "reason": "build_failure_detected",
                        "observation_id": observation.id,
                    },
                )
            )

        return WorldDelta(
            id=self._next_id("delta"),
            source_kind="observation",
            source_id=observation.id,
            goal_ops=[
                DeltaOp(
                    op="upsert",
                    id="software.stability",
                    value={"status": "active"},
                )
            ],
            active_intent_ops=active_intent_ops,
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
            resource_patch={"observation_count": observation_count},
            provenance_patch={
                "last_observation_id": observation.id,
                "last_observation_source": observation.source,
            },
            domain_patch={
                "software": {
                    "last_observation": {
                        "id": observation.id,
                        "type": observation.observation_type,
                    },
                }
            },
        )

    def _delta_from_outcome(self, state: WorldState, outcome: Outcome) -> WorldDelta:
        entity_ops = [
            DeltaOp(op="upsert", id=entity_id, value=entity_value)
            for entity_id, entity_value in outcome.changes.items()
        ]
        return WorldDelta(
            id=self._next_id("delta"),
            source_kind="outcome",
            source_id=outcome.id,
            entity_ops=entity_ops,
            active_intent_ops=[
                DeltaOp(op="remove", id="intent-software-remediation")
            ],
            provenance_patch={"last_outcome_id": outcome.id},
            confidence_patch={"latest_outcome_status": outcome.status},
            recent_outcome_additions=[
                {
                    "outcome_id": outcome.id,
                    "status": outcome.status,
                    "changes": outcome.changes,
                }
            ],
            domain_patch={
                "software": {
                    "last_outcome": {
                        "id": outcome.id,
                        "status": outcome.status,
                    }
                }
            },
        )

    def _select_decision(
        self,
        state: WorldState,
        candidates: list[Decision],
        *,
        decision_context: DecisionContext | None = None,
    ) -> Decision:
        if self.simulation_model is None:
            return self._normalize_decision(candidates[0], state)

        simulation_context: SimulationContext | None = None
        if self.context_compiler is not None:
            try:
                simulation_context = self.context_compiler.compile_simulation_context(
                    state,
                    domain=self.domain_name,
                    candidate_decisions=candidates,
                )
            except Exception:
                simulation_context = None

        state_for_model = self._state_for_model(
            state,
            has_compiled_context=simulation_context is not None,
        )
        best_candidate = candidates[0]
        best_score = float("-inf")
        best_artifact: dict[str, Any] = {}
        for candidate in candidates:
            model_context: dict[str, Any] = {"domain": "software", "stage": "decision_simulation"}
            if decision_context is not None:
                model_context["decision_context"] = asdict(decision_context)
            if simulation_context is not None:
                model_context["compiled_context"] = asdict(simulation_context)
            try:
                artifact = self.simulation_model.simulate(
                    state_for_model,
                    decision=candidate,
                    context=model_context,
                )
            except Exception:
                artifact = {}

            score_raw = artifact.get("score", 0.0) if isinstance(artifact, dict) else 0.0
            score = float(score_raw) if isinstance(score_raw, (int, float)) else 0.0
            if score > best_score:
                best_score = score
                best_candidate = candidate
                best_artifact = artifact if isinstance(artifact, dict) else {}

        normalized = self._normalize_decision(best_candidate, state)
        if best_artifact:
            normalized.metadata["simulation"] = best_artifact
        return normalized

    def _normalize_decision(self, decision: Decision, state: WorldState) -> Decision:
        if not decision.id:
            decision.id = self._next_id("dec")
        if not decision.decision_type:
            decision.decision_type = "software.placeholder"
        if state.id not in decision.refs:
            decision.refs.append(state.id)
        if decision.selected_action is None:
            decision.selected_action = "noop_software_action"
        return decision

    @staticmethod
    def _state_for_model(state: WorldState, *, has_compiled_context: bool) -> WorldState:
        if not has_compiled_context:
            return state

        # Provide a minimal state envelope when compiled context is available.
        return WorldState(
            id=state.id,
            timestamp=state.timestamp,
            refs=list(state.refs),
            metadata=dict(state.metadata),
            schema_version=state.schema_version,
            status=state.status,
            confidence=dict(state.confidence),
            provenance=dict(state.provenance),
        )

    @staticmethod
    def _next_id(prefix: str) -> str:
        return f"{prefix}-{uuid4().hex}"
