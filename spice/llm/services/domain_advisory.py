from __future__ import annotations

"""Domain-agnostic LLM decision/simulation activation for generated domains.

Deterministic responses in this module are explicit dev/test stubs so generated
scaffolds can run locally without external model dependencies.
"""

import json
import os
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import uuid4

from spice.decision import (
    CandidateDecision,
    DecisionObjective,
    DecisionPolicy,
    PolicyIdentity,
    SafetyConstraint,
)
from spice.llm.adapters import LLMDecisionAdapter, LLMSimulationAdapter
from spice.llm.core import (
    LLMClient,
    LLMModelConfig,
    LLMModelConfigOverride,
    LLMRouter,
    LLMTaskHook,
    ProviderRegistry,
)
from spice.llm.providers import DeterministicLLMProvider, SubprocessLLMProvider
from spice.protocols import Decision, WorldState


DOMAIN_MODEL_ENV = "SPICE_DOMAIN_MODEL"
DOMAIN_ADVISORY_ATTRIBUTE_KEYS = (
    "suggestion_text",
    "confidence",
    "urgency",
    "score",
    "simulation_rationale",
)


@dataclass(slots=True)
class DomainLLMDecisionPolicy(DecisionPolicy):
    """Reusable LLM-driven policy for domain decision proposal + simulation."""

    decision_adapter: LLMDecisionAdapter
    simulation_adapter: LLMSimulationAdapter
    allowed_actions: tuple[str, ...]
    domain: str
    max_candidates: int = 3
    identity: PolicyIdentity = field(
        default_factory=lambda: PolicyIdentity.create(
            policy_name="spice.domain.llm_policy",
            policy_version="0.1",
            implementation_fingerprint="phase2_6",
        )
    )
    _last_state: WorldState | None = field(default=None, init=False, repr=False)
    _last_candidate_decisions: dict[str, Decision] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def propose(self, state: WorldState, context: Any) -> list[CandidateDecision]:
        self._last_state = state
        self._last_candidate_decisions = {}
        try:
            proposals = self.decision_adapter.propose(
                state,
                context={
                    "domain": self.domain,
                    "stage": "domain_decision",
                },
                max_candidates=self.max_candidates,
            )
        except Exception:
            return []

        candidates: list[CandidateDecision] = []
        for proposal in proposals:
            normalized = _normalize_decision(proposal, state=state, domain=self.domain)
            action = normalized.selected_action or ""
            if action not in self.allowed_actions:
                continue

            candidate_id = normalized.id or f"dec-{uuid4().hex}"
            normalized.id = candidate_id
            self._last_candidate_decisions[candidate_id] = normalized
            score = _as_float(normalized.attributes.get("score"), 0.0)
            confidence = _as_float(normalized.attributes.get("confidence"), 0.0)
            risk = _as_float(normalized.attributes.get("risk"), 0.0)
            params_raw = normalized.attributes.get("params")
            params = dict(params_raw) if isinstance(params_raw, dict) else {}
            candidates.append(
                CandidateDecision(
                    id=candidate_id,
                    action=action,
                    params=params,
                    score_total=score,
                    score_breakdown={"proposal": score},
                    risk=risk,
                    confidence=confidence,
                )
            )
        return candidates

    def select(
        self,
        candidates: list[CandidateDecision],
        objective: DecisionObjective,
        constraints: list[SafetyConstraint],
    ) -> Decision:
        if not candidates:
            default_action = self.allowed_actions[0] if self.allowed_actions else ""
            return self._degraded_decision(
                selected_action=default_action,
                reason="no_candidates_from_llm",
            )

        if not any(candidate.id in self._last_candidate_decisions for candidate in candidates):
            return self._degraded_decision(
                selected_action=candidates[0].action,
                reason="runtime_domain_fallback_candidates",
            )

        risk_budget = objective.risk_budget
        risk_filtered = [candidate for candidate in candidates if candidate.risk <= risk_budget]
        eligible = risk_filtered or candidates

        best_candidate = eligible[0]
        best_advisory = _normalize_advisory_attributes(
            score=eligible[0].score_total,
            confidence=eligible[0].confidence,
            simulation_rationale="candidate_default",
        )
        best_artifact: dict[str, Any] = {}

        for candidate in eligible:
            seed_decision = self._seed_decision_for_candidate(candidate)
            artifact = self._simulate_candidate(seed_decision, objective=objective, constraints=constraints)
            advisory = _normalize_advisory_attributes(
                suggestion_text=_extract_suggestion(seed_decision, artifact),
                confidence=_extract_confidence(seed_decision, artifact, default=candidate.confidence),
                urgency=_extract_urgency(seed_decision, artifact),
                score=_as_float(artifact.get("score"), candidate.score_total),
                simulation_rationale=_extract_rationale(artifact),
            )

            if advisory["score"] > best_advisory["score"]:
                best_candidate = candidate
                best_advisory = advisory
                best_artifact = artifact

        selected = self._seed_decision_for_candidate(best_candidate)
        if selected.selected_action is None:
            selected.selected_action = best_candidate.action
        selected.attributes["selected_candidate_id"] = best_candidate.id
        selected.attributes["all_candidates"] = [
            {
                "id": candidate.id,
                "action": candidate.action,
                "score_total": candidate.score_total,
                "risk": candidate.risk,
                "confidence": candidate.confidence,
            }
            for candidate in candidates
        ]
        selected.attributes["advisory_degraded"] = False
        selected.attributes.update(best_advisory)
        if best_artifact:
            selected.metadata["simulation"] = dict(best_artifact)
        return selected

    def _simulate_candidate(
        self,
        decision: Decision,
        *,
        objective: DecisionObjective,
        constraints: list[SafetyConstraint],
    ) -> dict[str, Any]:
        if self._last_state is None:
            return {}
        try:
            artifact = self.simulation_adapter.simulate(
                self._last_state,
                decision=decision,
                context={
                    "domain": self.domain,
                    "stage": "domain_simulation",
                    "objective": {"risk_budget": objective.risk_budget},
                    "constraints": [
                        {
                            "name": constraint.name,
                            "kind": constraint.kind,
                            "params": constraint.params,
                        }
                        for constraint in constraints
                    ],
                },
            )
        except Exception:
            return {}
        return dict(artifact) if isinstance(artifact, dict) else {}

    def _seed_decision_for_candidate(self, candidate: CandidateDecision) -> Decision:
        proposal = self._last_candidate_decisions.get(candidate.id)
        if proposal is not None:
            return _copy_decision(proposal, state=self._last_state, domain=self.domain)
        refs = [self._last_state.id] if self._last_state is not None else []
        return Decision(
            id=f"dec-{uuid4().hex}",
            decision_type=f"{self.domain}.llm",
            status="proposed",
            selected_action=candidate.action,
            refs=refs,
            attributes={},
        )

    def _degraded_decision(self, *, selected_action: str, reason: str) -> Decision:
        refs = [self._last_state.id] if self._last_state is not None else []
        attributes = _normalize_advisory_attributes(
            confidence=0.0,
            urgency="",
            score=0.0,
            simulation_rationale=f"degraded:{reason}",
        )
        attributes.update(
            {
                "advisory_degraded": True,
                "degraded_reason": reason,
            }
        )
        return Decision(
            id=f"dec-{uuid4().hex}",
            decision_type=f"{self.domain}.llm",
            status="proposed",
            selected_action=selected_action,
            refs=refs,
            attributes=attributes,
        )


