from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spice.protocols.base import ProtocolRecord


@dataclass(slots=True)
class ExecutionIntent(ProtocolRecord):
    intent_type: str = "action_request"
    status: str = "created"
    objective: dict[str, Any] = field(
        default_factory=lambda: {"id": "", "description": ""}
    )
    executor_type: str = "generic"
    target: dict[str, Any] = field(default_factory=dict)
    operation: dict[str, Any] = field(default_factory=dict)
    input_payload: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    success_criteria: list[dict[str, Any]] = field(default_factory=list)
    failure_policy: dict[str, Any] = field(
        default_factory=lambda: {"strategy": "fail_fast", "max_retries": 0}
    )
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionResult(ProtocolRecord):
    result_type: str = "execution_result"
    status: str = "unknown"
    executor: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
