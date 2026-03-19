from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from spice.protocols import Decision, Outcome, WorldState

try:
    from .incident_reducers import incident_snapshot, is_stable_incident
    from .incident_vocabulary import (
        ACTION_DISABLE_FEATURE_FLAG,
        ACTION_ESCALATE_HUMAN,
        ACTION_MONITOR,
        ACTION_REQUEST_HOTFIX,
        ACTION_ROLLBACK_RELEASE,
        DEFAULT_INCIDENT_ID,
        HIGH_ERROR_RATE_THRESHOLD,
        HIGH_LATENCY_P95_THRESHOLD,
        INCIDENT_ENTITY_ID,
        OUTCOME_INCIDENT_TRANSITION,
    )
except ImportError:
    from incident_reducers import incident_snapshot, is_stable_incident
    from incident_vocabulary import (
        ACTION_DISABLE_FEATURE_FLAG,
        ACTION_ESCALATE_HUMAN,
        ACTION_MONITOR,
        ACTION_REQUEST_HOTFIX,
        ACTION_ROLLBACK_RELEASE,
        DEFAULT_INCIDENT_ID,
        HIGH_ERROR_RATE_THRESHOLD,
        HIGH_LATENCY_P95_THRESHOLD,
        INCIDENT_ENTITY_ID,
        OUTCOME_INCIDENT_TRANSITION,
    )


@dataclass(frozen=True, slots=True)
class _HiddenTruth:
    """
    Internal simulator truth.

    This never leaves the simulator output.
    """

    root_cause: str = "feature_flag_regression"
    rollback_effective: bool = False
    disable_flag_effective: bool = True
    requires_hotfix: bool = True
    stable_error_rate: float = 0.006
    stable_latency_p95_ms: int = 180


