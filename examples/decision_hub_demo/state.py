from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from spice.protocols.world_state import WorldState

DOMAIN_KEY = "decision_hub_demo"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_world_state(*, state_id: str = "world.decision_hub_demo") -> WorldState:
    state = WorldState(id=state_id)
    ensure_demo_state(state)
    return state


def ensure_demo_state(state: WorldState) -> dict[str, Any]:
    demo = state.domain_state.setdefault(DOMAIN_KEY, {})
    demo.setdefault("commitments", {})
    demo.setdefault("work_items", {})
    demo.setdefault("risks", {})
    demo.setdefault("recent_outcomes", [])
    demo.setdefault("history_summary", {})
    demo.setdefault("capabilities", {})
    return demo


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def minutes_between(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60))


def stable_slug(value: str) -> str:
    return (
        value.lower()
        .replace("://", "_")
        .replace("/", "_")
        .replace(" ", "_")
        .replace(":", "_")
        .replace("#", "_")
    )
