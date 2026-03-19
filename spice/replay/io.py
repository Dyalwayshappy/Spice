from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from spice.protocols import Observation, Outcome


def load_replay_stream(path: str | Path) -> list[Observation | Outcome]:
    file_path = Path(path)
    records: list[Observation | Outcome] = []
    with file_path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            row = line.strip()
            if not row:
                continue
            payload = json.loads(row)
            if not isinstance(payload, dict):
                raise ValueError(
                    f"Replay record must be an object, got {type(payload)!r} at line {line_number}."
                )
            records.append(to_replay_record(payload, line_number=line_number))
    return records


def stream_from_history(history: Iterable[object]) -> list[Observation | Outcome]:
    records: list[Observation | Outcome] = []
    for record in history:
        if isinstance(record, Observation | Outcome):
            records.append(record)
    return records


def to_replay_record(payload: dict[str, Any], *, line_number: int = 0) -> Observation | Outcome:
    record_type = payload.get("record_type") or payload.get("type")
    if isinstance(record_type, str):
        normalized = record_type.strip().lower()
        if normalized in {"observation", "obs"}:
            return _to_observation(payload, line_number=line_number)
        if normalized in {"outcome", "out"}:
            return _to_outcome(payload, line_number=line_number)

    if "observation_type" in payload:
        return _to_observation(payload, line_number=line_number)
    if "outcome_type" in payload or "changes" in payload or "decision_id" in payload:
        return _to_outcome(payload, line_number=line_number)

    raise ValueError(
        f"Could not infer replay record type at line {line_number}. Provide record_type."
    )


def _to_observation(payload: dict[str, Any], *, line_number: int) -> Observation:
    observation = Observation(
        id=str(payload.get("id") or f"obs-replay-{line_number:06d}"),
        observation_type=str(payload.get("observation_type", "generic.replay")),
        source=str(payload.get("source", "replay.stream")),
        attributes=_as_dict(payload.get("attributes")),
        metadata=_as_dict(payload.get("metadata")),
        refs=_as_str_list(payload.get("refs")),
    )
    timestamp = _parse_timestamp(payload.get("timestamp"))
    if timestamp is not None:
        observation.timestamp = timestamp
    return observation


def _to_outcome(payload: dict[str, Any], *, line_number: int) -> Outcome:
    attributes = _as_dict(payload.get("attributes"))
    decision_id = str(payload.get("decision_id") or attributes.get("decision_id") or "")

    outcome = Outcome(
        id=str(payload.get("id") or f"out-replay-{line_number:06d}"),
        outcome_type=str(payload.get("outcome_type", "replay.outcome")),
        status=str(payload.get("status", "observed")),
        decision_id=decision_id,
        changes=_as_dict(payload.get("changes")),
        attributes=attributes,
        metadata=_as_dict(payload.get("metadata")),
        refs=_as_str_list(payload.get("refs")),
    )
    timestamp = _parse_timestamp(payload.get("timestamp"))
    if timestamp is not None:
        outcome.timestamp = timestamp
    return outcome


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    return None
