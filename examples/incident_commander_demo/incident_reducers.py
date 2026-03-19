from __future__ import annotations

from typing import Any

from spice.protocols import DeltaOp, Observation, Outcome, WorldDelta, WorldState

try:
    from .incident_vocabulary import (
        ACTION_DISABLE_FEATURE_FLAG,
        ACTION_ESCALATE_HUMAN,
        ACTION_REQUEST_HOTFIX,
        ACTION_ROLLBACK_RELEASE,
        DEFAULT_INCIDENT_ID,
        HIGH_ERROR_RATE_THRESHOLD,
        HIGH_LATENCY_P95_THRESHOLD,
        INCIDENT_DOMAIN_NAME,
        INCIDENT_ENTITY_ID,
        STABLE_ERROR_RATE_MAX,
        STABLE_LATENCY_P95_MAX,
    )
except ImportError:
    from incident_vocabulary import (
        ACTION_DISABLE_FEATURE_FLAG,
        ACTION_ESCALATE_HUMAN,
        ACTION_REQUEST_HOTFIX,
        ACTION_ROLLBACK_RELEASE,
        DEFAULT_INCIDENT_ID,
        HIGH_ERROR_RATE_THRESHOLD,
        HIGH_LATENCY_P95_THRESHOLD,
        INCIDENT_DOMAIN_NAME,
        INCIDENT_ENTITY_ID,
        STABLE_ERROR_RATE_MAX,
        STABLE_LATENCY_P95_MAX,
    )


SUCCESS_STATUSES = {"applied", "success", "observed"}
FAILURE_STATUSES = {"failed", "rejected", "timeout"}

VISIBLE_OUTCOME_FIELDS = {
    "service",
    "severity",
    "error_rate",
    "latency_p95_ms",
    "release_id",
    "feature_flag_enabled",
    "recent_deploy",
    "incident_open",
    "mitigated_mode",
    "hotfix_requested",
    "human_escalated",
    "reenable_blocked",
}

NUMERIC_FLOAT_FIELDS = {"error_rate"}
NUMERIC_INT_FIELDS = {"latency_p95_ms"}
BOOLEAN_FIELDS = {
    "feature_flag_enabled",
    "recent_deploy",
    "incident_open",
    "mitigated_mode",
    "hotfix_requested",
    "human_escalated",
    "reenable_blocked",
}

OBSERVATION_CONFLICT_FIELDS = {
    "error_rate",
    "latency_p95_ms",
    "release_id",
    "feature_flag_enabled",
    "recent_deploy",
    "incident_open",
}


