from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from spice.executors.base import Executor
from spice.executors.sdep_mapping import build_sdep_describe_request, build_sdep_execute_request
from spice.protocols import (
    ExecutionIntent,
    ExecutionResult,
    SDEPDescribeRequest,
    SDEPDescribeResponse,
    SDEPError,
    SDEPExecuteRequest,
    SDEPExecuteResponse,
)
from spice.protocols.sdep import SDEPEndpointIdentity, SDEPExecutionOutcome


class SDEPTransport(ABC):
    """Transport interface for communicating with SDEP-compatible agents."""

    @abstractmethod
    def execute(self, request: SDEPExecuteRequest) -> dict[str, Any]:
        """Send one execute.request and return the execute.response payload."""

    def describe(self, request: SDEPDescribeRequest) -> dict[str, Any]:
        """
        Optional discovery path for agent capability declaration.

        Implementations may raise NotImplementedError when describe is not supported.
        """
        raise NotImplementedError("This transport does not support agent.describe.")


class SubprocessSDEPTransport(SDEPTransport):
    """
    Subprocess transport for SDEP agents.

    The target agent reads one JSON request from stdin and writes one JSON response to stdout.
    """

    def __init__(
        self,
        command: list[str],
        *,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("SubprocessSDEPTransport requires a non-empty command.")
        self.command = list(command)
        self.timeout_seconds = timeout_seconds
        self.env = dict(env) if env is not None else None

    def execute(self, request: SDEPExecuteRequest) -> dict[str, Any]:
        payload = json.dumps(request.to_dict(), ensure_ascii=True)
        return self._send_message(payload, request_id=request.request_id)

    def describe(self, request: SDEPDescribeRequest) -> dict[str, Any]:
        payload = json.dumps(request.to_dict(), ensure_ascii=True)
        return self._send_message(payload, request_id=request.request_id)

    def _send_message(self, payload: str, *, request_id: str) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                self.command,
                input=payload,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                env=self.env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"SDEP agent timeout after {self.timeout_seconds:.1f}s for request={request_id}"
            ) from exc

        stdout = completed.stdout.strip()
        if not stdout:
            stderr = completed.stderr.strip()
            raise RuntimeError(
                "SDEP agent returned empty stdout "
                f"(exit={completed.returncode}, stderr={stderr!r})"
            )

        try:
            payload_obj = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"SDEP agent returned non-JSON response: {stdout[:200]!r}"
            ) from exc

        if not isinstance(payload_obj, dict):
            raise RuntimeError(
                "SDEP agent response must be a JSON object, "
                f"got {type(payload_obj)!r}"
            )
        return payload_obj


class SDEPExecutor(Executor):
    """
    Executor adapter that routes ExecutionIntent through SDEP transport.

    This keeps Spice runtime unchanged while enabling external execution-layer agents.
    """

    def __init__(
        self,
        transport: SDEPTransport,
        *,
        executor_name: str = "sdep-executor",
    ) -> None:
        self.transport = transport
        self.executor_name = executor_name

    def execute(self, intent: ExecutionIntent) -> ExecutionResult:
        request: SDEPExecuteRequest | None = None
        try:
            request = build_sdep_execute_request(
                intent,
                metadata={"runtime": "spice", "adapter": "SDEPExecutor"},
            )
            payload = self.transport.execute(request)
            response = SDEPExecuteResponse.from_dict(payload)
            return self._to_execution_result(intent, request, response, raw_payload=payload)
        except Exception as exc:
            refs = [intent.id]
            request_payload: dict[str, Any] = {}
            if request is not None:
                refs.append(request.request_id)
                request_payload = request.to_dict()
            return ExecutionResult(
                id=f"result-{uuid4().hex}",
                result_type="sdep.execute_result",
                status="failed",
                executor=self.executor_name,
                output={},
                error=str(exc),
                refs=refs,
                attributes={
                    "sdep": {
                        "request": request_payload,
                        "transport_error": str(exc),
                    }
                },
            )

    def describe(self, *, action_types: list[str] | None = None) -> dict[str, Any]:
        """Optional capability-discovery call for SDEP agents."""
        request = build_sdep_describe_request(
            action_types=action_types,
            metadata={"runtime": "spice", "adapter": "SDEPExecutor"},
        )
        payload = self.transport.describe(request)
        response = SDEPDescribeResponse.from_dict(payload)
        return response.to_dict()

    def _to_execution_result(
        self,
        intent: ExecutionIntent,
        request: SDEPExecuteRequest,
        response: SDEPExecuteResponse,
        *,
        raw_payload: dict[str, Any],
    ) -> ExecutionResult:
        status = _map_sdep_status(response.status)
        outcome = response.outcome
        legacy_payload = dict(response.execution_result)

        refs = [intent.id, request.request_id]
        if response.request_id and response.request_id not in refs:
            refs.append(response.request_id)

        output = dict(outcome.output)
        if not output:
            legacy_output = legacy_payload.get("output")
            if isinstance(legacy_output, dict):
                output = dict(legacy_output)

        result_id = str(outcome.execution_id or legacy_payload.get("id") or f"result-{uuid4().hex}")
        result_type = str(
            outcome.outcome_type
            or outcome.metadata.get("result_type")
            or legacy_payload.get("result_type")
            or "sdep.execute_result"
        )
        # Canonical identity source is response.responder (executor-of-record).
        # outcome.metadata.executor and legacy execution_result.executor are deprecated fallback paths.
        executor_name = str(
            response.responder.implementation
            or response.responder.id
            or response.responder.name
            or outcome.metadata.get("executor")
            or legacy_payload.get("executor")
            or self.executor_name
        )

        error = None
        if response.error is not None:
            error = response.error.message
        elif status == "failed" and not output:
            error = f"sdep_status={response.status}"

        return ExecutionResult(
            id=result_id,
            result_type=result_type,
            status=status,
            executor=executor_name,
            output=output,
            error=error,
            refs=refs,
            attributes={
                "sdep": {
                    "request": request.to_dict(),
                    "response": response.to_dict(),
                    "raw_response": raw_payload,
                }
            },
        )


def _map_sdep_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized in {"success", "applied", "ok", "completed"}:
        return "success"
    if normalized in {"failed", "rejected", "error", "timeout"}:
        return "failed"
    return "unknown"


def build_error_response(
    request_id: str,
    *,
    responder: SDEPEndpointIdentity,
    code: str,
    message: str,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper for SDEP agents to emit a valid error response payload."""
    return SDEPExecuteResponse(
        request_id=request_id,
        status="error",
        responder=responder,
        outcome=SDEPExecutionOutcome(status="failed"),
        error=SDEPError(
            code=code,
            message=message,
            retryable=retryable,
            details=dict(details or {}),
        ),
    ).to_dict()
