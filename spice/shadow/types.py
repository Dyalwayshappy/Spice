from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ShadowCycleDiff:
    cycle_index: int
    baseline_action: str
    candidate_action: str
    action_diverged: bool
    baseline_score: float | None
    candidate_score: float | None
    score_delta: float | None
    baseline_veto: bool
    candidate_veto: bool
    veto_diverged: bool
    baseline_candidates_mode: str
    candidate_candidates_mode: str
    baseline_policy_name: str
    baseline_policy_version: str
    baseline_policy_hash: str
    candidate_policy_name: str
    candidate_policy_version: str
    candidate_policy_hash: str


@dataclass(slots=True)
class ShadowReport:
    total_cycles: int
    divergence_rate: float
    avg_score_delta: float | None
    veto_divergence_count: int
    baseline_cycles_to_stable: int | None
    candidate_cycles_to_stable: int | None
    baseline_deterministic: bool
    candidate_deterministic: bool
    baseline_determinism_message: str
    candidate_determinism_message: str
    cycles: list[ShadowCycleDiff] = field(default_factory=list)
