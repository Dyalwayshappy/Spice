from __future__ import annotations

from copy import deepcopy
from typing import Any


TRACE_REGISTRY: dict[str, dict[str, Any]] = {}


def register_trace(trace_ref: str, trace: dict[str, Any]) -> None:
    TRACE_REGISTRY[trace_ref] = deepcopy(trace)


def get_trace(trace_ref: str) -> dict[str, Any] | None:
    trace = TRACE_REGISTRY.get(trace_ref)
    if trace is None:
        return None
    return deepcopy(trace)
