from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from spice.protocols import Observation


class FileObservationAdapter:
    """Load observation records from local JSON or JSONL files."""

    def __init__(
        self,
        *,
        default_source: str = "file.adapter",
        default_observation_type: str = "generic.file",
    ) -> None:
        self.default_source = default_source
        self.default_observation_type = default_observation_type

    def load(self, path: str | Path) -> list[Observation]:
        file_path = Path(path)
        suffix = file_path.suffix.lower()
        if suffix == ".json":
            records = self._load_json(file_path)
        elif suffix == ".jsonl":
            records = self._load_jsonl(file_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}. Use .json or .jsonl")

        return [self.to_observation(record) for record in records]

    def to_observation(self, record: dict[str, Any]) -> Observation:
        observation_id = str(record.get("id") or f"obs-{uuid4().hex}")
        observation_type = str(
            record.get("observation_type", self.default_observation_type)
        )
        source = str(record.get("source", self.default_source))
        metadata = dict(record.get("metadata", {}))
        refs_raw = record.get("refs", [])
        refs = list(refs_raw) if isinstance(refs_raw, list) else []

        if "attributes" in record and isinstance(record["attributes"], dict):
            attributes = dict(record["attributes"])
        else:
            attributes = self._fallback_attributes(record)

        observation = Observation(
            id=observation_id,
            observation_type=observation_type,
            source=source,
            attributes=attributes,
            metadata=metadata,
            refs=refs,
        )

        timestamp = self._parse_timestamp(record.get("timestamp"))
        if timestamp is not None:
            observation.timestamp = timestamp
        return observation

    def _load_json(self, path: Path) -> list[dict[str, Any]]:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        if isinstance(payload, list):
            return [self._as_record(item) for item in payload]
        if isinstance(payload, dict) and isinstance(payload.get("observations"), list):
            return [self._as_record(item) for item in payload["observations"]]
        if isinstance(payload, dict):
            return [self._as_record(payload)]
        raise ValueError("JSON file must contain an object, a list, or {'observations': [...]}.")

    def _load_jsonl(self, path: Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(self._as_record(json.loads(line)))
        return records

    @staticmethod
    def _as_record(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"Observation record must be an object, got: {type(value)!r}")
        return value

    @staticmethod
    def _fallback_attributes(record: dict[str, Any]) -> dict[str, Any]:
        excluded = {"id", "timestamp", "refs", "metadata", "observation_type", "source"}
        return {key: value for key, value in record.items() if key not in excluded}

    @staticmethod
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
