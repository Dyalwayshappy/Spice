from __future__ import annotations

from typing import Any

from spice.decision import CandidateDecision, DecisionObjective, PolicyIdentity, SafetyConstraint
from spice.protocols import Decision, WorldState

try:
    from .incident_reducers import incident_snapshot, is_high_pressure, is_stable_incident
    from .incident_vocabulary import (
        ACTION_DISABLE_FEATURE_FLAG,
        ACTION_ESCALATE_HUMAN,
        ACTION_MONITOR,
        ACTION_REQUEST_HOTFIX,
        ACTION_ROLLBACK_RELEASE,
        BASELINE_POLICY_NAME,
        BASELINE_POLICY_VERSION,
        CANDIDATE_POLICY_NAME,
        CANDIDATE_POLICY_VERSION,
        DEFAULT_INCIDENT_ID,
        INCIDENT_ENTITY_ID,
    )
except ImportError:
    from incident_reducers import incident_snapshot, is_high_pressure, is_stable_incident
    from incident_vocabulary import (
        ACTION_DISABLE_FEATURE_FLAG,
        ACTION_ESCALATE_HUMAN,
        ACTION_MONITOR,
        ACTION_REQUEST_HOTFIX,
        ACTION_ROLLBACK_RELEASE,
        BASELINE_POLICY_NAME,
        BASELINE_POLICY_VERSION,
        CANDIDATE_POLICY_NAME,
        CANDIDATE_POLICY_VERSION,
        DEFAULT_INCIDENT_ID,
        INCIDENT_ENTITY_ID,
    )


class IncidentBaselinePolicy:
    """
    History-agnostic baseline policy.

    The baseline reacts only to current visible signal and does not read prior outcomes.
    """

    identity = PolicyIdentity.create(
        policy_name=BASELINE_POLICY_NAME,
        policy_version=BASELINE_POLICY_VERSION,
        implementation_fingerprint="history_agnostic_v1",
    )

    def propose(self, state: WorldState, context: Any) -> list[CandidateDecision]:
        incident = _incident_from_state(state)
        cycle_index = _cycle_index(state)
        high_pressure = is_high_pressure(incident)

        if high_pressure:
            return [
                _candidate(
                    policy_tag="baseline",
                    cycle_index=cycle_index,
                    action=ACTION_ROLLBACK_RELEASE,
                    score_total=0.94,
                    score_breakdown={"pressure_alignment": 0.94, "cost": 0.70},
                    risk=0.32,
                    confidence=0.86,
                ),
                _candidate(
                    policy_tag="baseline",
                    cycle_index=cycle_index,
                    action=ACTION_DISABLE_FEATURE_FLAG,
                    score_total=0.72,
                    score_breakdown={"pressure_alignment": 0.72, "cost": 0.58},
                    risk=0.40,
                    confidence=0.72,
                ),
                _candidate(
                    policy_tag="baseline",
                    cycle_index=cycle_index,
                    action=ACTION_ESCALATE_HUMAN,
                    score_total=0.41,
                    score_breakdown={"pressure_alignment": 0.41},
                    risk=0.22,
                    confidence=0.65,
                ),
                _candidate(
                    policy_tag="baseline",
                    cycle_index=cycle_index,
                    action=ACTION_MONITOR,
                    score_total=0.15,
                    score_breakdown={"pressure_alignment": 0.15},
                    risk=0.05,
                    confidence=0.40,
                ),
            ]

        return [
            _candidate(
                policy_tag="baseline",
                cycle_index=cycle_index,
                action=ACTION_MONITOR,
                score_total=0.92,
                score_breakdown={"stability_alignment": 0.92},
                risk=0.05,
                confidence=0.82,
            ),
            _candidate(
                policy_tag="baseline",
                cycle_index=cycle_index,
                action=ACTION_REQUEST_HOTFIX,
                score_total=0.20,
                score_breakdown={"stability_alignment": 0.20},
                risk=0.18,
                confidence=0.52,
            ),
        ]

    def select(
        self,
        candidates: list[CandidateDecision],
        objective: DecisionObjective,
        constraints: list[SafetyConstraint],
    ) -> Decision:
        selected = _select_candidate(candidates, objective)
        return _to_decision(
            policy_identity=self.identity,
            decision_kind="baseline",
            selected=selected,
            candidates=candidates,
            objective=objective,
            constraints=constraints,
        )


