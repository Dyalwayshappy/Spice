from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NativeAdapterRequest:
    request_id: str
    action_type: str
    target: dict[str, Any] = field(default_factory=dict)
    input_payload: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    success_criteria: list[dict[str, Any]] = field(default_factory=list)
    failure_policy: dict[str, Any] = field(default_factory=dict)
    mode: str = "sync"
    dry_run: bool = False
    idempotency_key: str = ""
    traceability: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NativeAdapterResult:
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    execution_id: str = ""
    outcome_type: str = "observation"
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    error_code: str = ""
    retryable: bool = False


class NativeAdapterError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = bool(retryable)


class NativeAdapterTimeoutError(NativeAdapterError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="adapter.timeout", retryable=True)


class NativeAdapterExecutionError(NativeAdapterError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="adapter.failed", retryable=False)


class NativeAgentAdapter(ABC):
    @abstractmethod
    def execute(self, request: NativeAdapterRequest) -> NativeAdapterResult:
        """Execute one native non-SDEP request and return a normalized result."""

