from __future__ import annotations

from pathlib import Path
from typing import Any

from spice.decision.core import (
    CandidateDecision,
    DecisionObjective,
    DecisionPolicy,
    PolicyIdentity,
    SafetyConstraint,
)
from spice.decision.guidance import (
    DecisionGuidance,
    DecisionGuidanceSupport,
    GuidedDecisionPolicy,
    load_decision_guidance,
)
from spice.protocols.decision import Decision
from spice.protocols.world_state import WorldState

from examples.decision_hub_demo.candidates import (
    CandidateGenerationReport,
    CandidateRecord,
    generate_candidates,
)
from examples.decision_hub_demo.context import (
    ActiveDecisionContext,
    build_active_context,
)
from examples.decision_hub_demo.simulation import (
    ConsequenceEstimate,
    StructuredSimulationRunner,
)
from examples.decision_hub_demo.formatter import format_recommendation
from examples.decision_hub_demo.ids import make_decision_id, make_trace_ref
from examples.decision_hub_demo.trace import register_trace


DEMO_DIR = Path(__file__).resolve().parent
DEMO_DECISION_MD = DEMO_DIR / "decision.md"


class DecisionHubCandidatePolicy(DecisionPolicy):
    """Demo policy that proposes simulated candidates but does not select them."""

    decision_guidance_support = DecisionGuidanceSupport(
        score_dimensions={
            "commitment_safety",
            "work_item_risk_reduction",
            "reversibility",
            "time_efficiency",
            "attention_preservation",
            "confidence_alignment",
        },
        constraint_ids={
            "no_commitment_endangerment",
            "no_silent_blocker_ignore",
            "no_executor_delegation_without_capability",
            "no_low_confidence_irreversible_action",
        },
        tradeoff_rule_ids={
            "prefer_delegate_when_executor_available_and_time_pressure",
            "prefer_reversible_under_time_pressure",
        },
    )

    def __init__(self, simulation_runner: StructuredSimulationRunner | None = None) -> None:
        self.identity = PolicyIdentity.create(
            policy_name="decision_hub_demo.candidate_policy",
            policy_version="0.1.0",
            implementation_fingerprint="world-state-active-context-simulation-v1",
        )
        self.simulation_runner = simulation_runner or StructuredSimulationRunner()
        self.latest_context: ActiveDecisionContext | None = None
        self.latest_generation_report: CandidateGenerationReport | None = None
        self.latest_consequences: dict[str, ConsequenceEstimate] = {}

    def propose(self, state: WorldState, context: Any) -> list[CandidateDecision]:
        now = context.get("now") if isinstance(context, dict) else None
        active_context = build_active_context(state, now=now)
        report = generate_candidates(active_context)
        consequences = {
            candidate.candidate_id: self.simulation_runner.simulate(active_context, candidate)
            for candidate in report.enabled
        }

        self.latest_context = active_context
        self.latest_generation_report = report
        self.latest_consequences = consequences
        return [
            self._to_candidate_decision(active_context, candidate, consequences[candidate.candidate_id])
            for candidate in report.enabled
        ]

    def select(
        self,
        candidates: list[CandidateDecision],
        objective: DecisionObjective,
        constraints: list[SafetyConstraint],
    ) -> Decision:
        del objective, constraints
        selected = sorted(candidates, key=lambda item: item.score_total, reverse=True)[0]
        return Decision(
            id=f"decision.demo.base.{selected.id}",
            decision_type="decision_hub_demo.base_policy_decision",
            selected_action=selected.action,
            attributes={"selected_candidate_id": selected.id},
        )

    def _to_candidate_decision(
        self,
        context: ActiveDecisionContext,
        candidate: CandidateRecord,
        consequence: ConsequenceEstimate,
    ) -> CandidateDecision:
        score_breakdown = _score_breakdown(context, consequence)
        score_total = sum(score_breakdown.values()) / len(score_breakdown)
        params = {
            **candidate.params,
            "candidate_generation": candidate.to_payload(),
            "active_context_id": context.id,
            "grounding_refs": list(candidate.grounding_refs),
            "consequence": consequence.to_payload(),
            "simulation_ref": f"simulation.{candidate.candidate_id}",
            "constraint_checks": _constraint_checks(context, candidate, consequence),
            "tradeoff_rule_results": _tradeoff_rule_results(context, candidate, consequence),
        }
        return CandidateDecision(
            id=candidate.candidate_id,
            action=candidate.action_type,
            params=params,
            score_total=score_total,
            score_breakdown=score_breakdown,
            risk=max(_risk_value(consequence.commitment_risk), _work_item_risk_value(consequence.work_item_risk_change)),
            confidence=consequence.confidence,
        )


