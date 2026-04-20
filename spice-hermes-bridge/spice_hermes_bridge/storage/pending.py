from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_PENDING_STORE = Path(".spice-hermes/pending_confirmations.json")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_pending_id() -> str:
    return f"pending_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    pending_id: str
    message: str
    missing_fields: tuple[str, ...]
    uncertain_fields: tuple[str, ...]
    assumptions: tuple[str, ...]
    original_text: str
    source: str = "whatsapp"
    status: str = "pending"
    followups: tuple[dict[str, Any], ...] = ()
    created_at: str = field(default_factory=utc_now_iso)
    resolved_at: str | None = None
    resolved_input_hash: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pending_id": self.pending_id,
            "status": self.status,
            "message": self.message,
            "missing_fields": list(self.missing_fields),
            "uncertain_fields": list(self.uncertain_fields),
            "assumptions": list(self.assumptions),
            "original_text": self.original_text,
            "followups": list(self.followups),
            "source": self.source,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolved_input_hash": self.resolved_input_hash,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PendingConfirmation:
        followups = payload.get("followups", ())
        if not isinstance(followups, list | tuple):
            followups = ()
        return cls(
            pending_id=str(payload.get("pending_id", "")),
            status=str(payload.get("status", "pending")),
            message=str(payload.get("message", "")),
            missing_fields=_string_tuple(payload.get("missing_fields", ())),
            uncertain_fields=_string_tuple(payload.get("uncertain_fields", ())),
            assumptions=_string_tuple(payload.get("assumptions", ())),
            original_text=str(payload.get("original_text", "")),
            followups=tuple(item for item in followups if isinstance(item, dict)),
            source=str(payload.get("source", "whatsapp")),
            created_at=str(payload.get("created_at", "")) or utc_now_iso(),
            resolved_at=_optional_string(payload.get("resolved_at")),
            resolved_input_hash=_optional_string(payload.get("resolved_input_hash")),
            provenance=(
                payload.get("provenance", {})
                if isinstance(payload.get("provenance", {}), dict)
                else {}
            ),
        )


def build_pending_confirmation(
    *,
    original_text: str,
    missing_fields: tuple[str, ...],
    uncertain_fields: tuple[str, ...],
    assumptions: tuple[str, ...],
    provenance: dict[str, Any],
    source: str = "whatsapp",
) -> PendingConfirmation:
    message = _confirmation_message(missing_fields, uncertain_fields, assumptions)
    return PendingConfirmation(
        pending_id=generate_pending_id(),
        message=message,
        missing_fields=missing_fields,
        uncertain_fields=uncertain_fields,
        assumptions=assumptions,
        original_text=original_text,
        source=source,
        provenance=provenance,
    )


def append_pending_confirmation(
    pending: PendingConfirmation,
    *,
    path: Path = DEFAULT_PENDING_STORE,
) -> None:
    payload = _load_payload(path)
    payload.append(pending.to_dict())
    _write_payload(path, payload)


def find_active_pending(
    *,
    path: Path = DEFAULT_PENDING_STORE,
    chat_id: str | None = None,
    session_id: str | None = None,
    source: str = "whatsapp",
) -> PendingConfirmation | None:
    """Return the most recent unresolved pending item in the same simple scope."""

    for item in reversed(_load_pending(path)):
        if item.status != "pending" or item.source != source:
            continue
        if chat_id is not None and item.provenance.get("chat_id") != chat_id:
            continue
        if session_id is not None and item.provenance.get("session_id") != session_id:
            continue
        return item
    return None


def find_resolved_pending_for_followup(
    *,
    followup_hash: str,
    path: Path = DEFAULT_PENDING_STORE,
    chat_id: str | None = None,
    source: str = "whatsapp",
) -> PendingConfirmation | None:
    """Return a resolved pending item that already used the same follow-up text."""

    for item in reversed(_load_pending(path)):
        if item.status != "resolved" or item.source != source:
            continue
        if chat_id is not None and item.provenance.get("chat_id") != chat_id:
            continue
        if any(followup.get("input_hash") == followup_hash for followup in item.followups):
            return item
    return None


