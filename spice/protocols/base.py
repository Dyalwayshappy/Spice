from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ProtocolRecord:
    id: str
    timestamp: datetime = field(default_factory=utc_now)
    refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