class DecisionHubRecommendationRunner:
    """Runs the demo loop and delegates final selection to GuidedDecisionPolicy."""

    def __init__(
        self,
        *,
        guidance: DecisionGuidance | None = None,
        guidance_path: str | Path | None = None,
        simulation_runner: StructuredSimulationRunner | None = None,
    ) -> None:
        self.guidance = guidance or load_decision_guidance(guidance_path or DEMO_DECISION_MD)
        self.base_policy = DecisionHubCandidatePolicy(simulation_runner)
        self.guided_policy = GuidedDecisionPolicy(self.base_policy, self.guidance)

    def recommend(self, state: WorldState, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        candidates = self.guided_policy.propose(state, context)
        decision = self.guided_policy.select(candidates, DecisionObjective(), [])
        selected_candidate_id = decision.attributes["selected_candidate_id"]
        candidate_payloads = decision.attributes.get("all_candidates", [])
        selected_payload = next(
            item for item in candidate_payloads if item["id"] == selected_candidate_id
        )
        explanation = decision.attributes["decision_guidance_explanation"]
        selected_action = selected_payload["action"]
        acted_on = selected_payload["params"].get("target_work_item_id")
        selected_candidate_meta = selected_payload.get("params", {}).get("candidate_generation", {})
        requires_confirmation = bool(selected_candidate_meta.get("requires_confirmation", False))
        trace = {
            "active_context": (
                self.base_policy.latest_context.to_payload()
                if self.base_policy.latest_context
                else {}
            ),
            "candidate_generation": (
                self.base_policy.latest_generation_report.to_payload()
                if self.base_policy.latest_generation_report
                else {}
            ),
            "candidates": candidate_payloads,
            "candidate_consequences": {
                key: value.to_payload()
                for key, value in self.base_policy.latest_consequences.items()
            },
            "consequences": {
                key: value.to_payload()
                for key, value in self.base_policy.latest_consequences.items()
            },
            "candidate_scores": explanation["candidate_scores"],
            "scores": explanation["candidate_scores"],
            "constraint_evaluations": explanation["constraint_evaluations"],
            "veto_events": explanation["veto_events"],
            "veto": explanation["veto_events"],
            "applied_tradeoff_rules": explanation["applied_tradeoff_rules"],
            "tradeoff": explanation["applied_tradeoff_rules"],
            "unsupported_tradeoff_rules": explanation["unsupported_tradeoff_rules"],
            "guidance_artifact": explanation["artifact"],
            "selection_reason": explanation["final_selection_reason"],
            "selected_candidate_id": selected_candidate_id,
            "selected_action": selected_action,
            "requires_confirmation": requires_confirmation,
            "llm_direct_recommendation": False,
        }
        decision_time = (
            context.get("now")
            if isinstance(context, dict)
            else None
        ) or (
            self.base_policy.latest_context.now
            if self.base_policy.latest_context
            else None
        )
        decision_id = make_decision_id(
            now=decision_time,
            acted_on=acted_on,
            trace_seed={
                "selected_candidate_id": selected_candidate_id,
                "scores": explanation["candidate_scores"],
                "veto": explanation["veto_events"],
                "tradeoff": explanation["applied_tradeoff_rules"],
                "guidance": explanation["artifact"],
            },
        )
        trace_ref = make_trace_ref(decision_id)
        trace["decision_id"] = decision_id
        trace["trace_ref"] = trace_ref
        register_trace(trace_ref, trace)
        formatted = format_recommendation(
            selected_action=selected_action,
            acted_on=acted_on,
            score_breakdown=selected_payload["score_breakdown"],
            veto_reasons=decision.attributes.get("veto_events", []),
            tradeoff_rules_applied=decision.attributes.get("applied_tradeoff_rules", []),
            trace=trace,
        )
        return {
            "decision_id": decision_id,
            "recommendation": formatted["recommendation"],
            "selected_action": selected_action,
            "acted_on": acted_on,
            "trace_ref": trace_ref,
            "human_summary": formatted["human_summary"],
            "reason_summary": formatted["reason_summary"],
            "requires_confirmation": requires_confirmation,
            "score_breakdown": selected_payload["score_breakdown"],
            "veto_reasons": decision.attributes.get("veto_events", []),
            "tradeoff_rules_applied": decision.attributes.get("applied_tradeoff_rules", []),
            "simulation_refs": [
                item.get("params", {}).get("simulation_ref")
                for item in candidate_payloads
                if item.get("params", {}).get("simulation_ref")
            ],
            "guided_decision_id": decision.id,
            "recommendation_source": "GuidedDecisionPolicy",
            "llm_direct_recommendation": False,
            "trace": trace,
        }


def _score_breakdown(
    context: ActiveDecisionContext,
    consequence: ConsequenceEstimate,
) -> dict[str, float]:
    time_cost = max(0, consequence.expected_time_cost_minutes)
    available = max(1, context.available_window_minutes)
    return {
        "commitment_safety": 1.0 - _risk_value(consequence.commitment_risk),
        "work_item_risk_reduction": _work_item_score(consequence.work_item_risk_change),
        "reversibility": _ordinal_score(consequence.reversibility),
        "time_efficiency": max(0.0, 1.0 - min(1.0, time_cost / available)),
        "attention_preservation": 1.0 - _ordinal_score(consequence.attention_cost),
        "confidence_alignment": consequence.confidence,
    }


def _constraint_checks(
    context: ActiveDecisionContext,
    candidate: CandidateRecord,
    consequence: ConsequenceEstimate,
) -> dict[str, str]:
    del context
    return {
        "no_commitment_endangerment": (
            "fail" if consequence.commitment_risk == "high" else "pass"
        ),
        "no_silent_blocker_ignore": (
            "fail"
            if candidate.action_type == "ignore_temporarily"
            and consequence.work_item_risk_change == "increased"
            else "pass"
        ),
        "no_executor_delegation_without_capability": (
            "fail"
            if candidate.action_type == "delegate_to_executor"
            and not consequence.metadata.get("executor_available", False)
            else "pass"
        ),
        "no_low_confidence_irreversible_action": (
            "fail"
            if consequence.confidence < 0.60 and consequence.reversibility == "low"
            else "pass"
        ),
    }


def _tradeoff_rule_results(
    context: ActiveDecisionContext,
    candidate: CandidateRecord,
    consequence: ConsequenceEstimate,
) -> dict[str, dict[str, Any]]:
    time_pressure = context.available_window_minutes < _target_minutes(context)
    results: dict[str, dict[str, Any]] = {}
    if (
        candidate.action_type == "delegate_to_executor"
        and context.available_capabilities
        and time_pressure
    ):
        results["prefer_delegate_when_executor_available_and_time_pressure"] = {
            "status": "preferred",
            "reason": "executor capability is available and available window is shorter than estimated work",
        }
    if time_pressure and consequence.reversibility == "high":
        results["prefer_reversible_under_time_pressure"] = {
            "status": "preferred",
            "reason": "candidate is highly reversible under time pressure",
        }
    return results


def _target_minutes(context: ActiveDecisionContext) -> int:
    if not context.open_work_items:
        return 30
    return int(context.open_work_items[0].get("estimated_minutes_hint") or 30)


def _risk_value(level: str) -> float:
    return {"low": 0.10, "medium": 0.45, "high": 0.95}.get(level, 0.50)


def _work_item_risk_value(change: str) -> float:
    return {"reduced": 0.20, "unchanged": 0.50, "increased": 0.90}.get(change, 0.50)


def _work_item_score(change: str) -> float:
    return {"reduced": 1.0, "unchanged": 0.45, "increased": 0.0}.get(change, 0.25)


def _ordinal_score(level: str) -> float:
    return {"none": 0.0, "low": 0.25, "medium": 0.55, "high": 0.90}.get(level, 0.40)
