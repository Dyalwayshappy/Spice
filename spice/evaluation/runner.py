from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from spice.core import SpiceRuntime
from spice.evaluation.io import (
    episodes_to_replay_records,
    load_episodes_from_provider,
    parse_episode_payloads,
)
from spice.evaluation.types import (
    EpisodeSelector,
    EvaluationGateConfig,
    PolicyEvaluationGates,
    PolicyEvaluationMetrics,
    PolicyEvaluationReport,
    PolicyRunSummary,
    RiskBudgetStats,
)
from spice.memory import EpisodeRecord, MemoryProvider
from spice.protocols import Observation, Outcome, WorldState
from spice.replay import ReplayRunner, load_replay_stream
from spice.shadow import compare


Record = Observation | Outcome
RuntimeFactory = Callable[[], SpiceRuntime]
StabilityPredicate = Callable[[WorldState], bool]


@dataclass(slots=True)
class PolicyEvaluationRunner:
    baseline_runtime_factory: RuntimeFactory
    candidate_runtime_factory: RuntimeFactory
    gate_config: EvaluationGateConfig = field(default_factory=EvaluationGateConfig)

    def evaluate(
        self,
        records: Iterable[Record],
        *,
        domain: str = "generic",
        baseline_expected_policy_hash: str | None = None,
        candidate_expected_policy_hash: str | None = None,
        check_determinism: bool = True,
    ) -> PolicyEvaluationReport:
        replay_records = tuple(records)
        baseline_runner = ReplayRunner(
            self.baseline_runtime_factory,
            stability_predicate=_resolve_stability_predicate(self.baseline_runtime_factory),
        )
        candidate_runner = ReplayRunner(
            self.candidate_runtime_factory,
            stability_predicate=_resolve_stability_predicate(self.candidate_runtime_factory),
        )

        baseline_report = baseline_runner.replay(
            replay_records,
            pinned_policy_hash=None,
            check_determinism=check_determinism,
        )
        candidate_report = candidate_runner.replay(
            replay_records,
            pinned_policy_hash=None,
            check_determinism=check_determinism,
        )

        shadow_report = compare(
            replay_records,
            self.baseline_runtime_factory,
            self.candidate_runtime_factory,
            baseline_policy_hash=None,
            candidate_policy_hash=None,
            check_determinism=check_determinism,
        )

        baseline_hash_match = _hash_match(
            baseline_report.policy_hash,
            baseline_expected_policy_hash,
        )
        candidate_hash_match = _hash_match(
            candidate_report.policy_hash,
            candidate_expected_policy_hash,
        )

        baseline_risk = _risk_budget_stats(replay_records, self.baseline_runtime_factory)
        candidate_risk = _risk_budget_stats(replay_records, self.candidate_runtime_factory)

        total_cycles = int(
            min(
                baseline_report.total_cycles,
                candidate_report.total_cycles,
                shadow_report.total_cycles,
            )
        )
        valid_cycles = int(
            min(
                baseline_risk.evaluated_cycles,
                candidate_risk.evaluated_cycles,
                total_cycles,
            )
        )

        baseline_summary = PolicyRunSummary(
            policy_name=baseline_report.policy_name,
            policy_version=baseline_report.policy_version,
            policy_hash=baseline_report.policy_hash,
            total_cycles=baseline_report.total_cycles,
            cycles_to_stable=baseline_report.cycles_to_stable,
            deterministic=baseline_report.deterministic,
            determinism_message=baseline_report.determinism_message,
            expected_policy_hash=baseline_expected_policy_hash,
            policy_hash_match=baseline_hash_match,
        )
        candidate_summary = PolicyRunSummary(
            policy_name=candidate_report.policy_name,
            policy_version=candidate_report.policy_version,
            policy_hash=candidate_report.policy_hash,
            total_cycles=candidate_report.total_cycles,
            cycles_to_stable=candidate_report.cycles_to_stable,
            deterministic=candidate_report.deterministic,
            determinism_message=candidate_report.determinism_message,
            expected_policy_hash=candidate_expected_policy_hash,
            policy_hash_match=candidate_hash_match,
        )

        metrics = PolicyEvaluationMetrics(
            total_cycles=total_cycles,
            valid_cycles=valid_cycles,
            action_divergence_rate=shadow_report.divergence_rate,
            veto_divergence_count=shadow_report.veto_divergence_count,
            avg_selected_candidate_score_delta=shadow_report.avg_score_delta,
            baseline_risk_budget_violation_rate=baseline_risk.violation_rate,
            candidate_risk_budget_violation_rate=candidate_risk.violation_rate,
        )
        gates = _evaluate_gates(
            baseline=baseline_summary,
            candidate=candidate_summary,
            metrics=metrics,
            config=self.gate_config,
        )

        metadata = {
            "check_determinism": check_determinism,
            "record_count": len(replay_records),
            "observation_count": sum(
                1 for record in replay_records if isinstance(record, Observation)
            ),
            "outcome_count": sum(
                1 for record in replay_records if isinstance(record, Outcome)
            ),
            "baseline_risk_evaluated_cycles": baseline_risk.evaluated_cycles,
            "candidate_risk_evaluated_cycles": candidate_risk.evaluated_cycles,
            "baseline_risk_violating_cycles": baseline_risk.violating_cycles,
            "candidate_risk_violating_cycles": candidate_risk.violating_cycles,
        }

        return PolicyEvaluationReport(
            domain=domain,
            baseline=baseline_summary,
            candidate=candidate_summary,
            metrics=metrics,
            gates=gates,
            metadata=metadata,
        )

    def evaluate_from_jsonl(
        self,
        path: str | Path,
        *,
        domain: str = "generic",
        baseline_expected_policy_hash: str | None = None,
        candidate_expected_policy_hash: str | None = None,
        check_determinism: bool = True,
    ) -> PolicyEvaluationReport:
        records = load_replay_stream(path)
        return self.evaluate(
            records,
            domain=domain,
            baseline_expected_policy_hash=baseline_expected_policy_hash,
            candidate_expected_policy_hash=candidate_expected_policy_hash,
            check_determinism=check_determinism,
        )

    def evaluate_from_episodes(
        self,
        episodes: Iterable[EpisodeRecord | dict],
        *,
        domain: str | None = None,
        baseline_expected_policy_hash: str | None = None,
        candidate_expected_policy_hash: str | None = None,
        check_determinism: bool = True,
    ) -> PolicyEvaluationReport:
        parsed_episodes = parse_episode_payloads(episodes)
        resolved_domain = domain or (parsed_episodes[0].domain if parsed_episodes else "generic")
        records = episodes_to_replay_records(parsed_episodes)
        return self.evaluate(
            records,
            domain=resolved_domain,
            baseline_expected_policy_hash=baseline_expected_policy_hash,
            candidate_expected_policy_hash=candidate_expected_policy_hash,
            check_determinism=check_determinism,
        )

    def evaluate_from_provider(
        self,
        provider: MemoryProvider,
        *,
        domain: str,
        selector: EpisodeSelector | None = None,
        baseline_expected_policy_hash: str | None = None,
        candidate_expected_policy_hash: str | None = None,
        check_determinism: bool = True,
    ) -> PolicyEvaluationReport:
        episodes = load_episodes_from_provider(
            provider,
            domain=domain,
            selector=selector,
        )
        return self.evaluate_from_episodes(
            episodes,
            domain=domain,
            baseline_expected_policy_hash=baseline_expected_policy_hash,
            candidate_expected_policy_hash=candidate_expected_policy_hash,
            check_determinism=check_determinism,
        )


