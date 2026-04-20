from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from spice.llm.simulation import SimulationModel
from spice.protocols.decision import Decision

from examples.decision_hub_demo.candidates import CandidateRecord
from examples.decision_hub_demo.context import ActiveDecisionContext


RISK_LEVELS = {"low", "medium", "high"}
RISK_CHANGES = {"reduced", "unchanged", "increased"}
ORDINAL_LEVELS = {"none", "low", "medium", "high"}


@dataclass(slots=True)
class ConsequenceEstimate:
    candidate_id: str
    action_type: str
    expected_time_cost_minutes: int
    commitment_risk: str
    work_item_risk_change: str
    reversibility: str
    attention_cost: str
    followup_needed: bool
    followup_summary: str
    executor_load: str = "none"
    requires_confirmation: bool = False
    confidence: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class StructuredSimulationRunner:
    """Runs bounded candidate consequence estimation.

    Optional LLM output is treated as a structured proposal only. The runner
    validates the proposal and falls back to deterministic estimates if the
    model fails, emits invalid schema, or attempts to recommend an action.
    """

    def __init__(self, model: SimulationModel | None = None) -> None:
        self.model = model

    def simulate(
        self,
        context: ActiveDecisionContext,
        candidate: CandidateRecord,
    ) -> ConsequenceEstimate:
        if self.model is None:
            return fallback_consequence(context, candidate, reason="no_simulation_model")

        seed = Decision(
            id=f"simulation.seed.{candidate.candidate_id}",
            decision_type="candidate_consequence_seed",
            selected_action=candidate.action_type,
            attributes={"candidate": candidate.to_payload()},
        )
        try:
            proposal = self.model.simulate(
                state=None,
                decision=seed,
                context={
                    "active_decision_context": context.to_payload(),
                    "candidate": candidate.to_payload(),
                    "instruction": (
                        "Return only a structured consequence estimate. "
                        "Do not return a recommendation or new candidate actions."
                    ),
                },
            )
        except Exception as exc:  # pragma: no cover - exact provider failures vary
            return fallback_consequence(
                context,
                candidate,
                reason="simulation_model_failed",
                issue=str(exc),
            )

        try:
            return consequence_from_proposal(proposal, candidate)
        except ValueError as exc:
            return fallback_consequence(
                context,
                candidate,
                reason="invalid_simulation_proposal",
                issue=str(exc),
            )


def consequence_from_proposal(
    proposal: dict[str, Any],
    candidate: CandidateRecord,
) -> ConsequenceEstimate:
    if not isinstance(proposal, dict):
        raise ValueError("proposal must be a dict")
    forbidden = {"recommendation", "selected_action", "best_option", "new_candidate", "candidate_actions"}
    present = sorted(_forbidden_keys_present(proposal, forbidden))
    if present:
        raise ValueError("simulation proposal attempted selection: " + ", ".join(present))

    raw_payload = proposal.get("consequence", proposal)
    if not isinstance(raw_payload, dict):
        raise ValueError("simulation consequence must be a dict")
    nested_present = sorted(_forbidden_keys_present(raw_payload, forbidden))
    if nested_present:
        raise ValueError("simulation consequence attempted selection: " + ", ".join(nested_present))
    payload = dict(raw_payload)
    payload.setdefault("candidate_id", candidate.candidate_id)
    payload.setdefault("action_type", candidate.action_type)
    if payload["candidate_id"] != candidate.candidate_id:
        raise ValueError("candidate_id does not match simulated candidate")
    if payload["action_type"] != candidate.action_type:
        raise ValueError("action_type does not match simulated candidate")

    estimate = ConsequenceEstimate(
        candidate_id=str(payload["candidate_id"]),
        action_type=str(payload["action_type"]),
        expected_time_cost_minutes=_int(payload.get("expected_time_cost_minutes"), "expected_time_cost_minutes"),
        commitment_risk=_member(payload.get("commitment_risk"), RISK_LEVELS, "commitment_risk"),
        work_item_risk_change=_member(payload.get("work_item_risk_change"), RISK_CHANGES, "work_item_risk_change"),
        reversibility=_member(payload.get("reversibility"), ORDINAL_LEVELS - {"none"}, "reversibility"),
        attention_cost=_member(payload.get("attention_cost"), ORDINAL_LEVELS, "attention_cost"),
        followup_needed=bool(payload.get("followup_needed", False)),
        followup_summary=str(payload.get("followup_summary", "")),
        executor_load=_member(payload.get("executor_load", "none"), ORDINAL_LEVELS, "executor_load"),
        requires_confirmation=bool(payload.get("requires_confirmation", candidate.requires_confirmation)),
        confidence=_confidence(payload.get("confidence")),
        assumptions=[str(item) for item in payload.get("assumptions", [])],
        metadata=dict(payload.get("metadata", {})) if isinstance(payload.get("metadata", {}), dict) else {},
    )
    estimate.metadata.setdefault("simulation_source", "llm")
    estimate.metadata.setdefault("llm_recommendation_allowed", False)
    return estimate


def _forbidden_keys_present(value: Any, forbidden: set[str]) -> set[str]:
    if isinstance(value, dict):
        found = set(forbidden.intersection(value))
        for child in value.values():
            found.update(_forbidden_keys_present(child, forbidden))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found.update(_forbidden_keys_present(child, forbidden))
        return found
    return set()