class IncidentSimulator:
    """
    Deterministic incident simulator for Step 3.

    Determinism guarantee:
    same (state, decision, cycle_index, hidden_truth) => same Outcome
    """

    def __init__(self, *, hidden_truth: _HiddenTruth | None = None) -> None:
        self._hidden_truth = hidden_truth or _HiddenTruth()

    def simulate(
        self,
        state: WorldState,
        decision: Decision,
        *,
        cycle_index: int,
    ) -> Outcome:
        incident = _incident_from_state(state)
        action = str(decision.selected_action or ACTION_MONITOR)

        patch, status, attrs = self._transition(
            incident=incident,
            action=action,
            cycle_index=cycle_index,
        )
        attrs["incident_id"] = incident["incident_id"]
        attrs["action"] = action
        attrs["cycle_index"] = cycle_index

        return Outcome(
            id=f"outcome.sim.{cycle_index:03d}.{_action_slug(action)}",
            timestamp=_deterministic_timestamp(cycle_index),
            outcome_type=OUTCOME_INCIDENT_TRANSITION,
            status=status,
            decision_id=decision.id,
            changes={INCIDENT_ENTITY_ID: patch},
            refs=[state.id, decision.id],
            attributes=attrs,
            metadata={
                "simulator": "incident_simulator@0.3",
                "deterministic": True,
                "cycle_index": cycle_index,
            },
        )

    def _transition(
        self,
        *,
        incident: dict[str, Any],
        action: str,
        cycle_index: int,
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        truth = self._hidden_truth
        current_error = _as_float(incident.get("error_rate"), 0.0)
        current_latency = _as_int(incident.get("latency_p95_ms"), 0)

        if action == ACTION_ROLLBACK_RELEASE:
            if truth.rollback_effective:
                error_rate = max(truth.stable_error_rate * 1.5, 0.009)
                latency = max(truth.stable_latency_p95_ms + 40, 220)
                return (
                    {
                        "recent_deploy": False,
                        "mitigated_mode": True,
                        "error_rate": error_rate,
                        "latency_p95_ms": latency,
                        "incident_open": False,
                    },
                    "applied",
                    {
                        "post_error_rate": error_rate,
                        "post_latency_p95_ms": latency,
                        "incident_open": False,
                    },
                )

            # Default hidden truth: rollback does not mitigate this incident.
            error_rate = max(current_error, HIGH_ERROR_RATE_THRESHOLD + 0.07)
            latency = max(current_latency, HIGH_LATENCY_P95_THRESHOLD + 850)
            return (
                {
                    "recent_deploy": True,
                    "mitigated_mode": False,
                    "error_rate": error_rate,
                    "latency_p95_ms": latency,
                    "incident_open": True,
                },
                "failed",
                {
                    "post_error_rate": error_rate,
                    "post_latency_p95_ms": latency,
                    "incident_open": True,
                },
            )

        if action == ACTION_DISABLE_FEATURE_FLAG:
            if truth.disable_flag_effective:
                error_rate = truth.stable_error_rate
                latency = truth.stable_latency_p95_ms
                return (
                    {
                        "feature_flag_enabled": False,
                        "mitigated_mode": True,
                        "error_rate": error_rate,
                        "latency_p95_ms": latency,
                        "incident_open": False,
                    },
                    "applied",
                    {
                        "post_error_rate": error_rate,
                        "post_latency_p95_ms": latency,
                        "incident_open": False,
                    },
                )

            error_rate = max(current_error, HIGH_ERROR_RATE_THRESHOLD + 0.05)
            latency = max(current_latency, HIGH_LATENCY_P95_THRESHOLD + 700)
            return (
                {
                    "feature_flag_enabled": True,
                    "mitigated_mode": False,
                    "error_rate": error_rate,
                    "latency_p95_ms": latency,
                    "incident_open": True,
                },
                "failed",
                {
                    "post_error_rate": error_rate,
                    "post_latency_p95_ms": latency,
                    "incident_open": True,
                },
            )

        if action == ACTION_REQUEST_HOTFIX:
            status = "applied" if truth.requires_hotfix else "observed"
            return (
                {
                    "hotfix_requested": bool(truth.requires_hotfix),
                    "reenable_blocked": bool(truth.requires_hotfix),
                    "error_rate": current_error,
                    "latency_p95_ms": current_latency,
                    "incident_open": not is_stable_incident(incident),
                },
                status,
                {
                    "post_error_rate": current_error,
                    "post_latency_p95_ms": current_latency,
                    "incident_open": not is_stable_incident(incident),
                },
            )

        if action == ACTION_ESCALATE_HUMAN:
            return (
                {
                    "human_escalated": True,
                    "error_rate": current_error,
                    "latency_p95_ms": current_latency,
                    "incident_open": True,
                },
                "applied",
                {
                    "post_error_rate": current_error,
                    "post_latency_p95_ms": current_latency,
                    "incident_open": True,
                },
            )

        # ACTION_MONITOR and any unknown action: keep state projection unchanged.
        incident_open = not is_stable_incident(incident)
        return (
            {
                "error_rate": current_error,
                "latency_p95_ms": current_latency,
                "incident_open": incident_open,
            },
            "observed",
            {
                "post_error_rate": current_error,
                "post_latency_p95_ms": current_latency,
                "incident_open": incident_open,
            },
        )


def simulate_outcome(
    state: WorldState,
    decision: Decision,
    *,
    cycle_index: int,
    simulator: IncidentSimulator | None = None,
) -> Outcome:
    active_simulator = simulator or IncidentSimulator()
    return active_simulator.simulate(
        state,
        decision,
        cycle_index=cycle_index,
    )


def _incident_from_state(state: WorldState) -> dict[str, Any]:
    entity = state.entities.get(INCIDENT_ENTITY_ID)
    incident_id = DEFAULT_INCIDENT_ID
    if isinstance(entity, dict):
        value = entity.get("incident_id")
        if value:
            incident_id = str(value)
    return incident_snapshot(state, incident_id)


def _deterministic_timestamp(cycle_index: int) -> datetime:
    safe_cycle = cycle_index if cycle_index > 0 else 1
    anchor = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return anchor + timedelta(seconds=safe_cycle)


def _action_slug(action: str) -> str:
    return action.replace(".", "_")


def _as_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default