def _evaluate_gates(
    *,
    baseline: PolicyRunSummary,
    candidate: PolicyRunSummary,
    metrics: PolicyEvaluationMetrics,
    config: EvaluationGateConfig,
) -> PolicyEvaluationGates:
    messages: list[str] = []

    determinism_pass = True
    if config.require_deterministic:
        determinism_pass = baseline.deterministic and candidate.deterministic
        if not determinism_pass:
            messages.append("determinism_failed")

    policy_hash_match_pass = True
    if config.require_policy_hash_match:
        policy_hash_match_pass = baseline.policy_hash_match and candidate.policy_hash_match
        if not policy_hash_match_pass:
            messages.append("policy_hash_mismatch")

    candidate_risk_budget_pass = True
    threshold = config.max_candidate_risk_budget_violation_rate
    if threshold is not None and metrics.candidate_risk_budget_violation_rate is not None:
        candidate_risk_budget_pass = (
            metrics.candidate_risk_budget_violation_rate <= float(threshold)
        )
        if not candidate_risk_budget_pass:
            messages.append("candidate_risk_budget_violation_rate_exceeded")

    overall_pass = (
        determinism_pass
        and policy_hash_match_pass
        and candidate_risk_budget_pass
    )

    return PolicyEvaluationGates(
        determinism_pass=determinism_pass,
        policy_hash_match_pass=policy_hash_match_pass,
        candidate_risk_budget_pass=candidate_risk_budget_pass,
        overall_pass=overall_pass,
        messages=messages,
    )


def _risk_budget_stats(
    records: Iterable[Record],
    runtime_factory: RuntimeFactory,
) -> RiskBudgetStats:
    runtime = runtime_factory()
    evaluated_cycles = 0
    violating_cycles = 0

    for record in records:
        if isinstance(record, Observation):
            state = runtime.update_state(record)
            runtime.decide(state)
            trace = runtime.latest_decision_trace
            if trace is None:
                continue
            selected = trace.selected_candidate
            if selected is None:
                continue

            evaluated_cycles += 1
            if float(selected.risk) > float(trace.objective_used.risk_budget):
                violating_cycles += 1
            continue

        if isinstance(record, Outcome):
            runtime.update_state(record)

    if evaluated_cycles == 0:
        return RiskBudgetStats(
            evaluated_cycles=0,
            violating_cycles=0,
            violation_rate=None,
        )

    return RiskBudgetStats(
        evaluated_cycles=evaluated_cycles,
        violating_cycles=violating_cycles,
        violation_rate=violating_cycles / evaluated_cycles,
    )


def _resolve_stability_predicate(
    runtime_factory: RuntimeFactory,
) -> StabilityPredicate | None:
    runtime = runtime_factory()
    checker = getattr(runtime.domain_pack, "is_stable", None)
    if not callable(checker):
        return None

    def _predicate(state: WorldState) -> bool:
        return bool(checker(state))

    return _predicate


def _hash_match(actual: str, expected: str | None) -> bool:
    if expected is None:
        return True
    return str(actual) == str(expected)