class IncidentContextAwarePolicy:
    """
    Context-aware policy over visible state/history.

    Required behavior:
    1. Under the same high-pressure signal, switch away from rollback after rollback failure.
    2. Add one proactive post-stabilization hotfix request.
    """

    identity = PolicyIdentity.create(
        policy_name=CANDIDATE_POLICY_NAME,
        policy_version=CANDIDATE_POLICY_VERSION,
        implementation_fingerprint="context_aware_v1",
    )

    def propose(self, state: WorldState, context: Any) -> list[CandidateDecision]:
        incident = _incident_from_state(state)
        cycle_index = _cycle_index(state)

        high_pressure = is_high_pressure(incident)
        stable = is_stable_incident(incident)
        failed_actions = set(_as_str_list(incident.get("failed_actions")))
        successful_actions = set(_as_str_list(incident.get("successful_actions")))

        rollback_failed = ACTION_ROLLBACK_RELEASE in failed_actions
        hotfix_attempted = (
            ACTION_REQUEST_HOTFIX in failed_actions
            or ACTION_REQUEST_HOTFIX in successful_actions
            or bool(incident.get("hotfix_requested", False))
        )

        if stable and not hotfix_attempted:
            return [
                _candidate(
                    policy_tag="candidate",
                    cycle_index=cycle_index,
                    action=ACTION_REQUEST_HOTFIX,
                    score_total=0.96,
                    score_breakdown={"proactive_followup": 0.96, "cost": 0.70},
                    risk=0.16,
                    confidence=0.90,
                ),
                _candidate(
                    policy_tag="candidate",
                    cycle_index=cycle_index,
                    action=ACTION_MONITOR,
                    score_total=0.80,
                    score_breakdown={"stability_alignment": 0.80},
                    risk=0.05,
                    confidence=0.78,
                ),
            ]

        if high_pressure and rollback_failed:
            return [
                _candidate(
                    policy_tag="candidate",
                    cycle_index=cycle_index,
                    action=ACTION_DISABLE_FEATURE_FLAG,
                    score_total=0.95,
                    score_breakdown={"history_adaptation": 0.95, "pressure_alignment": 0.90},
                    risk=0.38,
                    confidence=0.88,
                ),
                _candidate(
                    policy_tag="candidate",
                    cycle_index=cycle_index,
                    action=ACTION_ESCALATE_HUMAN,
                    score_total=0.62,
                    score_breakdown={"history_adaptation": 0.62},
                    risk=0.20,
                    confidence=0.74,
                ),
                _candidate(
                    policy_tag="candidate",
                    cycle_index=cycle_index,
                    action=ACTION_ROLLBACK_RELEASE,
                    score_total=0.18,
                    score_breakdown={"history_adaptation": 0.18},
                    risk=0.34,
                    confidence=0.40,
                ),
            ]

        if high_pressure:
            return [
                _candidate(
                    policy_tag="candidate",
                    cycle_index=cycle_index,
                    action=ACTION_ROLLBACK_RELEASE,
                    score_total=0.90,
                    score_breakdown={"pressure_alignment": 0.90},
                    risk=0.34,
                    confidence=0.82,
                ),
                _candidate(
                    policy_tag="candidate",
                    cycle_index=cycle_index,
                    action=ACTION_DISABLE_FEATURE_FLAG,
                    score_total=0.74,
                    score_breakdown={"pressure_alignment": 0.74},
                    risk=0.40,
                    confidence=0.72,
                ),
                _candidate(
                    policy_tag="candidate",
                    cycle_index=cycle_index,
                    action=ACTION_MONITOR,
                    score_total=0.14,
                    score_breakdown={"pressure_alignment": 0.14},
                    risk=0.06,
                    confidence=0.40,
                ),
            ]

        return [
            _candidate(
                policy_tag="candidate",
                cycle_index=cycle_index,
                action=ACTION_MONITOR,
                score_total=0.88,
                score_breakdown={"stability_alignment": 0.88},
                risk=0.05,
                confidence=0.80,
            ),
            _candidate(
                policy_tag="candidate",
                cycle_index=cycle_index,
                action=ACTION_REQUEST_HOTFIX,
                score_total=0.22,
                score_breakdown={"stability_alignment": 0.22},
                risk=0.16,
                confidence=0.52,
            ),
        ]

    def select(
        self,
        candidates: list[CandidateDecision],
        objective: DecisionObjective,
        constraints: list[SafetyConstraint],
    ) -> Decision:
        selected = _select_candidate(candidates, objective)
        return _to_decision(
            policy_identity=self.identity,
            decision_kind="candidate",
            selected=selected,
            candidates=candidates,
            objective=objective,
            constraints=constraints,
        )


