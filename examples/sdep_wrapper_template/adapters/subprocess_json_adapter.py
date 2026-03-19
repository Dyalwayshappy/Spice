from __future__ import annotations

import json
import subprocess
from typing import Any

from adapter_contract import (
    NativeAdapterExecutionError,
    NativeAdapterRequest,
    NativeAdapterResult,
    NativeAdapterTimeoutError,
    NativeAgentAdapter,
)


class SubprocessJsonAdapter(NativeAgentAdapter):
    """
    Bridge to a non-SDEP subprocess agent that speaks a simple JSON contract:
    - stdin: one JSON object request
    - stdout: one JSON object response
    """

    def __init__(
        self,
        command: list[str],
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not command:
            raise ValueError("SubprocessJsonAdapter requires a non-empty command.")
        self.command = list(command)
        self.timeout_seconds = float(timeout_seconds)

    def execute(self, request: NativeAdapterRequest) -> NativeAdapterResult:
        native_request = {
            "request_id": request.request_id,
            "action_type": request.action_type,
            "target": dict(request.target),
            "input_payload": dict(request.input_payload),
            "parameters": dict(request.parameters),
            "constraints": list(request.constraints),
            "success_criteria": list(request.success_criteria),
            "failure_policy": dict(request.failure_policy),
            "mode": request.mode,
            "dry_run": bool(request.dry_run),
            "idempotency_key": request.idempotency_key,
            "traceability": dict(request.traceability),
            "metadata": dict(request.metadata),
        }
        payload = json.dumps(native_request, ensure_ascii=True)
        response = self._run_native(payload)
        return self._normalize_native_response(response)

    def _run_native(self, payload: str) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                self.command,
                input=payload,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise NativeAdapterTimeoutError(
                f"Native adapter timeout after {self.timeout_seconds:.1f}s."
            ) from exc

        stdout = completed.stdout.strip()
        if not stdout:
            stderr = completed.stderr.strip()
            raise NativeAdapterExecutionError(
                f"Native adapter returned empty stdout (exit={completed.returncode}, stderr={stderr!r})."
            )

        try:
            payload_obj = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise NativeAdapterExecutionError(
                f"Native adapter returned non-JSON response: {stdout[:200]!r}"
            ) from exc

        if not isinstance(payload_obj, dict):
            raise NativeAdapterExecutionError(
                "Native adapter response must be a JSON object."
            )
        return payload_obj

    def _normalize_native_response(
        self,
        payload: dict[str, Any],
    ) -> NativeAdapterResult:
        status = str(payload.get("status", "")).strip().lower()
        if status == "success":
            output = payload.get("output")
            if not isinstance(output, dict):
                output = {}
            artifacts = payload.get("artifacts")
            if not isinstance(artifacts, list):
                artifacts = []
            metrics = payload.get("metrics")
            if not isinstance(metrics, dict):
                metrics = {}
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            return NativeAdapterResult(
                status="success",
                output=dict(output),
                execution_id=str(payload.get("execution_id", "")),
                outcome_type=str(payload.get("outcome_type") or "observation"),
                artifacts=[dict(item) for item in artifacts if isinstance(item, dict)],
                metrics=dict(metrics),
                metadata=dict(metadata),
            )

        if status in {"failed", "error"}:
            output = payload.get("output")
            if not isinstance(output, dict):
                output = {}
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            return NativeAdapterResult(
                status="failed",
                output=dict(output),
                execution_id=str(payload.get("execution_id", "")),
                outcome_type=str(payload.get("outcome_type") or "error"),
                metadata=dict(metadata),
                error_message=str(payload.get("error", "Native adapter reported failure.")),
                error_code=str(payload.get("error_code", "")),
                retryable=bool(payload.get("retryable", False)),
            )

        raise NativeAdapterExecutionError(
            f"Native adapter response has unsupported status: {status!r}"
        )

