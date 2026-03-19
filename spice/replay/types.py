from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ReplayCycleReport:
    cycle_index: int
    selected_action: str
    selected_candidate_score: float | None
    veto: bool
    candidates_mode: str
    policy_name: str
    policy_version: str
    policy_hash: str


@dataclass(slots=True)
class ReplayReport:
    policy_name: str
    policy_version: str
    policy_hash: str
    total_cycles: int
    cycles_to_stable: int | None
    deterministic: bool
    determinism_message: str
    cycles: list[ReplayCycleReport] = field(default_factory=list)