def update_pending_still_pending(
    *,
    pending_id: str,
    followup: dict[str, Any],
    missing_fields: tuple[str, ...],
    uncertain_fields: tuple[str, ...],
    assumptions: tuple[str, ...],
    path: Path = DEFAULT_PENDING_STORE,
) -> PendingConfirmation:
    def update(item: PendingConfirmation) -> PendingConfirmation:
        followups = _append_unique_followup(item.followups, followup)
        message = _confirmation_message(missing_fields, uncertain_fields, assumptions)
        return PendingConfirmation(
            pending_id=item.pending_id,
            status="pending",
            message=message,
            missing_fields=missing_fields,
            uncertain_fields=uncertain_fields,
            assumptions=assumptions,
            original_text=item.original_text,
            followups=followups,
            source=item.source,
            created_at=item.created_at,
            resolved_at=None,
            resolved_input_hash=None,
            provenance=item.provenance,
        )

    return _update_pending(pending_id, update, path=path)


def mark_pending_resolved(
    *,
    pending_id: str,
    followup: dict[str, Any],
    resolved_input_hash: str,
    path: Path = DEFAULT_PENDING_STORE,
) -> PendingConfirmation:
    def update(item: PendingConfirmation) -> PendingConfirmation:
        followups = _append_unique_followup(item.followups, followup)
        return PendingConfirmation(
            pending_id=item.pending_id,
            status="resolved",
            message=item.message,
            missing_fields=item.missing_fields,
            uncertain_fields=item.uncertain_fields,
            assumptions=item.assumptions,
            original_text=item.original_text,
            followups=followups,
            source=item.source,
            created_at=item.created_at,
            resolved_at=utc_now_iso(),
            resolved_input_hash=resolved_input_hash,
            provenance=item.provenance,
        )

    return _update_pending(pending_id, update, path=path)


def build_followup_record(
    *,
    text: str,
    message_id: str | None = None,
    received_at: str | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "message_id": message_id,
        "received_at": received_at,
        "created_at": utc_now_iso(),
        "input_hash": hash_followup_text(text),
    }


def hash_followup_text(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def hash_resolution_input(original_text: str, followup_text: str) -> str:
    normalized = f"{' '.join(original_text.split())}\n{' '.join(followup_text.split())}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _confirmation_message(
    missing_fields: tuple[str, ...],
    uncertain_fields: tuple[str, ...],
    assumptions: tuple[str, ...],
) -> str:
    fields = tuple(dict.fromkeys(missing_fields + uncertain_fields))
    needs_start = "start_time" in fields
    needs_duration = "duration_minutes" in fields or "end_time" in fields
    if needs_start and needs_duration:
        return "我理解你有一个日程，但缺少具体开始时间和预计时长/结束时间。请补充开始时间和时长。"
    if needs_start:
        return "我理解你有一个日程，但缺少具体开始时间。请补充具体时间。"
    if needs_duration:
        return "我理解你有一个日程，但缺少结束时间或预计持续时间。请补充时长或结束时间。"
    if assumptions:
        return "我理解这可能是一个日程，但存在不确定假设。请确认具体信息。"
    return "我理解这可能是一个日程，但信息不够明确。请补充细节。"


def _load_pending(path: Path) -> list[PendingConfirmation]:
    return [PendingConfirmation.from_dict(item) for item in _load_payload(path)]


def _load_payload(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    loaded = json.loads(path.read_text())
    if not isinstance(loaded, list):
        return []
    return [item for item in loaded if isinstance(item, dict)]


def _write_payload(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _update_pending(
    pending_id: str,
    update: Any,
    *,
    path: Path,
) -> PendingConfirmation:
    payload = _load_payload(path)
    updated: PendingConfirmation | None = None
    next_payload: list[dict[str, Any]] = []
    for item_payload in payload:
        item = PendingConfirmation.from_dict(item_payload)
        if item.pending_id == pending_id:
            item = update(item)
            updated = item
        next_payload.append(item.to_dict())

    if updated is None:
        raise KeyError(f"pending not found: {pending_id}")

    _write_payload(path, next_payload)
    return updated


def _append_unique_followup(
    followups: tuple[dict[str, Any], ...],
    followup: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    input_hash = followup.get("input_hash")
    if input_hash and any(item.get("input_hash") == input_hash for item in followups):
        return followups
    return followups + (followup,)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
