from __future__ import annotations

from spice.domain.base import DomainPack
from spice.memory import DecisionContext, ReflectionContext
from spice.protocols import (
    Decision,
    ExecutionIntent,
    ExecutionResult,
    Observation,
    Outcome,
    Reflection,
    WorldState,
    apply_delta,
)

try:
    from .incident_reducers import (
        incident_snapshot,
        is_stable,
        is_stable_incident,
        observation_to_delta,
        outcome_to_delta,
    )
    from .incident_vocabulary import (
        ACTION_MONITOR,
        DEFAULT_INCIDENT_ID,
        INCIDENT_DOMAIN_NAME,
        INCIDENT_ENTITY_ID,
    )
except ImportError:
    from incident_reducers import (
        incident_snapshot,
        is_stable,
        is_stable_incident,
        observation_to_delta,
        outcome_to_delta,
    )
    from incident_vocabulary import (
        ACTION_MONITOR,
        DEFAULT_INCIDENT_ID,
        INCIDENT_DOMAIN_NAME,
        INCIDENT_ENTITY_ID,
    )


class IncidentCommanderDomainPack(DomainPack):
    """Deterministic domain pack for the incident commander demo."""

    domain_name = INCIDENT_DOMAIN_NAME

    def reduce_observation(self, state: WorldState, observation: Observation) -> WorldState:
        delta = observation_to_delta(state, observation)
        return apply_delta(state, delta)

    def reduce_outcome(self, state: WorldState, outcome: Outcome) -> WorldState:
        delta = outcome_to_delta(state, outcome)
        return apply_delta(state, delta)

    def decide(
        self,
        state: WorldState,
        *,
        decision_context: DecisionContext | None = None,
    ) -> Decision:
        """
        Minimal fallback only.

        Main demo path is expected to use injected DecisionPolicy via SpiceRuntime.
        """
        incident = incident_snapshot(state, self._incident_id(state))
        cycle_index = self._fallback_cycle_index(state)

        return Decision(
            id=f"decision.fallback.{cycle_index:03d}",
            decision_type="incident.fallback",
            status="proposed",
            selected_action=ACTION_MONITOR,
            refs=[state.id],
            attributes={
                "selected_candidate_id": f"candidate.fallback.{cycle_index:03d}",
                "reason": "domain_pack_fallback_monitor",
                "incident_id": incident["incident_id"],
                "policy_name": f"{self.domain_name}.domain_pack",
                "policy_version": "0.2",
                "all_candidates": [
                    {
                        "id": f"candidate.fallback.{cycle_index:03d}",
                        "action": ACTION_MONITOR,
                        "params": {},
                        "score_total": 1.0,
                        "score_breakdown": {"fallback": 1.0},
                        "risk": 0.0,
                        "confidence": 1.0,
                    }
                ],
                "used_compiled_context": decision_context is not None,
            },
        )

    def plan_execution(self, decision: Decision) -> ExecutionIntent:
        action = decision.selected_action or ACTION_MONITOR
        incident_id = str(decision.attributes.get("incident_id", DEFAULT_INCIDENT_ID))

        return ExecutionIntent(
            id=f"intent.{decision.id}",
            intent_type="incident.command",
            status="planned",
            objective={
                "id": f"objective.{decision.id}",
                "description": "Apply selected incident action.",
            },
            executor_type="incident-simulator",
            target={"kind": "incident", "id": incident_id},
            operation={"name": action, "mode": "sync", "dry_run": False},
            input_payload={"incident_id": incident_id},
            parameters={},
            constraints=[],
            success_criteria=[
                {
                    "id": "outcome.recorded",
                    "description": "Simulator returns an outcome record.",
                }
            ],
            failure_policy={"strategy": "fail_fast", "max_retries": 0},
            refs=[decision.id],
            provenance={"decision_id": decision.id, "domain": self.domain_name},
        )

    def interpret_execution_result(self, result: ExecutionResult) -> Outcome:
        status = "applied" if result.status == "success" else "failed"
        action = str(result.output.get("operation", ACTION_MONITOR))
        incident_id = str(result.output.get("incident_id", ""))

        return Outcome(
            id=f"outcome.{result.id}",
            outcome_type="incident.execution",
            status=status,
            decision_id="",
            changes={},
            refs=[result.id],
            attributes={
                "action": action,
                "incident_id": incident_id,
                "execution_status": result.status,
            },
        )

    def reflect(
        self,
        state: WorldState,
        outcome: Outcome,
        *,
        execution_result: ExecutionResult | None = None,
        reflection_context: ReflectionContext | None = None,
    ) -> Reflection:
        incident = incident_snapshot(state, self._incident_id(state))

        return Reflection(
            id=f"reflection.{outcome.id}",
            reflection_type="incident.reflection",
            status="recorded",
            refs=[outcome.id],
            insights={
                "summary": "Incident cycle evaluated.",
                "incident_id": incident["incident_id"],
                "last_action": incident["last_action"],
                "last_action_status": incident["last_action_status"],
                "is_stable": is_stable_incident(incident),
                "execution_status": execution_result.status if execution_result else None,
                "used_compiled_context": reflection_context is not None,
            },
            attributes={"domain": self.domain_name},
        )

    def is_stable(self, state: WorldState) -> bool:
        return is_stable(state)

    @staticmethod
    def _incident_id(state: WorldState) -> str:
        entity = state.entities.get(INCIDENT_ENTITY_ID)
        if isinstance(entity, dict):
            value = entity.get("incident_id")
            if value:
                return str(value)
        return DEFAULT_INCIDENT_ID

    @staticmethod
    def _fallback_cycle_index(state: WorldState) -> int:
        count = state.resources.get("observation_count")
        if isinstance(count, int) and count > 0:
            return count
        return 1
