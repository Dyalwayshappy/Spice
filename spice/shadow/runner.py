from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from spice.core import SpiceRuntime
from spice.protocols import Observation, Outcome, WorldState
from spice.replay import ReplayRunner, load_replay_stream
from spice.replay.types import ReplayReport
from spice.shadow.types import ShadowCycleDiff, ShadowReport


Record = Observation | Outcome
RuntimeFactory = Callable[[], SpiceRuntime]
StabilityPredicate = Callable[[WorldState], bool]


def compare(
    records: Iterable[Record],
    baseline_runtime_factory: RuntimeFactory,
    candidate_runtime_factory: RuntimeFactory,
    baseline_policy_hash: str | None = None,
    candidate_policy_hash: str | None = None,
    check_determinism: bool = True,
) -> ShadowReport:
    """Compare baseline and candidate policies on the same offline replay stream."""
    replay_records = tuple(records)

    baseline_runner = ReplayRunner(
        baseline_runtime_factory,
        stability_predicate=_resolve_stability_predicate(baseline_runtime_factory),
    )
    candidate_runner = ReplayRunner(
        candidate_runtime_factory,
        stability_predicate=_resolve_stability_predicate(candidate_runtime_factory),
    )

    baseline_report = baseline_runner.replay(
        replay_records,
        pinned_policy_hash=baseline_policy_hash,
        check_determinism=check_determinism,
    )
    candidate_report = candidate_runner.replay(
        replay_records,
        pinned_policy_hash=candidate_policy_hash,
        check_determinism=check_determinism,
    )

    _validate_cycle_alignment(baseline_report, candidate_report)

    cycle_diffs: list[ShadowCycleDiff] = []
    score_deltas: list[float] = []
    action_divergence_count = 0
    veto_divergence_count = 0

    for baseline_cycle, candidate_cycle in zip(
        baseline_report.cycles,
        candidate_report.cycles,
    ):
        action_diverged = baseline_cycle.selected_action != candidate_cycle.selected_action
        if action_diverged:
            action_divergence_count += 1

        veto_diverged = baseline_cycle.veto != candidate_cycle.veto
        if veto_diverged:
            veto_divergence_count += 1

        score_delta = _score_delta(
            baseline_cycle.selected_candidate_score,
            candidate_cycle.selected_candidate_score,
        )
        if score_delta is not None:
            score_deltas.append(score_delta)

        cycle_diffs.append(
            ShadowCycleDiff(
                cycle_index=baseline_cycle.cycle_index,
                baseline_action=baseline_cycle.selected_action,
                candidate_action=candidate_cycle.selected_action,
                action_diverged=action_diverged,
                baseline_score=baseline_cycle.selected_candidate_score,
                candidate_score=candidate_cycle.selected_candidate_score,
                score_delta=score_delta,
                baseline_veto=baseline_cycle.veto,
                candidate_veto=candidate_cycle.veto,
                veto_diverged=veto_diverged,
                baseline_candidates_mode=baseline_cycle.candidates_mode,
                candidate_candidates_mode=candidate_cycle.candidates_mode,
                baseline_policy_name=baseline_cycle.policy_name,
                baseline_policy_version=baseline_cycle.policy_version,
                baseline_policy_hash=baseline_cycle.policy_hash,
                candidate_policy_name=candidate_cycle.policy_name,
                candidate_policy_version=candidate_cycle.policy_version,
                candidate_policy_hash=candidate_cycle.policy_hash,
            )
        )

    total_cycles = len(cycle_diffs)
    divergence_rate = (action_divergence_count / total_cycles) if total_cycles else 0.0
    avg_score_delta = (sum(score_deltas) / len(score_deltas)) if score_deltas else None

    return ShadowReport(
        total_cycles=total_cycles,
        divergence_rate=divergence_rate,
        avg_score_delta=avg_score_delta,
        veto_divergence_count=veto_divergence_count,
        baseline_cycles_to_stable=baseline_report.cycles_to_stable,
        candidate_cycles_to_stable=candidate_report.cycles_to_stable,
        baseline_deterministic=baseline_report.deterministic,
        candidate_deterministic=candidate_report.deterministic,
        baseline_determinism_message=baseline_report.determinism_message,
        candidate_determinism_message=candidate_report.determinism_message,
        cycles=cycle_diffs,
    )


def compare_from_jsonl(
    path: str | Path,
    baseline_runtime_factory: RuntimeFactory,
    candidate_runtime_factory: RuntimeFactory,
    baseline_policy_hash: str | None = None,
    candidate_policy_hash: str | None = None,
    check_determinism: bool = True,
) -> ShadowReport:
    records = load_replay_stream(path)
    return compare(
        records,
        baseline_runtime_factory,
        candidate_runtime_factory,
        baseline_policy_hash=baseline_policy_hash,
        candidate_policy_hash=candidate_policy_hash,
        check_determinism=check_determinism,
    )


def _validate_cycle_alignment(baseline: ReplayReport, candidate: ReplayReport) -> None:
    if baseline.total_cycles != candidate.total_cycles:
        raise ValueError(
            "Shadow cycle alignment mismatch: "
            f"baseline={baseline.total_cycles} candidate={candidate.total_cycles}"
        )

    for baseline_cycle, candidate_cycle in zip(baseline.cycles, candidate.cycles):
        if baseline_cycle.cycle_index != candidate_cycle.cycle_index:
            raise ValueError(
                "Shadow cycle index mismatch: "
                f"baseline={baseline_cycle.cycle_index} candidate={candidate_cycle.cycle_index}"
            )


def _resolve_stability_predicate(runtime_factory: RuntimeFactory) -> StabilityPredicate | None:
    runtime = runtime_factory()
    checker = getattr(runtime.domain_pack, "is_stable", None)
    if not callable(checker):
        return None

    def _predicate(state: WorldState) -> bool:
        return bool(checker(state))

    return _predicate


def _score_delta(baseline_score: float | None, candidate_score: float | None) -> float | None:
    if baseline_score is None or candidate_score is None:
        return None
    return float(candidate_score) - float(baseline_score)
