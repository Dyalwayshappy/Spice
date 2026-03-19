from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from spice.domain.base import DomainPack
from spice.memory import DecisionContext, ReflectionContext, SimulationContext
from spice.protocols import Decision, ExecutionIntent, ExecutionResult, Observation, Outcome, Reflection, WorldState, apply_delta

from spice.domain_starter import reducers


class StarterDomainPack(DomainPack):
    """
    Domain Starter v0.1 reference scaffold.

    Copy this class and customize reducers + vocabulary for your domain.
    """

    domain_name = "starter"

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
                    context={"domain": self.domain_name, "stage": "reduce_observation"},
                )
                if isinstance(candidate, Observation):
                    normalized_observation = candidate
            except Exception:
                normalized_observation = observation

        delta = reducers.observation_to_delta(state, normalized_observation)
        return apply_delta(state, delta)

    def reduce_outcome(self, state: WorldState, outcome: Outcome) -> WorldState:
        delta = reducers.outcome_to_delta(outcome)
        return apply_delta(state, delta)

    def decide(
        self,
        state: WorldState,
        *,
        decision_context: DecisionContext | None = None,
    ) -> Decision:
        if self.decision_model is not None:
            state_for_model = self._state_for_model(state, has_compiled_context=decision_context is not None)
            model_context: dict[str, Any] = {"domain": self.domain_name, "stage": "decide"}
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

        return reducers.build_default_decision(state)

    def plan_execution(self, decision: Decision) -> ExecutionIntent:
        return reducers.build_execution_intent(decision)

    def interpret_execution_result(self, result: ExecutionResult) -> Outcome:
        return reducers.build_outcome_from_result(result)

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
            model_context: dict[str, Any] = {"domain": self.domain_name, "stage": "reflect"}
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
                pass

        simulation_artifact = None
        if execution_result is not None:
            simulation_artifact = execution_result.attributes.get("simulation")
        return reducers.build_reflection(
            outcome,
            execution_result=execution_result,
            simulation_artifact=simulation_artifact,
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

        state_for_model = self._state_for_model(state, has_compiled_context=simulation_context is not None)
        best_candidate = candidates[0]
        best_score = float("-inf")
        best_artifact: dict[str, Any] = {}
        for candidate in candidates:
            model_context: dict[str, Any] = {"domain": self.domain_name, "stage": "decision_simulation"}
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

    @staticmethod
    def _normalize_decision(decision: Decision, state: WorldState) -> Decision:
        if not decision.id:
            decision.id = f"dec-{uuid4().hex}"
        if not decision.decision_type:
            decision.decision_type = "starter.placeholder"
        if state.id not in decision.refs:
            decision.refs.append(state.id)
        if decision.selected_action is None:
            decision.selected_action = "starter.noop_action"
        return decision

    @staticmethod
    def _state_for_model(state: WorldState, *, has_compiled_context: bool) -> WorldState:
        if not has_compiled_context:
            return state

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
