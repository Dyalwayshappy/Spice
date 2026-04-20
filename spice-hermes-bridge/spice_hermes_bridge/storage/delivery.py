from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spice_hermes_bridge.observations.schema import StructuredObservation, utc_now_iso


DEFAULT_DELIVERY_STATE = Path(".spice-hermes/delivery_state.json")
DEFAULT_OBSERVATION_AUDIT_LOG = Path(".spice-hermes/observations.jsonl")


def is_event_processed(
    event_key: str,
    *,
    path: Path = DEFAULT_DELIVERY_STATE,
) -> bool:
    return event_key in _load_processed_event_keys(path)


def mark_event_processed(
    event_key: str,
    *,
    observation_id: str,
    path: Path = DEFAULT_DELIVERY_STATE,
) -> None:
    payload = _load_payload(path)
    processed = payload.setdefault("processed_event_keys", {})
    if not isinstance(processed, dict):
        processed = {}
        payload["processed_event_keys"] = processed

    processed[event_key] = {
        "processed_at": utc_now_iso(),
        "observation_id": observation_id,
    }
    _write_payload(path, payload)


def append_observation_audit(
    observation: StructuredObservation,
    *,
    path: Path = DEFAULT_OBSERVATION_AUDIT_LOG,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def find_audited_observation_id(
    event_key: str,
    *,
    path: Path = DEFAULT_OBSERVATION_AUDIT_LOG,
) -> str | None:
    if not path.exists():
        return None

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        attributes = payload.get("attributes")
        if not isinstance(attributes, dict):
            continue
        if attributes.get("event_key") == event_key:
            observation_id = payload.get("observation_id")
            return observation_id if isinstance(observation_id, str) else ""

    return None


def load_delivery_state(
    *,
    path: Path = DEFAULT_DELIVERY_STATE,
) -> dict[str, Any]:
    return _load_payload(path)


def _load_processed_event_keys(path: Path) -> dict[str, Any]:
    processed = _load_payload(path).get("processed_event_keys", {})
    if isinstance(processed, dict):
        return processed
    return {}


def _load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"processed_event_keys": {}}
    loaded = json.loads(path.read_text())
    if not isinstance(loaded, dict):
        return {"processed_event_keys": {}}
    processed = loaded.get("processed_event_keys")
    if not isinstance(processed, dict):
        loaded["processed_event_keys"] = {}
    return loaded


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
