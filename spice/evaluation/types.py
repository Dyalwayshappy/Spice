from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


EVALUATION_SCHEMA_VERSION = "0.1"


@dataclass(slots=True)
class EpisodeSelector:
    filters: dict[str, Any] | None = None
    limit: int = -1
    order_by: str | None = None


@dataclass(slots=True)
class EvaluationGateConfig:
    require_deterministic: bool = True
    require_policy_hash_match: bool = True
    max_candidate_risk_budget_violation_rate: float | None = 0.0


@dataclass(slots=True)
class PolicyRunSummary:
    policy_name: str
    policy_version: str
    policy_hash: str
    total_cycles: int
    cycles_to_stable: int | None
    deterministic: bool
    determinism_message: str
    expected_policy_hash: str | None = None
    policy_hash_match: bool = True


@dataclass(slots=True)
class RiskBudgetStats:
    evaluated_cycles: int
    violating_cycles: int
    violation_rate: float | None


@dataclass(slots=True)
class PolicyEvaluationMetrics:
    total_cycles: int
    valid_cycles: int
    action_divergence_rate: float
    veto_divergence_count: int
    avg_selected_candidate_score_delta: float | None
    baseline_risk_budget_violation_rate: float | None
    candidate_risk_budget_violation_rate: float | None


@dataclass(slots=True)
class PolicyEvaluationGates:
    determinism_pass: bool
    policy_hash_match_pass: bool
    candidate_risk_budget_pass: bool
    overall_pass: bool
    messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PolicyEvaluationReport:
    baseline: PolicyRunSummary
    candidate: PolicyRunSummary
    metrics: PolicyEvaluationMetrics
    gates: PolicyEvaluationGates
    schema_version: str = EVALUATION_SCHEMA_VERSION
    domain: str = "generic"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload
