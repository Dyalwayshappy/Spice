from __future__ import annotations

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

from examples.incident_commander_demo.incident_domain_pack import IncidentCommanderDomainPack
from examples.incident_commander_demo.incident_policies import IncidentContextAwarePolicy
from examples.incident_commander_demo.incident_simulator import IncidentSimulator
from examples.incident_commander_demo.incident_vocabulary import (
    ACTION_REQUEST_HOTFIX,
    ACTION_ROLLBACK_RELEASE,
)


REPLAY_PATH = THIS_DIR / "incident_replay_stream.jsonl"


def main() -> int:
    policy = IncidentContextAwarePolicy()
    observations = _load_observations(REPLAY_PATH)
    stream = _build_simulated_stream(observations, policy=policy)

    report = ReplayRunner(
        runtime_factory=lambda: _runtime(policy),
        stability_predicate=_is_stable_state,
    ).replay(
        stream,
        pinned_policy_hash=policy.identity.resolved_hash(),
        check_determinism=True,
    )

    outcomes = [record for record in stream if isinstance(record, Outcome)]
    switch_cycle = _find_rollback_failure_switch_cycle(report.cycles, outcomes)
    hotfix_cycle = _find_action_cycle(report.cycles, ACTION_REQUEST_HOTFIX)

    print("Incident Commander Replay: candidate")
    print(
        f"policy={policy.identity.policy_name}@{policy.identity.policy_version} "
        f"hash={policy.identity.resolved_hash()}"
    )
    print(f"observations={len(observations)} records={len(stream)}")
    print(f"candidate_cycles_to_stable={_format_cycles(report.cycles_to_stable)}")
    print(f"cycle_action_sequence={_format_action_sequence(report.cycles)}")
    print(f"rollback_failure_switch_cycle={_format_cycles(switch_cycle)}")
    print(f"proactive_request_hotfix_cycle={_format_cycles(hotfix_cycle)}")
    return 0


def _runtime(policy: IncidentContextAwarePolicy) -> SpiceRuntime:
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
    policy: IncidentContextAwarePolicy,
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


def _is_stable_state(state: WorldState) -> bool:
    pack = IncidentCommanderDomainPack()
    return bool(pack.is_stable(state))


def _find_rollback_failure_switch_cycle(cycles: list, outcomes: list[Outcome]) -> int | None:
    for index, cycle in enumerate(cycles, start=1):
        if index < 2:
            continue
        if index - 2 >= len(outcomes):
            continue

        previous_outcome = outcomes[index - 2]
        previous_action = str(previous_outcome.attributes.get("action", ""))
        if previous_outcome.status != "failed":
            continue
        if previous_action != ACTION_ROLLBACK_RELEASE:
            continue
        if cycle.selected_action == ACTION_ROLLBACK_RELEASE:
            continue
        return cycle.cycle_index
    return None


def _find_action_cycle(cycles: list, action: str) -> int | None:
    for cycle in cycles:
        if cycle.selected_action == action:
            return cycle.cycle_index
    return None


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
