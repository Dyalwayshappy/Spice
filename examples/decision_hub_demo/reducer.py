from __future__ import annotations

from hashlib import sha256
from typing import Any

from spice.protocols.observation import Observation
from spice.protocols.world_delta import WorldDelta, apply_delta
from spice.protocols.world_state import WorldState

from examples.decision_hub_demo.state import (
    DOMAIN_KEY,
    ensure_demo_state,
    isoformat_utc,
    parse_time,
    stable_slug,
    utc_now,
)


def ingest_observation(state: WorldState, observation: Observation) -> WorldState:
    """Apply one demo-domain observation to WorldState.

    The reducer updates facts only. It does not detect conflicts, recommend
    actions, or decide whether a fact matters to a decision.
    """

    ensure_demo_state(state)
    delta = reduce_observation(state, observation)
    return apply_delta(state, delta)


def reduce_observation(state: WorldState, observation: Observation) -> WorldDelta:
    if observation.observation_type == "commitment_declared":
        return _reduce_commitment_declared(observation)
    if observation.observation_type == "work_item_opened":
        return _reduce_work_item_opened(observation)
    if observation.observation_type == "executor_capability_observed":
        return _reduce_executor_capability_observed(observation)
    if observation.observation_type == "execution_result_observed":
        return _reduce_execution_result_observed(state, observation)
    return WorldDelta(
        id=f"delta.ignored.{observation.id}",
        source_id=observation.id,
        domain_patch={DOMAIN_KEY: {"history_summary": {"ignored_observation_type": observation.observation_type}}},
    )


def _reduce_commitment_declared(observation: Observation) -> WorldDelta:
    attrs = observation.attributes
    commitment_id = str(
        attrs.get("commitment_id")
        or f"commitment.{_short_hash(observation.id, attrs.get('summary', ''))}"
    )
    commitment = {
        "id": commitment_id,
        "summary": str(attrs.get("summary", "Untitled commitment")),
        "start_time": _time_or_none(attrs.get("start_time")),
        "end_time": _time_or_none(attrs.get("end_time")),
        "duration_minutes": attrs.get("duration_minutes"),
        "prep_start_time": _time_or_none(attrs.get("prep_start_time")),
        "priority_hint": attrs.get("priority_hint", "normal"),
        "flexibility_hint": attrs.get("flexibility_hint", "fixed"),
        "constraint_hints": list(attrs.get("constraint_hints", []) or []),
        "source_observation_id": observation.id,
        "source": observation.source,
        "confidence": _confidence(observation),
    }
    return WorldDelta(
        id=f"delta.{commitment_id}",
        source_id=observation.id,
        domain_patch={DOMAIN_KEY: {"commitments": {commitment_id: commitment}}},
        provenance_patch={commitment_id: {"observation_id": observation.id, "source": observation.source}},
        confidence_patch={commitment_id: commitment["confidence"]},
    )


def _reduce_work_item_opened(observation: Observation) -> WorldDelta:
    attrs = observation.attributes
    repo = str(attrs.get("repo", "unknown"))
    item_id = str(attrs.get("item_id", attrs.get("id", "unknown")))
    kind = str(attrs.get("kind", "work_item"))
    work_item_id = str(
        attrs.get("work_item_id")
        or f"workitem.{observation.source or 'unknown'}.{stable_slug(repo)}.{stable_slug(item_id)}"
    )
    work_item = {
        "id": work_item_id,
        "kind": kind,
        "repo": repo,
        "item_id": item_id,
        "title": str(attrs.get("title", "Untitled work item")),
        "url": attrs.get("url"),
        "action": attrs.get("action", "opened"),
        "status": "open",
        "requires_attention": bool(attrs.get("requires_attention", True)),
        "urgency_hint": attrs.get("urgency_hint", "medium"),
        "estimated_minutes_hint": int(attrs.get("estimated_minutes_hint") or 30),
        "event_key": attrs.get("event_key"),
        "opened_at": _time_or_none(attrs.get("opened_at")) or _time_or_none(observation.timestamp),
        "source_observation_id": observation.id,
        "source": observation.source,
        "confidence": _confidence(observation),
    }
    return WorldDelta(
        id=f"delta.{work_item_id}",
        source_id=observation.id,
        domain_patch={DOMAIN_KEY: {"work_items": {work_item_id: work_item}}},
        provenance_patch={work_item_id: {"observation_id": observation.id, "source": observation.source}},
        confidence_patch={work_item_id: work_item["confidence"]},
    )


