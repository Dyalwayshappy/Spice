from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from spice.protocols.world_state import WorldState

from examples.decision_hub_demo.state import (
    DOMAIN_KEY,
    ensure_demo_state,
    isoformat_utc,
    minutes_between,
    parse_time,
    utc_now,
)


@dataclass(slots=True)
class ConflictFact:
    type: str
    entities: list[str]
    severity: str
    facts: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ActiveDecisionContext:
    id: str
    now: datetime
    relevant_commitments: list[dict[str, Any]]
    open_work_items: list[dict[str, Any]]
    active_risks: list[dict[str, Any]]
    conflict_facts: list[ConflictFact]
    available_window_minutes: int
    executor_capabilities: list[dict[str, Any]]
    available_capabilities: list[dict[str, Any]]
    executor_available: bool
    missing_fields: list[str] = field(default_factory=list)
    uncertainty_reasons: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "now": isoformat_utc(self.now),
            "relevant_commitments": list(self.relevant_commitments),
            "open_work_items": list(self.open_work_items),
            "active_risks": list(self.active_risks),
            "conflict_facts": [item.to_payload() for item in self.conflict_facts],
            "available_window_minutes": self.available_window_minutes,
            "executor_capabilities": list(self.executor_capabilities),
            "available_capabilities": list(self.available_capabilities),
            "executor_available": self.executor_available,
            "missing_fields": list(self.missing_fields),
            "uncertainty_reasons": list(self.uncertainty_reasons),
        }


def build_active_context(
    state: WorldState,
    *,
    now: datetime | None = None,
    lookahead_minutes: int = 180,
) -> ActiveDecisionContext:
    demo = ensure_demo_state(state)
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("ActiveDecisionContext requires timezone-aware now.")
    horizon = now + timedelta(minutes=lookahead_minutes)

    relevant_commitments = [
        commitment
        for commitment in demo.get("commitments", {}).values()
        if _commitment_is_relevant(commitment, now, horizon)
    ]
    relevant_commitments.sort(key=lambda item: parse_time(item.get("prep_start_time") or item.get("start_time")) or horizon)

    open_work_items = [
        item
        for item in demo.get("work_items", {}).values()
        if item.get("status", "open") == "open" and item.get("requires_attention", True)
    ]
    open_work_items.sort(key=lambda item: str(item.get("id", "")))

    active_risks = list(demo.get("risks", {}).values())
    capabilities = dict(demo.get("capabilities", {}))
    executor_capabilities = _executor_capabilities(capabilities)
    available_capabilities = _available_executor_capabilities(executor_capabilities)
    executor_available = bool(available_capabilities)
    available = _available_window_minutes(relevant_commitments, now)
    missing_fields = _missing_fields(relevant_commitments, open_work_items)
    uncertainty_reasons = _uncertainty_reasons(relevant_commitments, open_work_items)

    context = ActiveDecisionContext(
        id=f"active_context.{state.id}.{int(now.timestamp())}",
        now=now,
        relevant_commitments=relevant_commitments,
        open_work_items=open_work_items,
        active_risks=active_risks,
        conflict_facts=[],
        available_window_minutes=available,
        executor_capabilities=executor_capabilities,
        available_capabilities=available_capabilities,
        executor_available=executor_available,
        missing_fields=missing_fields,
        uncertainty_reasons=uncertainty_reasons,
    )
    context.conflict_facts = detect_conflicts(context)
    return context