def fallback_consequence(
    context: ActiveDecisionContext,
    candidate: CandidateRecord,
    *,
    reason: str,
    issue: str = "",
) -> ConsequenceEstimate:
    estimated_work = _target_estimated_minutes(context)
    available = context.available_window_minutes
    action = candidate.action_type

    if action == "handle_now":
        commitment_risk = "high" if estimated_work > available else "medium"
        estimate = ConsequenceEstimate(
            candidate_id=candidate.candidate_id,
            action_type=action,
            expected_time_cost_minutes=estimated_work,
            commitment_risk=commitment_risk,
            work_item_risk_change="reduced",
            reversibility="medium",
            attention_cost="high",
            followup_needed=False,
            followup_summary="Immediate handling may close or materially advance the work item.",
            confidence=0.72,
            assumptions=["deterministic fallback estimate"],
        )
    elif action == "quick_triage_then_defer":
        estimate = ConsequenceEstimate(
            candidate_id=candidate.candidate_id,
            action_type=action,
            expected_time_cost_minutes=min(5, max(1, available)),
            commitment_risk="low",
            work_item_risk_change="reduced",
            reversibility="high",
            attention_cost="low",
            followup_needed=True,
            followup_summary="Full handling remains after the fixed commitment.",
            confidence=0.78,
            assumptions=["triage can reduce uncertainty without full execution"],
        )
    elif action == "ignore_temporarily":
        estimate = ConsequenceEstimate(
            candidate_id=candidate.candidate_id,
            action_type=action,
            expected_time_cost_minutes=0,
            commitment_risk="low",
            work_item_risk_change="increased" if context.open_work_items else "unchanged",
            reversibility="high",
            attention_cost="none",
            followup_needed=True,
            followup_summary="The work item remains open with no status change.",
            confidence=0.62,
            assumptions=["temporary ignore preserves time but may increase work-item risk"],
        )
    elif action == "delegate_to_executor":
        capability = _candidate_executor_capability(context, candidate)
        executor_available = bool(capability and capability.get("availability") == "available")
        default_budget = _positive_int(capability.get("default_time_budget_minutes") if capability else None, 10)
        requires_confirmation = bool(
            capability.get("requires_confirmation")
            if capability
            else candidate.requires_confirmation
        )
        reversible = bool(capability.get("reversible")) if capability else False
        estimate = ConsequenceEstimate(
            candidate_id=candidate.candidate_id,
            action_type=action,
            expected_time_cost_minutes=default_budget,
            commitment_risk="low",
            work_item_risk_change="reduced" if executor_available else "unchanged",
            reversibility="high" if reversible else "medium",
            attention_cost="low",
            followup_needed=True,
            followup_summary="Executor result should be checked after delegation.",
            executor_load="medium",
            requires_confirmation=requires_confirmation,
            confidence=0.76 if executor_available else 0.45,
            assumptions=[
                "executor availability comes from executor_capability_observed state",
                "executor failure would leave the work item open",
            ],
            metadata={
                "executor_available": executor_available,
                "capability_id": capability.get("capability_id") if capability else None,
                "executor": capability.get("executor") if capability else None,
                "supported_scopes": list(capability.get("supported_scopes", []) or []) if capability else [],
                "required_scope": candidate.params.get("required_scope"),
                "requires_confirmation": requires_confirmation,
                "availability": capability.get("availability") if capability else "missing",
                "default_time_budget_minutes": default_budget,
                "estimated_executor_latency_minutes": 30,
                "delegation_reversible": reversible,
                "failure_risk_change": "increased_if_unmonitored",
            },
        )
    elif action == "ask_user":
        estimate = ConsequenceEstimate(
            candidate_id=candidate.candidate_id,
            action_type=action,
            expected_time_cost_minutes=2,
            commitment_risk="low",
            work_item_risk_change="unchanged",
            reversibility="high",
            attention_cost="medium",
            followup_needed=True,
            followup_summary="User answer is needed before a lower-uncertainty decision.",
            requires_confirmation=False,
            confidence=0.70,
            assumptions=["asking reduces uncertainty rather than resolving the work item directly"],
            metadata={"uncertainty_reduction": "high"},
        )
    else:
        raise ValueError(f"Unsupported candidate action: {action}")

    estimate.metadata.update(
        {
            "simulation_source": "deterministic_fallback",
            "fallback_reason": reason,
            "fallback_issue": issue,
            "llm_recommendation_allowed": False,
        }
    )
    return estimate


def _target_estimated_minutes(context: ActiveDecisionContext) -> int:
    if not context.open_work_items:
        return 30
    return int(context.open_work_items[0].get("estimated_minutes_hint") or 30)


def _candidate_executor_capability(
    context: ActiveDecisionContext,
    candidate: CandidateRecord,
) -> dict[str, Any]:
    raw = candidate.params.get("executor_capability")
    if isinstance(raw, dict):
        return dict(raw)
    if context.available_capabilities:
        return dict(context.available_capabilities[0])
    return {}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer") from None
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed


def _member(value: Any, allowed: set[str], field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")
    return normalized


def _confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError("confidence must be numeric") from None
    if parsed < 0.0 or parsed > 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return parsed
