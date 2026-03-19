from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from spice.memory.base import MemoryProvider


class FileMemoryProvider(MemoryProvider):
    """Lightweight JSONL-backed memory provider for local OSS usage."""

    def __init__(self, base_dir: str | Path = ".spice_memory") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        records: list[dict[str, Any]],
        *,
        namespace: str,
        refs: list[str] | None = None,
    ) -> list[str]:
        if not records:
            return []

        path = self._namespace_path(namespace)
        path.parent.mkdir(parents=True, exist_ok=True)

        ids: list[str] = []
        with path.open("a", encoding="utf-8") as f:
            for record in records:
                payload = dict(record)
                payload.setdefault("id", f"mem-{uuid4().hex}")
                if refs:
                    payload.setdefault("refs", [])
                    payload["refs"] = list(dict.fromkeys([*payload["refs"], *refs]))
                f.write(json.dumps(payload, ensure_ascii=True, default=self._json_default) + "\n")
                ids.append(str(payload["id"]))
        return ids

    def query(
        self,
        *,
        namespace: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        order_by: str | None = None,
    ) -> list[dict[str, Any]]:
        records = self._read_namespace(namespace)
        if filters:
            records = [record for record in records if self._matches_filters(record, filters)]

        if order_by:
            reverse = order_by.startswith("-")
            key = order_by[1:] if reverse else order_by
            records.sort(key=lambda record: str(record.get(key, "")), reverse=reverse)

        if limit < 0:
            return records
        return records[:limit]

    def _namespace_path(self, namespace: str) -> Path:
        safe = namespace.replace("/", "__")
        return self.base_dir / f"{safe}.jsonl"

    def _read_namespace(self, namespace: str) -> list[dict[str, Any]]:
        path = self._namespace_path(namespace)
        if not path.exists():
            return []

        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records

    @staticmethod
    def _matches_filters(record: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, expected in filters.items():
            actual = record.get(key)
            if isinstance(actual, list):
                if expected not in actual:
                    return False
                continue
            if actual != expected:
                return False
        return True

    @staticmethod
    def _json_default(value: Any) -> Any:
        iso = getattr(value, "isoformat", None)
        if callable(iso):
            return iso()
        return str(value)