def observation_to_delta(state: WorldState, observation: Observation) -> WorldDelta:
    """Deterministically reduce one observation into a WorldDelta."""
    attrs = dict(observation.attributes)
    incident_id = str(
        attrs.get("incident_id")
        or _incident_id_from_state(state)
        or DEFAULT_INCIDENT_ID
    )
    incident = incident_snapshot(state, incident_id)

    # Update only fields explicitly present in this observation.
    if "service" in attrs:
        incident["service"] = str(attrs.get("service") or "")
    if "severity" in attrs:
        incident["severity"] = str(attrs.get("severity") or "")
    if "release_id" in attrs:
        release_id = str(attrs.get("release_id") or "")
        _observation_update_field(
            incident,
            field="release_id",
            value=release_id,
            observed_field="observed_release_id",
        )
    if "error_rate" in attrs:
        error_rate = _as_float(attrs.get("error_rate"), incident["observed_error_rate"])
        _observation_update_field(
            incident,
            field="error_rate",
            value=error_rate,
            observed_field="observed_error_rate",
        )
    if "latency_p95_ms" in attrs:
        latency = _as_int(attrs.get("latency_p95_ms"), incident["observed_latency_p95_ms"])
        _observation_update_field(
            incident,
            field="latency_p95_ms",
            value=latency,
            observed_field="observed_latency_p95_ms",
        )
    if "feature_flag_enabled" in attrs:
        feature_flag_enabled = _as_bool(
            attrs.get("feature_flag_enabled"),
            incident["observed_feature_flag_enabled"],
        )
        _observation_update_field(
            incident,
            field="feature_flag_enabled",
            value=feature_flag_enabled,
            observed_field="observed_feature_flag_enabled",
        )
    if "recent_deploy" in attrs:
        recent_deploy = _as_bool(attrs.get("recent_deploy"), incident["recent_deploy"])
        _observation_update_field(incident, field="recent_deploy", value=recent_deploy)
    if "incident_open" in attrs:
        incident_open = _as_bool(attrs.get("incident_open"), incident["observed_incident_open"])
        _observation_update_field(
            incident,
            field="incident_open",
            value=incident_open,
            observed_field="observed_incident_open",
        )

    incident["last_observation_id"] = observation.id

    signal_value: dict[str, Any] = {
        "kind": observation.observation_type,
        "incident_id": incident_id,
        "source": observation.source,
    }
    if "error_rate" in attrs:
        signal_value["error_rate"] = incident["observed_error_rate"]
    if "latency_p95_ms" in attrs:
        signal_value["latency_p95_ms"] = incident["observed_latency_p95_ms"]

    return WorldDelta(
        id=f"delta.observation.{observation.id}",
        source_kind="observation",
        source_id=observation.id,
        entity_ops=[DeltaOp(op="upsert", id=INCIDENT_ENTITY_ID, value=incident)],
        signal_ops=[
            DeltaOp(
                op="upsert",
                id=f"signal.event.{observation.id}",
                value=signal_value,
            )
        ],
        resource_patch={
            "observation_count": _as_int(state.resources.get("observation_count"), 0) + 1
        },
        provenance_patch={
            "last_observation_id": observation.id,
            "last_observation_kind": observation.observation_type,
        },
        domain_patch={
            INCIDENT_DOMAIN_NAME: {
                "last_incident_id": incident_id,
                "last_observation_kind": observation.observation_type,
                "is_high_pressure": is_high_pressure(incident),
            }
        },
    )


def outcome_to_delta(state: WorldState, outcome: Outcome) -> WorldDelta:
    """Deterministically reduce one outcome into a WorldDelta."""
    attrs = dict(outcome.attributes)
    incident_id = str(
        attrs.get("incident_id")
        or _incident_id_from_state(state)
        or DEFAULT_INCIDENT_ID
    )
    incident = incident_snapshot(state, incident_id)

    action = str(attrs.get("action") or "")
    if action:
        incident["last_action"] = action
        incident["last_action_status"] = outcome.status
        if outcome.status in SUCCESS_STATUSES:
            incident["successful_actions"] = _append_unique(incident["successful_actions"], action)
        elif outcome.status in FAILURE_STATUSES:
            incident["failed_actions"] = _append_unique(incident["failed_actions"], action)

    applied_fields: set[str] = set()

    visible_patch = _extract_visible_outcome_patch(outcome)
    for field in sorted(visible_patch):
        incident[field] = _normalize_field_value(field, visible_patch[field], incident.get(field))
        applied_fields.add(field)

    action_effects = _derive_action_effects(action, outcome.status, attrs)
    for field in sorted(action_effects):
        if field in visible_patch:
            continue
        incident[field] = _normalize_field_value(field, action_effects[field], incident.get(field))
        applied_fields.add(field)

    # If mitigation stabilizes the incident, close it unless explicitly overridden.
    if "incident_open" not in applied_fields and is_stable_incident(incident):
        incident["incident_open"] = False
        applied_fields.add("incident_open")

    if applied_fields:
        owners = set(incident["outcome_owned_fields"])
        owners.update(applied_fields)
        incident["outcome_owned_fields"] = sorted(owners)

    incident["last_outcome_id"] = outcome.id

    return WorldDelta(
        id=f"delta.outcome.{outcome.id}",
        source_kind="outcome",
        source_id=outcome.id,
        entity_ops=[DeltaOp(op="upsert", id=INCIDENT_ENTITY_ID, value=incident)],
        provenance_patch={
            "last_outcome_id": outcome.id,
            "last_decision_id": outcome.decision_id,
        },
        confidence_patch={"latest_outcome_status": outcome.status},
        recent_outcome_additions=[
            {
                "outcome_id": outcome.id,
                "decision_id": outcome.decision_id,
                "status": outcome.status,
                "action": action,
                "incident_id": incident_id,
                "applied_fields": sorted(applied_fields),
            }
        ],
        domain_patch={
            INCIDENT_DOMAIN_NAME: {
                "last_incident_id": incident_id,
                "last_action": action,
                "last_outcome_status": outcome.status,
                "is_stable": is_stable_incident(incident),
            }
        },
    )


