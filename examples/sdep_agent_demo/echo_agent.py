from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from uuid import uuid4

RESPONDER = {
    "id": "agent.echo",
    "name": "Echo Agent",
    "version": "0.1",
    "vendor": "ExampleVendor",
    "implementation": "echo-agent",
    "role": "executor",
}


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        _write_response(
            _error_response(
                request_id="",
                code="request.empty",
                message="No request payload was provided.",
            )
        )
        return 1

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        _write_response(
            _error_response(
                request_id="",
                code="request.invalid_json",
                message="Request payload is not valid JSON.",
            )
        )
        return 1

    request_id = str(payload.get("request_id", ""))
    execution = payload.get("execution", {})
    if not isinstance(execution, dict):
        _write_response(
            _error_response(
                request_id=request_id,
                code="request.invalid_execution",
                message="Request payload must include object field execution.",
            )
        )
        return 1

    operation_name = str(execution.get("action_type", "unknown.operation"))
    target = execution.get("target", {})
    if not isinstance(target, dict):
        target = {}

    if operation_name == "demo.fail":
        _write_response(
            _error_response(
                request_id=request_id,
                code="operation.rejected",
                message="Requested operation is intentionally rejected by demo agent.",
                details={"operation": operation_name},
            )
        )
        return 0

    response = _base_response(
        request_id=request_id,
        status="success",
        outcome={
            "execution_id": f"exec-{uuid4().hex}",
            "status": "success",
            "outcome_type": "observation",
            "output": {
                "executed": True,
                "operation": operation_name,
                "target": target,
                "agent_timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "artifacts": [],
            "metrics": {},
            "metadata": {
                "result_type": "sdep.demo.echo",
                "executor": "echo-agent",
            },
        },
        metadata={"agent": "echo_agent.py"},
    )
    _write_response(response)
    return 0


def _error_response(
    *,
    request_id: str,
    code: str,
    message: str,
    details: dict | None = None,
) -> dict:
    return _base_response(
        request_id=request_id,
        status="error",
        outcome={
            "execution_id": "",
            "status": "failed",
            "outcome_type": "error",
            "output": {},
            "artifacts": [],
            "metrics": {},
            "metadata": {"executor": "echo-agent"},
        },
        error={
            "code": code,
            "message": message,
            "retryable": False,
            "details": dict(details or {}),
        },
    )


def _base_response(
    *,
    request_id: str,
    status: str,
    outcome: dict,
    error: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    payload = {
        "protocol": "sdep",
        "sdep_version": "0.1",
        "message_type": "execute.response",
        "message_id": f"sdep-msg-{uuid4().hex}",
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "responder": dict(RESPONDER),
        "status": status,
        "outcome": dict(outcome),
        "metadata": dict(metadata or {}),
    }
    if error is not None:
        payload["error"] = dict(error)
    return payload


def _write_response(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
