from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Iterable

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spice.core import SpiceRuntime
from spice.protocols import Observation, Outcome, WorldState
from spice.replay import ReplayRunner, load_replay_stream
from spice.shadow import compare
from spice.shadow.types import ShadowCycleDiff

from examples.incident_commander_demo.incident_domain_pack import IncidentCommanderDomainPack
from examples.incident_commander_demo.incident_policies import (
    IncidentBaselinePolicy,
    IncidentContextAwarePolicy,
)
from examples.incident_commander_demo.incident_simulator import IncidentSimulator
from examples.incident_commander_demo.incident_vocabulary import (
    ACTION_REQUEST_HOTFIX,
    ACTION_ROLLBACK_RELEASE,
)


REPLAY_PATH = THIS_DIR / "incident_replay_stream.jsonl"


def main() -> int:
    baseline_policy = IncidentBaselinePolicy()
    candidate_policy = IncidentContextAwarePolicy()

    observations = _load_observations(REPLAY_PATH)

    baseline_stream = _build_simulated_stream(observations, policy=baseline_policy)
    candidate_stream = _build_simulated_stream(observations, policy=candidate_policy)

    baseline_report = _run_replay(baseline_stream, baseline_policy)
    candidate_report = _run_replay(candidate_stream, candidate_policy)

    # Shared-stream shadow compare to expose cycle-level policy divergence.
    shadow_report = compare(
        baseline_stream,
        baseline_runtime_factory=lambda: _runtime(baseline_policy),
        candidate_runtime_factory=lambda: _runtime(candidate_policy),
        baseline_policy_hash=baseline_policy.identity.resolved_hash(),
        candidate_policy_hash=candidate_policy.identity.resolved_hash(),
        check_determinism=True,
    )

    baseline_actions = _format_action_sequence(baseline_report.cycles)
    candidate_actions = _format_action_sequence(candidate_report.cycles)
    divergent_cycle = _find_divergent_cycle_from_rollback_failure(
        shadow_report.cycles,
        baseline_stream,
    )
    hotfix_cycle = _find_action_cycle(candidate_report.cycles, ACTION_REQUEST_HOTFIX)

    print("Incident Commander Shadow Compare")
    print(f"replay_file={REPLAY_PATH.name} observations={len(observations)}")
    print(f"baseline_cycles_to_stable={_format_cycles(baseline_report.cycles_to_stable)}")
    print(f"candidate_cycles_to_stable={_format_cycles(candidate_report.cycles_to_stable)}")
    print(f"baseline_action_sequence={baseline_actions}")
    print(f"candidate_action_sequence={candidate_actions}")
    print(f"proactive_request_hotfix_cycle={_format_cycles(hotfix_cycle)}")

    if divergent_cycle is None:
        print("divergent_cycle_after_rollback_failure=not_found")
    else:
        print(
            "divergent_cycle_after_rollback_failure="
            f"{divergent_cycle.cycle_index} "
            f"(baseline={divergent_cycle.baseline_action}, "
            f"candidate={divergent_cycle.candidate_action})"
        )

    proof_holds = _proof_metric_holds(
        baseline_cycles_to_stable=baseline_report.cycles_to_stable,
        candidate_cycles_to_stable=candidate_report.cycles_to_stable,
    )
    print(
        "proof_metric_candidate_lt_baseline="
        f"{proof_holds}"
    )
    return 0


def _runtime(policy: IncidentBaselinePolicy | IncidentContextAwarePolicy) -> SpiceRuntime:
    return SpiceRuntime(
        domain_pack=IncidentCommanderDomainPack(),
        decision_policy=policy,
    )


def _load_observations(path: Path) -> list[Observation]:
    records = load_replay_stream(path)
    return [record for record in records if isinstance(record, Observation)]


def _build_simulated_stream(
    observations: Iterable[Observation],
    *,
    policy: IncidentBaselinePolicy | IncidentContextAwarePolicy,
) -> list[Observation | Outcome]:
    runtime = _runtime(policy)
    simulator = IncidentSimulator()
    records: list[Observation | Outcome] = []

    for cycle_index, observation in enumerate(observations, start=1):
        state = runtime.update_state(observation)
        decision = runtime.decide(state)
        outcome = simulator.simulate(
            state,
            decision,
            cycle_index=cycle_index,
        )
        runtime.update_state(outcome)
        records.extend([observation, outcome])

    return records


def _run_replay(
    records: Iterable[Observation | Outcome],
    policy: IncidentBaselinePolicy | IncidentContextAwarePolicy,
):
    return ReplayRunner(
        runtime_factory=lambda: _runtime(policy),
        stability_predicate=_is_stable_state,
    ).replay(
        records,
        pinned_policy_hash=policy.identity.resolved_hash(),
        check_determinism=True,
    )


def _is_stable_state(state: WorldState) -> bool:
    pack = IncidentCommanderDomainPack()
    return bool(pack.is_stable(state))


def _find_divergent_cycle_from_rollback_failure(
    cycles: list[ShadowCycleDiff],
    shared_stream: list[Observation | Outcome],
) -> ShadowCycleDiff | None:
    outcomes = [record for record in shared_stream if isinstance(record, Outcome)]
    for cycle in cycles:
        if not cycle.action_diverged:
            continue
        if cycle.cycle_index < 2:
            continue

        previous_outcome_index = cycle.cycle_index - 2
        if previous_outcome_index >= len(outcomes):
            continue

        previous_outcome = outcomes[previous_outcome_index]
        previous_action = str(previous_outcome.attributes.get("action", ""))
        if previous_outcome.status == "failed" and previous_action == ACTION_ROLLBACK_RELEASE:
            return cycle
    return None


def _find_action_cycle(cycles: list, action: str) -> int | None:
    for cycle in cycles:
        if cycle.selected_action == action:
            return cycle.cycle_index
    return None


def _proof_metric_holds(
    *,
    baseline_cycles_to_stable: int | None,
    candidate_cycles_to_stable: int | None,
) -> bool:
    baseline = _normalized_cycle_value(baseline_cycles_to_stable)
    candidate = _normalized_cycle_value(candidate_cycles_to_stable)
    return candidate < baseline


def _normalized_cycle_value(value: int | None) -> float:
    if value is None:
        return math.inf
    return float(value)


def _format_cycles(value: int | None) -> str:
    if value is None:
        return "not_reached"
    return str(value)


def _format_action_sequence(cycles: list) -> str:
    if not cycles:
        return "none"
    return " -> ".join(f"{cycle.cycle_index}:{cycle.selected_action}" for cycle in cycles)


if __name__ == "__main__":
    raise SystemExit(main())
