from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from examples.decision_hub_demo.state import parse_time, stable_slug


def short_hash(payload: Any, *, length: int = 8) -> str:
    return sha256(repr(payload).encode("utf-8")).hexdigest()[:length]


def timestamp_segment(value: datetime | str | None) -> str:
    parsed = parse_time(value) if value is not None else None
    if parsed is None:
        parsed = datetime.now(timezone.utc)
    parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return parsed.isoformat().replace("+00:00", "Z")


def entity_segment(value: Any) -> str:
    raw = str(value or "none").strip() or "none"
    return stable_slug(raw).replace(".", "_")


def make_decision_id(
    *,
    now: datetime | str | None,
    acted_on: Any,
    trace_seed: Any,
) -> str:
    stamp = timestamp_segment(now)
    entity = entity_segment(acted_on)
    digest = short_hash({"stamp": stamp, "entity": entity, "trace_seed": trace_seed}, length=8)
    return f"decision.{stamp}.{entity}.{digest}"


def make_trace_ref(decision_id: str) -> str:
    return f"trace.{short_hash(decision_id, length=12)}"


def make_execution_id(
    *,
    now: datetime | str | None,
    decision_id: str,
    action_type: str,
    acted_on: Any,
) -> str:
    stamp = timestamp_segment(now)
    digest = short_hash(
        {
            "stamp": stamp,
            "decision_id": decision_id,
            "action_type": action_type,
            "acted_on": acted_on,
        },
        length=8,
    )
    return f"exec.{stamp}.{stable_slug(action_type)}.{digest}"


def make_confirmation_id(
    *,
    now: datetime | str | None,
    decision_id: str,
    selected_action: str,
    acted_on: Any,
) -> str:
    stamp = timestamp_segment(now)
    digest = short_hash(
        {
            "stamp": stamp,
            "decision_id": decision_id,
            "selected_action": selected_action,
            "acted_on": acted_on,
        },
        length=8,
    )
    return f"confirm.{stamp}.{stable_slug(selected_action)}.{digest}"