def _reduce_executor_capability_observed(observation: Observation) -> WorldDelta:
    attrs = observation.attributes
    executor = str(attrs.get("executor") or "unknown")
    action_type = str(attrs.get("action_type") or "delegate_to_executor")
    capability_id = str(
        attrs.get("capability_id")
        or f"cap.external_executor.{stable_slug(executor)}.{stable_slug(action_type)}"
    )
    capability = {
        "id": capability_id,
        "capability_id": capability_id,
        "action_type": action_type,
        "executor": executor,
        "supported_scopes": [str(item) for item in attrs.get("supported_scopes", []) or []],
        "requires_confirmation": bool(attrs.get("requires_confirmation", True)),
        "reversible": bool(attrs.get("reversible", True)),
        "default_time_budget_minutes": int(attrs.get("default_time_budget_minutes") or 10),
        "availability": str(attrs.get("availability") or "unknown"),
        "source_observation_id": observation.id,
        "source": observation.source,
        "confidence": _confidence(observation),
        "observed_at": _time_or_none(observation.timestamp) or isoformat_utc(utc_now()),
        "provenance": {
            "adapter": observation.metadata.get("adapter"),
            "reported_by": observation.metadata.get("reported_by", observation.source),
            "notes": observation.metadata.get("notes"),
        },
    }
    return WorldDelta(
        id=f"delta.{capability_id}",
        source_id=observation.id,
        domain_patch={DOMAIN_KEY: {"capabilities": {capability_id: capability}}},
        provenance_patch={capability_id: {"observation_id": observation.id, "source": observation.source}},
        confidence_patch={capability_id: capability["confidence"]},
    )


def _reduce_execution_result_observed(
    state: WorldState,
    observation: Observation,
) -> WorldDelta:
    demo = ensure_demo_state(state)
    attrs = observation.attributes
    acted_on = str(attrs.get("acted_on") or attrs.get("work_item_id") or "")
    work_item = dict(demo.get("work_items", {}).get(acted_on, {}))
    status = str(attrs.get("status", "unknown"))
    if work_item:
        work_item["last_execution_status"] = status
        work_item["last_execution_ref"] = attrs.get("execution_ref")
        work_item["last_decision_id"] = attrs.get("decision_id")
        work_item["last_selected_action"] = attrs.get("selected_action")
        work_item["last_execution_summary"] = attrs.get("summary", "")
        work_item["followup_needed"] = bool(attrs.get("followup_needed", False))
        if status == "success" and not work_item["followup_needed"]:
            work_item["status"] = "closed"
        elif status in {"failed", "partial", "abandoned"}:
            work_item["status"] = "open"

    risk_id = f"risk.execution.{stable_slug(acted_on or observation.id)}"
    risk = {
        "id": risk_id,
        "kind": "execution_outcome",
        "acted_on": acted_on,
        "status": status,
        "risk_change": attrs.get("risk_change", "unknown"),
        "blocking_issue": attrs.get("blocking_issue"),
        "followup_needed": bool(attrs.get("followup_needed", False)),
        "source_observation_id": observation.id,
    }
    outcome = {
        "observation_id": observation.id,
        "decision_id": attrs.get("decision_id"),
        "execution_ref": attrs.get("execution_ref"),
        "status": status,
        "acted_on": acted_on,
        "selected_action": attrs.get("selected_action"),
        "elapsed_minutes": attrs.get("elapsed_minutes"),
        "blocking_issue": attrs.get("blocking_issue"),
        "risk_change": attrs.get("risk_change"),
        "followup_needed": attrs.get("followup_needed"),
        "summary": attrs.get("summary", ""),
        "observed_at": _time_or_none(observation.timestamp) or isoformat_utc(utc_now()),
    }
    patch: dict[str, Any] = {
        "risks": {risk_id: risk},
        "recent_outcomes": [*demo.get("recent_outcomes", []), outcome][-10:],
    }
    if work_item:
        patch["work_items"] = {acted_on: work_item}
    return WorldDelta(
        id=f"delta.execution.{_short_hash(observation.id, attrs.get('execution_ref', ''))}",
        source_id=observation.id,
        risk_ops=[],
        recent_outcome_additions=[outcome],
        domain_patch={DOMAIN_KEY: patch},
    )


def _time_or_none(value: Any) -> str | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return isoformat_utc(parsed)


def _confidence(observation: Observation) -> float:
    raw = observation.metadata.get("confidence", observation.attributes.get("confidence", 1.0))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 1.0


def _short_hash(*parts: Any) -> str:
    joined = ":".join(str(part) for part in parts)
    return sha256(joined.encode("utf-8")).hexdigest()[:12]