def incident_snapshot(state: WorldState, incident_id: str) -> dict[str, Any]:
    existing = state.entities.get(INCIDENT_ENTITY_ID)
    snapshot = dict(existing) if isinstance(existing, dict) else {}

    snapshot["kind"] = "incident"
    snapshot["incident_id"] = str(
        incident_id
        or snapshot.get("incident_id")
        or DEFAULT_INCIDENT_ID
    )
    snapshot["service"] = str(snapshot.get("service") or "")
    snapshot["severity"] = str(snapshot.get("severity") or "")

    snapshot["error_rate"] = _as_float(snapshot.get("error_rate"), 0.0)
    snapshot["latency_p95_ms"] = _as_int(snapshot.get("latency_p95_ms"), 0)
    snapshot["observed_error_rate"] = _as_float(
        snapshot.get("observed_error_rate"),
        snapshot["error_rate"],
    )
    snapshot["observed_latency_p95_ms"] = _as_int(
        snapshot.get("observed_latency_p95_ms"),
        snapshot["latency_p95_ms"],
    )

    snapshot["release_id"] = str(snapshot.get("release_id") or "")
    snapshot["observed_release_id"] = str(
        snapshot.get("observed_release_id")
        or snapshot["release_id"]
    )
    snapshot["feature_flag_enabled"] = _as_bool(snapshot.get("feature_flag_enabled"), True)
    snapshot["observed_feature_flag_enabled"] = _as_bool(
        snapshot.get("observed_feature_flag_enabled"),
        snapshot["feature_flag_enabled"],
    )
    snapshot["recent_deploy"] = _as_bool(snapshot.get("recent_deploy"), False)
    snapshot["incident_open"] = _as_bool(snapshot.get("incident_open"), True)
    snapshot["observed_incident_open"] = _as_bool(
        snapshot.get("observed_incident_open"),
        snapshot["incident_open"],
    )

    snapshot["failed_actions"] = _as_str_list(snapshot.get("failed_actions"))
    snapshot["successful_actions"] = _as_str_list(snapshot.get("successful_actions"))
    snapshot["last_action"] = str(snapshot.get("last_action") or "")
    snapshot["last_action_status"] = str(snapshot.get("last_action_status") or "")

    snapshot["mitigated_mode"] = _as_bool(snapshot.get("mitigated_mode"), False)
    snapshot["hotfix_requested"] = _as_bool(snapshot.get("hotfix_requested"), False)
    snapshot["human_escalated"] = _as_bool(snapshot.get("human_escalated"), False)
    snapshot["reenable_blocked"] = _as_bool(snapshot.get("reenable_blocked"), False)

    snapshot["last_observation_id"] = str(snapshot.get("last_observation_id") or "")
    snapshot["last_outcome_id"] = str(snapshot.get("last_outcome_id") or "")
    snapshot["outcome_owned_fields"] = _normalize_field_owners(
        snapshot.get("outcome_owned_fields")
    )

    return snapshot