def build_domain_llm_decision_policy(
    *,
    model: str | None,
    domain: str,
    allowed_actions: tuple[str, ...],
) -> DomainLLMDecisionPolicy | None:
    if not allowed_actions:
        return None

    try:
        client = _build_domain_llm_client(allowed_actions=allowed_actions)
        model_override = _resolve_domain_model_override(model=model)
        return DomainLLMDecisionPolicy(
            decision_adapter=LLMDecisionAdapter(client=client, model_override=model_override),
            simulation_adapter=LLMSimulationAdapter(client=client, model_override=model_override),
            allowed_actions=tuple(allowed_actions),
            domain=domain,
        )
    except Exception:
        return None


def _build_domain_llm_client(*, allowed_actions: tuple[str, ...]) -> LLMClient:
    decision_default = LLMModelConfig(
        provider_id="deterministic",
        model_id="deterministic.domain.stub.v1",
        temperature=0.0,
        max_tokens=1200,
        timeout_sec=45.0,
        response_format_hint="json_array",
    )
    simulation_default = replace(decision_default, response_format_hint="json_object")
    router = LLMRouter(
        global_default=decision_default,
        hook_defaults={
            LLMTaskHook.DECISION_PROPOSE: decision_default,
            LLMTaskHook.SIMULATION_ADVISE: simulation_default,
        },
    )
    stub_provider = DeterministicLLMProvider(
        responses={
            LLMTaskHook.DECISION_PROPOSE: _stub_llm_domain_decision_response(
                allowed_actions=allowed_actions
            ),
            LLMTaskHook.SIMULATION_ADVISE: _stub_llm_domain_simulation_response(),
        }
    )
    registry = (
        ProviderRegistry.empty()
        .register(stub_provider)
        .register(SubprocessLLMProvider())
    )
    return LLMClient(registry=registry, router=router)


