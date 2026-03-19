from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Protocol

from spice.protocols.base import ProtocolRecord
from spice.protocols.decision import Decision
from spice.protocols.world_state import WorldState


@dataclass(slots=True)
class CandidateDecision:
    id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    score_total: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    risk: float = 0.0
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateDecision":
        score_breakdown_raw = payload.get("score_breakdown", {})
        score_breakdown: dict[str, float] = {}
        if isinstance(score_breakdown_raw, dict):
            for key, value in score_breakdown_raw.items():
                score_breakdown[str(key)] = _as_float(value, 0.0)

        params_raw = payload.get("params", {})
        params = dict(params_raw) if isinstance(params_raw, dict) else {}

        return cls(
            id=str(payload.get("id", "candidate.unknown")),
            action=str(payload.get("action", "unknown.action")),
            params=params,
            score_total=_as_float(payload.get("score_total"), 0.0),
            score_breakdown=score_breakdown,
            risk=_as_float(payload.get("risk"), 0.0),
            confidence=_as_float(payload.get("confidence"), 0.0),
        )


@dataclass(slots=True)
class DecisionObjective:
    stability_weight: float = 1.0
    latency_weight: float = 1.0
    cost_weight: float = 1.0
    risk_budget: float = 1.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DecisionObjective":
        return cls(
            stability_weight=_as_float(payload.get("stability_weight"), 1.0),
            latency_weight=_as_float(payload.get("latency_weight"), 1.0),
            cost_weight=_as_float(payload.get("cost_weight"), 1.0),
            risk_budget=_as_float(payload.get("risk_budget"), 1.0),
        )


@dataclass(slots=True)
class SafetyConstraint:
    name: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SafetyConstraint":
        params_raw = payload.get("params", {})
        params = dict(params_raw) if isinstance(params_raw, dict) else {}
        return cls(
            name=str(payload.get("name", "constraint.unknown")),
            kind=str(payload.get("kind", "generic")),
            params=params,
        )


@dataclass(slots=True)
class PolicyIdentity:
    policy_name: str
    policy_version: str
    policy_hash: str = ""
    implementation_fingerprint: str = ""

    @classmethod
    def create(
        cls,
        *,
        policy_name: str,
        policy_version: str,
        implementation_fingerprint: str = "",
    ) -> "PolicyIdentity":
        return cls(
            policy_name=policy_name,
            policy_version=policy_version,
            policy_hash=build_policy_hash(
                policy_name=policy_name,
                policy_version=policy_version,
                implementation_fingerprint=implementation_fingerprint,
            ),
            implementation_fingerprint=implementation_fingerprint,
        )

    def resolved_hash(self) -> str:
        if self.policy_hash:
            return self.policy_hash
        return build_policy_hash(
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            implementation_fingerprint=self.implementation_fingerprint,
        )


class DecisionPolicy(Protocol):
    identity: PolicyIdentity

    def propose(self, state: WorldState, context: Any) -> list[CandidateDecision]:
        ...

    def select(
        self,
        candidates: list[CandidateDecision],
        objective: DecisionObjective,
        constraints: list[SafetyConstraint],
    ) -> Decision:
        ...


@dataclass(slots=True)
class DecisionTrace(ProtocolRecord):
    state_ref: str = ""
    cycle_index: int = 0
    all_candidates: list[CandidateDecision] = field(default_factory=list)
    candidates_mode: str = "synthetic"
    selected_candidate: CandidateDecision | None = None
    veto_events: list[dict[str, Any]] = field(default_factory=list)
    objective_used: DecisionObjective = field(default_factory=DecisionObjective)
    policy_name: str = ""
    policy_version: str = ""
    policy_hash: str = ""


def build_policy_hash(
    *,
    policy_name: str,
    policy_version: str,
    implementation_fingerprint: str = "",
) -> str:
    if implementation_fingerprint:
        token = (
            f"{policy_name}:{policy_version}:{implementation_fingerprint}"
        ).encode("utf-8")
    else:
        token = f"{policy_name}:{policy_version}".encode("utf-8")
    return sha256(token).hexdigest()


def _as_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