def detect_conflicts(context: ActiveDecisionContext) -> list[ConflictFact]:
    facts: list[ConflictFact] = []
    for work_item in context.open_work_items:
        estimated = int(work_item.get("estimated_minutes_hint") or 30)
        if context.relevant_commitments and context.available_window_minutes < estimated:
            facts.append(
                ConflictFact(
                    type="time_conflict",
                    entities=[
                        str(context.relevant_commitments[0].get("id")),
                        str(work_item.get("id")),
                    ],
                    severity="high" if context.available_window_minutes < max(10, estimated // 2) else "medium",
                    facts={
                        "available_window_minutes": context.available_window_minutes,
                        "estimated_work_minutes": estimated,
                        "prep_start_time": context.relevant_commitments[0].get("prep_start_time"),
                        "executor_available": context.executor_available,
                        "available_executor_capabilities": [
                            item.get("capability_id") or item.get("id")
                            for item in context.available_capabilities
                        ],
                    },
                )
            )
        if context.relevant_commitments and _prep_window_active(context.relevant_commitments[0], context.now):
            facts.append(
                ConflictFact(
                    type="deep_work_risk",
                    entities=[str(context.relevant_commitments[0].get("id")), str(work_item.get("id"))],
                    severity="medium",
                    facts={"reason": "commitment preparation window has started"},
                )
            )
    if context.executor_available:
        facts.append(
            ConflictFact(
                type="executor_capability_available",
                entities=[
                    str(item.get("capability_id") or item.get("id"))
                    for item in context.available_capabilities
                ],
                severity="info",
                facts={
                    "executor_available": True,
                    "capabilities": list(context.available_capabilities),
                },
            )
        )
    if context.missing_fields or context.uncertainty_reasons:
        facts.append(
            ConflictFact(
                type="uncertainty",
                entities=[],
                severity="medium",
                facts={
                    "missing_fields": list(context.missing_fields),
                    "uncertainty_reasons": list(context.uncertainty_reasons),
                },
            )
        )
    return facts


def _commitment_is_relevant(
    commitment: dict[str, Any],
    now: datetime,
    horizon: datetime,
) -> bool:
    start = parse_time(commitment.get("start_time"))
    end = parse_time(commitment.get("end_time"))
    prep = parse_time(commitment.get("prep_start_time"))
    if end and end < now:
        return False
    anchor = prep or start
    if anchor is None:
        return True
    return now <= anchor <= horizon or (start is not None and start <= now <= (end or horizon))


def _available_window_minutes(commitments: list[dict[str, Any]], now: datetime) -> int:
    if not commitments:
        return 240
    first = commitments[0]
    prep = parse_time(first.get("prep_start_time"))
    start = parse_time(first.get("start_time"))
    if prep and prep > now:
        return minutes_between(now, prep)
    if start and start > now:
        return minutes_between(now, start)
    return 0


def _missing_fields(
    commitments: list[dict[str, Any]],
    work_items: list[dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    for commitment in commitments:
        if not commitment.get("start_time"):
            missing.append(f"{commitment.get('id')}.start_time")
        if not commitment.get("end_time") and not commitment.get("duration_minutes"):
            missing.append(f"{commitment.get('id')}.end_time")
    for work_item in work_items:
        if not work_item.get("estimated_minutes_hint"):
            missing.append(f"{work_item.get('id')}.estimated_minutes_hint")
    return missing


def _uncertainty_reasons(
    commitments: list[dict[str, Any]],
    work_items: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    for item in [*commitments, *work_items]:
        try:
            confidence = float(item.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        if confidence < 0.65:
            reasons.append(f"{item.get('id')}.low_confidence")
    return reasons


def _prep_window_active(commitment: dict[str, Any], now: datetime) -> bool:
    prep = parse_time(commitment.get("prep_start_time"))
    start = parse_time(commitment.get("start_time"))
    if not prep or not start:
        return False
    return prep <= now <= start


def _executor_capabilities(capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for capability_id, raw in capabilities.items():
        if not isinstance(raw, dict):
            continue
        capability = dict(raw)
        capability.setdefault("capability_id", str(capability_id))
        if capability.get("action_type") == "delegate_to_executor":
            normalized.append(capability)
    normalized.sort(key=lambda item: str(item.get("capability_id") or item.get("id") or ""))
    return normalized


def _available_executor_capabilities(
    capabilities: list[dict[str, Any]],
    *,
    required_scope: str = "triage",
) -> list[dict[str, Any]]:
    available: list[dict[str, Any]] = []
    for capability in capabilities:
        scopes = {str(item) for item in capability.get("supported_scopes", []) or []}
        if capability.get("availability") == "available" and required_scope in scopes:
            available.append(capability)
    return available