def _incident_from_state(state: WorldState) -> dict[str, Any]:
    entity = state.entities.get(INCIDENT_ENTITY_ID)
    incident_id = DEFAULT_INCIDENT_ID
    if isinstance(entity, dict):
        value = entity.get("incident_id")
        if value:
            incident_id = str(value)
    return incident_snapshot(state, incident_id)


def _cycle_index(state: WorldState) -> int:
    value = state.resources.get("observation_count")
    if isinstance(value, int) and value > 0:
        return value
    return len(state.recent_outcomes) + 1


def _candidate(
    *,
    policy_tag: str,
    cycle_index: int,
    action: str,
    score_total: float,
    score_breakdown: dict[str, float],
    risk: float,
    confidence: float,
) -> CandidateDecision:
    slug = action.replace(".", "_")
    return CandidateDecision(
        id=f"candidate.{policy_tag}.{cycle_index:03d}.{slug}",
        action=action,
        params={},
        score_total=float(score_total),
        score_breakdown={str(k): float(v) for k, v in score_breakdown.items()},
        risk=float(risk),
        confidence=float(confidence),
    )


def _select_candidate(
    candidates: list[CandidateDecision],
    objective: DecisionObjective,
) -> CandidateDecision:
    if not candidates:
        raise ValueError("At least one candidate is required for selection.")

    eligible = [
        candidate
        for candidate in candidates
        if candidate.risk <= float(objective.risk_budget)
    ]
    return max(eligible or candidates, key=lambda candidate: candidate.score_total)


def _to_decision(
    *,
    policy_identity: PolicyIdentity,
    decision_kind: str,
    selected: CandidateDecision,
    candidates: list[CandidateDecision],
    objective: DecisionObjective,
    constraints: list[SafetyConstraint],
) -> Decision:
    return Decision(
        id=f"decision.{decision_kind}.{selected.id}",
        decision_type=f"incident.{decision_kind}.policy_decision",
        status="proposed",
        selected_action=selected.action,
        attributes={
            "selected_candidate_id": selected.id,
            "all_candidates": [_candidate_payload(candidate) for candidate in candidates],
            "objective_used": _objective_payload(objective),
            "constraints_used": [_constraint_payload(constraint) for constraint in constraints],
            "policy_name": policy_identity.policy_name,
            "policy_version": policy_identity.policy_version,
            "policy_hash": policy_identity.resolved_hash(),
        },
    )


def _candidate_payload(candidate: CandidateDecision) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "action": candidate.action,
        "params": dict(candidate.params),
        "score_total": float(candidate.score_total),
        "score_breakdown": {str(k): float(v) for k, v in candidate.score_breakdown.items()},
        "risk": float(candidate.risk),
        "confidence": float(candidate.confidence),
    }


def _objective_payload(objective: DecisionObjective) -> dict[str, float]:
    return {
        "stability_weight": float(objective.stability_weight),
        "latency_weight": float(objective.latency_weight),
        "cost_weight": float(objective.cost_weight),
        "risk_budget": float(objective.risk_budget),
    }


def _constraint_payload(constraint: SafetyConstraint) -> dict[str, Any]:
    return {
        "name": constraint.name,
        "kind": constraint.kind,
        "params": dict(constraint.params),
    }


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
