from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class CommitmentProposalMeta:
    confidence: float
    uncertain_fields: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    needs_confirmation: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CommitmentProposalMeta:
        confidence = payload.get("confidence", 0.0)
        if not isinstance(confidence, int | float) or isinstance(confidence, bool):
            confidence = 0.0

        uncertain_fields = _string_tuple(payload.get("uncertain_fields", ()))
        assumptions = _string_tuple(payload.get("assumptions", ()))
        needs_confirmation = bool(payload.get("needs_confirmation", False))

        return cls(
            confidence=max(0.0, min(1.0, float(confidence))),
            uncertain_fields=uncertain_fields,
            assumptions=assumptions,
            needs_confirmation=needs_confirmation,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "uncertain_fields": list(self.uncertain_fields),
            "assumptions": list(self.assumptions),
            "needs_confirmation": self.needs_confirmation,
        }


@dataclass(frozen=True, slots=True)
class CommitmentProposal:
    summary: str | None
    start_time: str | None
    end_time: str | None = None
    duration_minutes: int | None = None
    prep_start_time: str | None = None
    priority_hint: str | None = None
    flexibility_hint: str | None = None
    constraint_hints: tuple[str, ...] = ()
    meta: CommitmentProposalMeta = CommitmentProposalMeta(confidence=0.0)
    extractor: str = "unknown"
    matched_terms: tuple[str, ...] = ()
    duration_source: str | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        extractor: str = "llm_assisted",
    ) -> CommitmentProposal:
        meta_payload = payload.get("meta")
        meta = CommitmentProposalMeta.from_payload(
            meta_payload if isinstance(meta_payload, dict) else {}
        )

        duration_minutes = payload.get("duration_minutes")
        if not isinstance(duration_minutes, int) or isinstance(duration_minutes, bool):
            duration_minutes = None

        return cls(
            summary=_optional_string(payload.get("summary")),
            start_time=_optional_string(payload.get("start_time")),
            end_time=_optional_string(payload.get("end_time")),
            duration_minutes=duration_minutes,
            prep_start_time=_optional_string(payload.get("prep_start_time")),
            priority_hint=_optional_string(payload.get("priority_hint")),
            flexibility_hint=_optional_string(payload.get("flexibility_hint")),
            constraint_hints=_string_tuple(payload.get("constraint_hints", ())),
            meta=meta,
            extractor=extractor,
            matched_terms=_string_tuple(payload.get("matched_terms", ())),
            duration_source=_optional_string(payload.get("duration_source")),
        )

    def with_duration_from_end_time(self) -> CommitmentProposal:
        if self.duration_minutes is not None:
            return self
        if not self.start_time or not self.end_time:
            return self

        start = _parse_iso_datetime(self.start_time)
        end = _parse_iso_datetime(self.end_time)
        if start is None or end is None or end <= start:
            return self

        minutes = round((end - start).total_seconds() / 60)
        return CommitmentProposal(
            summary=self.summary,
            start_time=self.start_time,
            end_time=self.end_time,
            duration_minutes=max(1, minutes),
            prep_start_time=self.prep_start_time,
            priority_hint=self.priority_hint,
            flexibility_hint=self.flexibility_hint,
            constraint_hints=self.constraint_hints,
            meta=self.meta,
            extractor=self.extractor,
            matched_terms=self.matched_terms,
            duration_source=self.duration_source or "explicit_end_time",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_minutes": self.duration_minutes,
            "prep_start_time": self.prep_start_time,
            "priority_hint": self.priority_hint,
            "flexibility_hint": self.flexibility_hint,
            "constraint_hints": list(self.constraint_hints),
            "meta": self.meta.to_dict(),
            "extractor": self.extractor,
            "matched_terms": list(self.matched_terms),
            "duration_source": self.duration_source,
        }


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed
