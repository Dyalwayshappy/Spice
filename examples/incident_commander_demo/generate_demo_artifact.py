from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spice.core import SpiceRuntime
from spice.protocols import Observation, Outcome, WorldState
from spice.replay import ReplayRunner, load_replay_stream
from spice.shadow import compare

from examples.incident_commander_demo.incident_domain_pack import IncidentCommanderDomainPack
from examples.incident_commander_demo.incident_policies import (
    IncidentBaselinePolicy,
    IncidentContextAwarePolicy,
)
from examples.incident_commander_demo.incident_simulator import IncidentSimulator
from examples.incident_commander_demo.incident_vocabulary import (
    ACTION_DISABLE_FEATURE_FLAG,
    ACTION_MONITOR,
    ACTION_REQUEST_HOTFIX,
    ACTION_ROLLBACK_RELEASE,
)


REPLAY_PATH = THIS_DIR / "incident_replay_stream.jsonl"
ARTIFACT_PATH = THIS_DIR / "demo_timeline.json"
SCHEMA_VERSION = "0.1"


def main() -> int:
    observations = _load_observations(REPLAY_PATH)

    baseline_policy = IncidentBaselinePolicy()
    candidate_policy = IncidentContextAwarePolicy()

    baseline_run = _run_policy_path(observations, policy=baseline_policy)
    candidate_run = _run_policy_path(observations, policy=candidate_policy)

    shadow_report = compare(
        baseline_run["stream"],
        baseline_runtime_factory=lambda: _runtime(baseline_policy),
        candidate_runtime_factory=lambda: _runtime(candidate_policy),
        baseline_policy_hash=baseline_policy.identity.resolved_hash(),
        candidate_policy_hash=candidate_policy.identity.resolved_hash(),
        check_determinism=True,
    )

    cycles = _build_cycles(
        observations=observations,
        baseline_run=baseline_run,
        candidate_run=candidate_run,
    )
    divergent_cycle = _find_divergent_cycle_after_rollback_failure(cycles)
    proactive_cycle = _find_proactive_cycle(cycles)
    _apply_scene_labels(
        cycles=cycles,
        divergent_cycle=divergent_cycle,
        proactive_cycle=proactive_cycle,
    )

    baseline_cycles_to_stable = baseline_run["report"].cycles_to_stable
    candidate_cycles_to_stable = candidate_run["report"].cycles_to_stable
    proof_metric = _holds_improvement_metric(
        baseline_cycles_to_stable=baseline_cycles_to_stable,
        candidate_cycles_to_stable=candidate_cycles_to_stable,
    )

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "title": "Checkout Incident in 5 Cycles: Why History-Aware Decisions Win",
        "scenario_summary": (
            "A checkout incident starts after a deploy. Baseline keeps choosing rollback "
            "under unchanged high pressure. Candidate switches after rollback failure and "
            "takes one proactive hotfix step after stabilization."
        ),
        "proof_target": "candidate_cycles_to_stable < baseline_cycles_to_stable",
        "sources": {
            "replay_stream": str(REPLAY_PATH.name),
            "generator_script": str(Path(__file__).name),
            "observation_count": len(observations),
            "deterministic": True,
        },
        "baseline_replay_summary": _replay_summary(baseline_run),
        "candidate_replay_summary": _replay_summary(candidate_run),
        "shadow_summary": {
            "total_cycles": shadow_report.total_cycles,
            "divergence_rate": shadow_report.divergence_rate,
            "avg_score_delta": _round_float_or_none(shadow_report.avg_score_delta),
            "veto_divergence_count": shadow_report.veto_divergence_count,
            "baseline_deterministic": shadow_report.baseline_deterministic,
            "candidate_deterministic": shadow_report.candidate_deterministic,
            "baseline_determinism_message": shadow_report.baseline_determinism_message,
            "candidate_determinism_message": shadow_report.candidate_determinism_message,
        },
        "cycles": cycles,
        "baseline_cycles_to_stable": baseline_cycles_to_stable,
        "candidate_cycles_to_stable": candidate_cycles_to_stable,
        "divergent_cycle_after_rollback_failure": divergent_cycle,
        "proactive_request_hotfix_cycle": proactive_cycle,
        "proof_metric_candidate_lt_baseline": proof_metric,
        "final_proof_summary": _final_proof_summary(
            proof_metric=proof_metric,
            baseline_cycles_to_stable=baseline_cycles_to_stable,
            candidate_cycles_to_stable=candidate_cycles_to_stable,
        ),
    }

    with ARTIFACT_PATH.open("w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"generated={ARTIFACT_PATH}")
    print(
        "proof_metric_candidate_lt_baseline="
        f"{artifact['proof_metric_candidate_lt_baseline']}"
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


def _run_policy_path(
    observations: list[Observation],
    *,
    policy: IncidentBaselinePolicy | IncidentContextAwarePolicy,
) -> dict[str, Any]:
    runtime = _runtime(policy)
    simulator = IncidentSimulator()

    stream: list[Observation | Outcome] = []
    decisions: list[dict[str, Any]] = []
    outcomes: list[Outcome] = []
    stable_after_cycle: list[bool] = []

    for cycle_index, observation in enumerate(observations, start=1):
        state_after_observation = runtime.update_state(observation)
        decision = runtime.decide(state_after_observation)
        outcome = simulator.simulate(
            state_after_observation,
            decision,
            cycle_index=cycle_index,
        )
        state_after_outcome = runtime.update_state(outcome)
        stable_now = bool(runtime.domain_pack.is_stable(state_after_outcome))

        stream.extend([observation, outcome])
        decisions.append(
            {
                "cycle_index": cycle_index,
                "decision_id": decision.id,
                "action": decision.selected_action or "",
                "selected_candidate_id": str(
                    decision.attributes.get("selected_candidate_id", "")
                ),
            }
        )
        outcomes.append(outcome)
        stable_after_cycle.append(stable_now)

    replay_report = ReplayRunner(
        runtime_factory=lambda: _runtime(policy),
        stability_predicate=_is_stable_state,
    ).replay(
        stream,
        pinned_policy_hash=policy.identity.resolved_hash(),
        check_determinism=True,
    )

    return {
        "policy": policy,
        "stream": stream,
        "report": replay_report,
        "decisions": decisions,
        "outcomes": outcomes,
        "stable_after_cycle": stable_after_cycle,
    }


def _is_stable_state(state: WorldState) -> bool:
    pack = IncidentCommanderDomainPack()
    return bool(pack.is_stable(state))


def _replay_summary(run: dict[str, Any]) -> dict[str, Any]:
    policy = run["policy"]
    report = run["report"]
    return {
        "policy_name": policy.identity.policy_name,
        "policy_version": policy.identity.policy_version,
        "policy_hash": policy.identity.resolved_hash(),
        "total_cycles": report.total_cycles,
        "cycles_to_stable": report.cycles_to_stable,
        "deterministic": report.deterministic,
        "determinism_message": report.determinism_message,
        "action_sequence": [cycle.selected_action for cycle in report.cycles],
        "action_sequence_text": " -> ".join(
            f"{cycle.cycle_index}:{cycle.selected_action}" for cycle in report.cycles
        ),
    }


def _build_cycles(
    *,
    observations: list[Observation],
    baseline_run: dict[str, Any],
    candidate_run: dict[str, Any],
) -> list[dict[str, Any]]:
    cycles: list[dict[str, Any]] = []
    for idx, observation in enumerate(observations, start=1):
        baseline_decision = baseline_run["decisions"][idx - 1]
        candidate_decision = candidate_run["decisions"][idx - 1]

        previous_baseline_outcome = (
            baseline_run["outcomes"][idx - 2] if idx > 1 else None
        )
        previous_candidate_outcome = (
            candidate_run["outcomes"][idx - 2] if idx > 1 else None
        )

        baseline_action = str(baseline_decision["action"])
        candidate_action = str(candidate_decision["action"])

        cycles.append(
            {
                "cycle_index": idx,
                "observation_id": observation.id,
                "observed_signal_summary": _observed_signal_summary(observation),
                "previous_outcome_summary": {
                    "baseline": _outcome_summary(previous_baseline_outcome),
                    "candidate": _outcome_summary(previous_candidate_outcome),
                },
                "baseline_action": baseline_action,
                "candidate_action": candidate_action,
                "divergence": baseline_action != candidate_action,
                "proactive": candidate_action == ACTION_REQUEST_HOTFIX,
                "stable_after_cycle": {
                    "baseline": bool(baseline_run["stable_after_cycle"][idx - 1]),
                    "candidate": bool(candidate_run["stable_after_cycle"][idx - 1]),
                },
                "scene_label": "",
            }
        )
    return cycles


def _observed_signal_summary(observation: Observation) -> dict[str, Any]:
    attrs = observation.attributes
    return {
        "observation_type": observation.observation_type,
        "service": str(attrs.get("service", "")),
        "severity": str(attrs.get("severity", "")),
        "error_rate": _as_float(attrs.get("error_rate")),
        "latency_p95_ms": _as_int(attrs.get("latency_p95_ms")),
        "feature_flag_enabled": _as_bool(attrs.get("feature_flag_enabled")),
        "recent_deploy": _as_bool(attrs.get("recent_deploy")),
    }


def _outcome_summary(outcome: Outcome | None) -> dict[str, Any] | None:
    if outcome is None:
        return None

    changes = outcome.changes.get("incident.current", {})
    patch = changes if isinstance(changes, dict) else {}
    return {
        "outcome_id": outcome.id,
        "status": outcome.status,
        "action": str(outcome.attributes.get("action", "")),
        "error_rate": _as_float(patch.get("error_rate")),
        "latency_p95_ms": _as_int(patch.get("latency_p95_ms")),
        "incident_open": _as_bool(patch.get("incident_open")),
        "human_summary": _outcome_human_summary(outcome, patch),
    }


def _outcome_human_summary(outcome: Outcome, patch: dict[str, Any]) -> str:
    action = str(outcome.attributes.get("action", ""))
    status = outcome.status
    incident_open = _as_bool(patch.get("incident_open"))

    if action == ACTION_ROLLBACK_RELEASE and status == "failed":
        return "Rollback failed; service still unstable."
    if action == ACTION_DISABLE_FEATURE_FLAG and status in {"applied", "success"}:
        if incident_open is False:
            return "Feature flag disabled; service recovered."
        return "Feature flag disabled, but service is still unstable."
    if action == ACTION_REQUEST_HOTFIX and status in {"applied", "observed", "success"}:
        return "Hotfix requested after stabilization."
    if action == ACTION_MONITOR:
        if incident_open is False:
            return "Monitoring only; service remains stable."
        return "Monitoring only; service still unstable."
    if status == "failed":
        return f"{_humanize_action(action)} failed; service still unstable."

    return f"{_humanize_action(action)} {status}."


def _find_divergent_cycle_after_rollback_failure(cycles: list[dict[str, Any]]) -> int | None:
    for cycle in cycles:
        if not cycle["divergence"]:
            continue
        previous = cycle["previous_outcome_summary"].get("baseline")
        if not isinstance(previous, dict):
            continue
        if previous.get("status") != "failed":
            continue
        if previous.get("action") != ACTION_ROLLBACK_RELEASE:
            continue
        if cycle.get("candidate_action") == ACTION_ROLLBACK_RELEASE:
            continue
        return int(cycle["cycle_index"])
    return None


def _find_proactive_cycle(cycles: list[dict[str, Any]]) -> int | None:
    for cycle in cycles:
        if bool(cycle.get("proactive")):
            return int(cycle["cycle_index"])
    return None


def _apply_scene_labels(
    *,
    cycles: list[dict[str, Any]],
    divergent_cycle: int | None,
    proactive_cycle: int | None,
) -> None:
    total = len(cycles)
    for cycle in cycles:
        idx = int(cycle["cycle_index"])
        if idx == 1:
            label = "Trigger"
        elif idx == total:
            label = "Proof Complete"
        elif divergent_cycle is not None and idx == divergent_cycle:
            label = "Divergence"
        elif proactive_cycle is not None and idx == proactive_cycle:
            label = "Proactive Closure"
        elif bool(cycle.get("stable_after_cycle", {}).get("candidate")):
            label = "Monitoring"
        else:
            label = "Ongoing Pressure"
        cycle["scene_label"] = label


def _holds_improvement_metric(
    *,
    baseline_cycles_to_stable: int | None,
    candidate_cycles_to_stable: int | None,
) -> bool:
    baseline = math.inf if baseline_cycles_to_stable is None else float(baseline_cycles_to_stable)
    candidate = math.inf if candidate_cycles_to_stable is None else float(candidate_cycles_to_stable)
    return candidate < baseline


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
        return None
    return bool(value)


def _round_float_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _humanize_action(action: str) -> str:
    if not action:
        return "Action"
    token = action.split(".")[-1].replace("_", " ")
    return token.capitalize()


def _final_proof_summary(
    *,
    proof_metric: bool,
    baseline_cycles_to_stable: int | None,
    candidate_cycles_to_stable: int | None,
) -> str:
    baseline_text = "not reached" if baseline_cycles_to_stable is None else str(baseline_cycles_to_stable)
    candidate_text = "not reached" if candidate_cycles_to_stable is None else str(candidate_cycles_to_stable)

    if proof_metric:
        return (
            "Candidate stabilized faster and performed one proactive follow-up step "
            f"(candidate={candidate_text}, baseline={baseline_text})."
        )
    return (
        "Candidate did not beat baseline stabilization speed in this run "
        f"(candidate={candidate_text}, baseline={baseline_text})."
    )


if __name__ == "__main__":
    raise SystemExit(main())
