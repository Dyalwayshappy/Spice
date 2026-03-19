from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from spice.core import SpiceRuntime
from spice.decision import DecisionTrace
from spice.protocols import Observation, Outcome, WorldState

from spice.replay.io import load_replay_stream
from spice.replay.types import ReplayCycleReport, ReplayReport


Record = Observation | Outcome
StabilityPredicate = Callable[[WorldState], bool]
RuntimeFactory = Callable[[], SpiceRuntime]


@dataclass(slots=True)
class _ReplayPass:
    report: ReplayReport
    signatures: list[tuple]


class ReplayRunner:
    """Offline replay runner for deterministic decision-trace reproduction."""

    def __init__(
        self,
        runtime_factory: RuntimeFactory,
        *,
        stability_predicate: StabilityPredicate | None = None,
    ) -> None:
        self.runtime_factory = runtime_factory
        self.stability_predicate = stability_predicate

    def replay_from_jsonl(
        self,
        path: str | Path,
        *,
        pinned_policy_hash: str | None = None,
        check_determinism: bool = True,
    ) -> ReplayReport:
        records = load_replay_stream(path)
        return self.replay(
            records,
            pinned_policy_hash=pinned_policy_hash,
            check_determinism=check_determinism,
        )

    def replay(
        self,
        records: Iterable[Record],
        *,
        pinned_policy_hash: str | None = None,
        check_determinism: bool = True,
    ) -> ReplayReport:
        replay_records = list(records)
        first_pass = self._run_pass(replay_records, pinned_policy_hash=pinned_policy_hash)

        deterministic = True
        determinism_message = "determinism_check_skipped"
        if check_determinism:
            second_pass = self._run_pass(replay_records, pinned_policy_hash=pinned_policy_hash)
            deterministic = first_pass.signatures == second_pass.signatures
            determinism_message = (
                "deterministic"
                if deterministic
                else "non_deterministic_trace_signature_mismatch"
            )

        report = first_pass.report
        report.deterministic = deterministic
        report.determinism_message = determinism_message
        return report

    def _run_pass(
        self,
        records: list[Record],
        *,
        pinned_policy_hash: str | None,
    ) -> _ReplayPass:
        runtime = self.runtime_factory()
        expected_policy_hash = self._resolve_expected_policy_hash(
            runtime,
            pinned_policy_hash=pinned_policy_hash,
        )

        cycles: list[ReplayCycleReport] = []
        signatures: list[tuple] = []
        cycles_to_stable: int | None = None

        for record in records:
            if isinstance(record, Observation):
                state = runtime.update_state(record)
                decision = runtime.decide(state)
                trace = runtime.latest_decision_trace
                if trace is None:
                    raise RuntimeError("Replay expected DecisionTrace but none was recorded.")

                self._validate_policy_hash(trace, expected_policy_hash)

                cycle = self._to_cycle_report(decision.selected_action, trace)
                cycles.append(cycle)
                signatures.append(self._trace_signature(cycle, trace))

                if (
                    cycles_to_stable is None
                    and self.stability_predicate is not None
                    and self.stability_predicate(state)
                ):
                    cycles_to_stable = cycle.cycle_index

            elif isinstance(record, Outcome):
                runtime.update_state(record)
            else:
                raise TypeError(f"Unsupported replay record type: {type(record)!r}")

        policy_name = cycles[0].policy_name if cycles else ""
        policy_version = cycles[0].policy_version if cycles else ""
        policy_hash = cycles[0].policy_hash if cycles else (expected_policy_hash or "")

        report = ReplayReport(
            policy_name=policy_name,
            policy_version=policy_version,
            policy_hash=policy_hash,
            total_cycles=len(cycles),
            cycles_to_stable=cycles_to_stable,
            deterministic=True,
            determinism_message="",
            cycles=cycles,
        )
        return _ReplayPass(report=report, signatures=signatures)

    @staticmethod
    def _resolve_expected_policy_hash(
        runtime: SpiceRuntime,
        *,
        pinned_policy_hash: str | None,
    ) -> str | None:
        if pinned_policy_hash:
            return pinned_policy_hash

        policy = runtime.decision_policy
        if policy is not None:
            return policy.identity.resolved_hash()
        return None

    @staticmethod
    def _validate_policy_hash(trace: DecisionTrace, expected_policy_hash: str | None) -> None:
        if expected_policy_hash is None:
            return
        if trace.policy_hash != expected_policy_hash:
            raise ValueError(
                "Replay policy hash mismatch: "
                f"expected={expected_policy_hash} actual={trace.policy_hash} cycle={trace.cycle_index}"
            )

    @staticmethod
    def _to_cycle_report(selected_action: str | None, trace: DecisionTrace) -> ReplayCycleReport:
        selected_score = None
        if trace.selected_candidate is not None:
            selected_score = trace.selected_candidate.score_total

        return ReplayCycleReport(
            cycle_index=trace.cycle_index,
            selected_action=selected_action or "",
            selected_candidate_score=selected_score,
            veto=bool(trace.veto_events),
            candidates_mode=trace.candidates_mode,
            policy_name=trace.policy_name,
            policy_version=trace.policy_version,
            policy_hash=trace.policy_hash,
        )

    @staticmethod
    def _trace_signature(cycle: ReplayCycleReport, trace: DecisionTrace) -> tuple:
        candidate_signature = tuple(
            (
                candidate.action,
                _round_float(candidate.score_total),
                tuple(
                    sorted(
                        (str(key), _round_float(value))
                        for key, value in candidate.score_breakdown.items()
                    )
                ),
                _round_float(candidate.risk),
                _round_float(candidate.confidence),
            )
            for candidate in trace.all_candidates
        )

        objective_signature = (
            _round_float(trace.objective_used.stability_weight),
            _round_float(trace.objective_used.latency_weight),
            _round_float(trace.objective_used.cost_weight),
            _round_float(trace.objective_used.risk_budget),
        )

        selected_action = cycle.selected_action
        selected_score = (
            None
            if cycle.selected_candidate_score is None
            else _round_float(cycle.selected_candidate_score)
        )

        return (
            cycle.cycle_index,
            selected_action,
            selected_score,
            cycle.veto,
            cycle.candidates_mode,
            cycle.policy_name,
            cycle.policy_version,
            cycle.policy_hash,
            candidate_signature,
            objective_signature,
        )


def _round_float(value: float, digits: int = 9) -> float:
    return round(float(value), digits)