def is_high_pressure(incident: dict[str, Any]) -> bool:
    error_rate = _as_float(incident.get("error_rate"), 0.0)
    latency_p95 = _as_int(incident.get("latency_p95_ms"), 0)
    return (
        error_rate >= HIGH_ERROR_RATE_THRESHOLD
        or latency_p95 >= HIGH_LATENCY_P95_THRESHOLD
    )


def is_stable_incident(incident: dict[str, Any]) -> bool:
    error_rate = _as_float(incident.get("error_rate"), 0.0)
    latency_p95 = _as_int(incident.get("latency_p95_ms"), 0)
    return (
        error_rate <= STABLE_ERROR_RATE_MAX
        and latency_p95 <= STABLE_LATENCY_P95_MAX
    )


def is_stable(state: WorldState) -> bool:
    entity = state.entities.get(INCIDENT_ENTITY_ID)
    if not isinstance(entity, dict):
        return False
    return is_stable_incident(entity)


def _incident_id_from_state(state: WorldState) -> str:
    entity = state.entities.get(INCIDENT_ENTITY_ID)
    if isinstance(entity, dict):
        value = entity.get("incident_id")
        if value:
            return str(value)
    return ""


def _observation_update_field(
    incident: dict[str, Any],
    *,
    field: str,
    value: Any,
    observed_field: str | None = None,
) -> None:
    if observed_field:
        incident[observed_field] = value

    if field in OBSERVATION_CONFLICT_FIELDS:
        owners = set(incident.get("outcome_owned_fields", []))
        if field in owners:
            return
    incident[field] = value


def _extract_visible_outcome_patch(outcome: Outcome) -> dict[str, Any]:
    patch = outcome.changes.get(INCIDENT_ENTITY_ID)
    if not isinstance(patch, dict):
        return {}
    return {
        str(field): value
        for field, value in patch.items()
        if str(field) in VISIBLE_OUTCOME_FIELDS
    }


def _derive_action_effects(
    action: str,
    status: str,
    attrs: dict[str, Any],
) -> dict[str, Any]:
    if status not in SUCCESS_STATUSES:
        return {}

    effects: dict[str, Any] = {}

    if action == ACTION_ROLLBACK_RELEASE:
        effects["recent_deploy"] = False
        effects["mitigated_mode"] = True
    elif action == ACTION_DISABLE_FEATURE_FLAG:
        effects["feature_flag_enabled"] = False
        effects["mitigated_mode"] = True
    elif action == ACTION_REQUEST_HOTFIX:
        effects["hotfix_requested"] = True
    elif action == ACTION_ESCALATE_HUMAN:
        effects["human_escalated"] = True

    if "post_error_rate" in attrs:
        effects["error_rate"] = attrs.get("post_error_rate")
    if "post_latency_p95_ms" in attrs:
        effects["latency_p95_ms"] = attrs.get("post_latency_p95_ms")
    if "incident_open" in attrs:
        effects["incident_open"] = attrs.get("incident_open")

    return {field: value for field, value in effects.items() if field in VISIBLE_OUTCOME_FIELDS}


def _normalize_field_value(field: str, value: Any, default: Any) -> Any:
    if field in NUMERIC_FLOAT_FIELDS:
        return _as_float(value, _as_float(default, 0.0))
    if field in NUMERIC_INT_FIELDS:
        return _as_int(value, _as_int(default, 0))
    if field in BOOLEAN_FIELDS:
        return _as_bool(value, _as_bool(default, False))
    if value is None:
        return str(default or "")
    return str(value)


def _normalize_field_owners(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = [str(item) for item in value if str(item) in VISIBLE_OUTCOME_FIELDS]
    return sorted(set(normalized))


def _append_unique(value: Any, item: str) -> list[str]:
    existing = _as_str_list(value)
    if item and item not in existing:
        existing.append(item)
    return existing


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


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


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
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
        return default
    return bool(value)