def _resolve_domain_model_override(model: str | None) -> LLMModelConfigOverride | None:
    raw = model if model is not None else os.environ.get(DOMAIN_MODEL_ENV)
    if raw is None:
        return None
    token = raw.strip()
    if not token:
        return None
    if token.lower() == "deterministic":
        return LLMModelConfigOverride(
            provider_id="deterministic",
            model_id="deterministic.domain.stub.v1",
        )
    return LLMModelConfigOverride(
        provider_id="subprocess",
        model_id=token,
    )


def _stub_llm_domain_decision_response(*, allowed_actions: tuple[str, ...]) -> str:
    action = allowed_actions[0] if allowed_actions else ""
    payload = [
        {
            "decision_type": "domain.llm",
            "status": "proposed",
            "selected_action": action,
            "attributes": {
                "confidence": 0.6,
                "urgency": "normal",
            },
        }
    ]
    return json.dumps(payload, ensure_ascii=True)


def _stub_llm_domain_simulation_response() -> str:
    payload = {
        "score": 0.6,
        "confidence": 0.6,
        "urgency": "normal",
        "suggestion_text": (
            "Stub LLM advisory suggestion (dev/test): take a reversible step and monitor impact."
        ),
        "simulation_rationale": "stub_llm_default_domain_simulation",
    }
    return json.dumps(payload, ensure_ascii=True)


def _normalize_advisory_attributes(
    *,
    suggestion_text: str = "",
    confidence: float = 0.0,
    urgency: str = "",
    score: float = 0.0,
    simulation_rationale: str = "",
) -> dict[str, Any]:
    payload = {
        "suggestion_text": _as_text(suggestion_text),
        "confidence": _as_float(confidence, 0.0),
        "urgency": _as_text(urgency),
        "score": _as_float(score, 0.0),
        "simulation_rationale": _as_text(simulation_rationale),
    }
    return {key: payload[key] for key in DOMAIN_ADVISORY_ATTRIBUTE_KEYS}


def _normalize_decision(decision: Decision, *, state: WorldState, domain: str) -> Decision:
    decision_id = (
        decision.id.strip()
        if isinstance(decision.id, str) and decision.id.strip()
        else f"dec-{uuid4().hex}"
    )
    decision_type = (
        decision.decision_type.strip()
        if isinstance(decision.decision_type, str) and decision.decision_type.strip()
        else f"{domain}.llm"
    )
    status = (
        decision.status.strip()
        if isinstance(decision.status, str) and decision.status.strip()
        else "proposed"
    )
    refs = [ref for ref in decision.refs if isinstance(ref, str)]
    if state.id not in refs:
        refs.append(state.id)
    return Decision(
        id=decision_id,
        decision_type=decision_type,
        status=status,
        selected_action=decision.selected_action,
        refs=refs,
        metadata=dict(decision.metadata),
        attributes=dict(decision.attributes),
    )


def _copy_decision(decision: Decision, *, state: WorldState | None, domain: str) -> Decision:
    refs = [ref for ref in decision.refs if isinstance(ref, str)]
    if state is not None and state.id not in refs:
        refs.append(state.id)
    decision_id = (
        decision.id if isinstance(decision.id, str) and decision.id.strip() else f"dec-{uuid4().hex}"
    )
    decision_type = (
        decision.decision_type
        if isinstance(decision.decision_type, str) and decision.decision_type.strip()
        else f"{domain}.llm"
    )
    status = (
        decision.status
        if isinstance(decision.status, str) and decision.status.strip()
        else "proposed"
    )
    return Decision(
        id=decision_id,
        decision_type=decision_type,
        status=status,
        selected_action=decision.selected_action,
        refs=refs,
        metadata=dict(decision.metadata),
        attributes=dict(decision.attributes),
    )


def _extract_suggestion(decision: Decision, artifact: dict[str, Any]) -> str:
    fields = (
        artifact.get("suggestion_text"),
        artifact.get("suggestion"),
        artifact.get("advice"),
        decision.attributes.get("suggestion_text"),
    )
    for value in fields:
        text = _as_text(value)
        if text:
            return text
    return ""


def _extract_urgency(decision: Decision, artifact: dict[str, Any]) -> str:
    fields = (artifact.get("urgency"), decision.attributes.get("urgency"))
    for value in fields:
        text = _as_text(value)
        if text:
            return text
    return ""


def _extract_confidence(decision: Decision, artifact: dict[str, Any], *, default: float) -> float:
    if "confidence" in artifact:
        return _as_float(artifact.get("confidence"), default)
    if "confidence" in decision.attributes:
        return _as_float(decision.attributes.get("confidence"), default)
    return default


def _extract_rationale(artifact: dict[str, Any]) -> str:
    fields = (
        artifact.get("simulation_rationale"),
        artifact.get("rationale"),
        artifact.get("summary"),
    )
    for value in fields:
        text = _as_text(value)
        if text:
            return text
    return ""


def _as_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""
