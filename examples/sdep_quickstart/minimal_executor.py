"""
Minimal SDEP v0.1 Executor — stdin/stdout

This is the smallest possible SDEP-compliant executor.
It reads one execute.request from stdin and writes one execute.response to stdout.

Transport: subprocess stdin/stdout JSON
Protocol: SDEP v0.1

Run standalone (pipe a request):
    echo '<request_json>' | python3 minimal_executor.py

Run via Spice SDEPExecutor + SubprocessSDEPTransport:
    python3 run_quickstart.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from uuid import uuid4

# ---------------------------------------------------------------------------
# Executor identity — set these for your own executor
# ---------------------------------------------------------------------------
RESPONDER = {
    "id": "agent.minimal_quickstart",
    "name": "Minimal SDEP Quickstart Executor",
    "version": "0.1.0",
    "vendor": "quickstart",
    "implementation": "minimal-sdep-executor",
    "role": "executor",
}

SUPPORTED_PROTOCOL = "sdep"
SUPPORTED_VERSION = "0.1"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        _write_response(
            _protocol_error(
                request_id="",
                code="request.empty",
                message="No request payload received on stdin.",
            )
        )
        return 1

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _write_response(
            _protocol_error(
                request_id="",
                code="request.invalid_json",
                message=f"Request is not valid JSON: {exc}",
            )
        )
        return 1

    # --- 1. Validate protocol envelope ---
    if payload.get("protocol") != SUPPORTED_PROTOCOL:
        _write_response(
            _protocol_error(
                request_id=str(payload.get("request_id", "")),
                code="envelope.protocol_mismatch",
                message=(
                    f"Expected protocol={SUPPORTED_PROTOCOL!r}, "
                    f"got {payload.get('protocol')!r}."
                ),
            )
        )
        return 0

    if payload.get("sdep_version") != SUPPORTED_VERSION:
        _write_response(
            _protocol_error(
                request_id=str(payload.get("request_id", "")),
                code="envelope.version_unsupported",
                message=(
                    f"Expected sdep_version={SUPPORTED_VERSION!r}, "
                    f"got {payload.get('sdep_version')!r}."
                ),
            )
        )
        return 0

    message_type = str(payload.get("message_type", ""))
    request_id = str(payload.get("request_id", ""))

    # --- 2. Route by message_type ---
    if message_type == "agent.describe.request":
        _write_response(_describe_response(request_id=request_id))
        return 0

    if message_type == "execute.request":
        return _handle_execute(request_id=request_id, payload=payload)

    # Unknown message type
    _write_response(
        _protocol_error(
            request_id=request_id,
            code="envelope.message_type_unknown",
            message=f"Unsupported message_type: {message_type!r}.",
        )
    )
    return 0


# ---------------------------------------------------------------------------
# Execute handler
# ---------------------------------------------------------------------------

def _handle_execute(*, request_id: str, payload: dict) -> int:
    execution = payload.get("execution", {})
    if not isinstance(execution, dict):
        _write_response(
            _protocol_error(
                request_id=request_id,
                code="request.missing_execution",
                message="Field 'execution' is missing or not an object.",
            )
        )
        return 0

    action_type = str(execution.get("action_type", "unknown"))
    target = execution.get("target", {})
    if not isinstance(target, dict):
        target = {}

    # --- Execute the action (replace this with your own logic) ---
    output = _run_action(action_type=action_type, target=target, execution=execution)

    _write_response(
        _execute_response(
            request_id=request_id,
            status="success",
            outcome={
                "execution_id": f"exec-{uuid4().hex}",
                "status": "success",
                "outcome_type": "observation",
                "output": output,
                "artifacts": [],
                "metrics": {},
                "metadata": {
                    "executor": RESPONDER["implementation"],
                    "action_type": action_type,
                },
            },
        )
    )
    return 0


def _run_action(*, action_type: str, target: dict, execution: dict) -> dict:
    """
    Replace this function body with your actual execution logic.

    Inputs you typically read:
        action_type        — what to do (e.g. "triage.pr", "notify.slack")
        target             — what to do it on (kind, id, url, ...)
        execution.input    — structured input payload from Spice
        execution.parameters — domain-specific parameters

    Outputs you typically return (add your own domain fields):
        {
            "status": "success",
            "summary": "...",
            ...
        }
    """
    return {
        "executed": True,
        "action_type": action_type,
        "target_id": target.get("id", ""),
        "target_kind": target.get("kind", ""),
        "agent_timestamp": datetime.now(timezone.utc).isoformat(),
        "note": (
            "This is the minimal quickstart executor. "
            "Replace _run_action() with your own logic."
        ),
    }


# ---------------------------------------------------------------------------
# Capability discovery (agent.describe.request)
# ---------------------------------------------------------------------------

def _describe_response(*, request_id: str) -> dict:
    return {
        "protocol": SUPPORTED_PROTOCOL,
        "sdep_version": SUPPORTED_VERSION,
        "message_type": "agent.describe.response",
        "message_id": f"sdep-msg-{uuid4().hex}",
        "request_id": request_id,
        "timestamp": _now(),
        "responder": dict(RESPONDER),
        "description": {
            "protocol_support": {
                "protocol": SUPPORTED_PROTOCOL,
                "sdep_version": SUPPORTED_VERSION,
                "supported_message_types": [
                    "execute.request",
                    "agent.describe.request",
                ],
            },
            "capabilities": [
                {
                    "action_type": "quickstart.*",
                    "target_kinds": ["any"],
                    "mode_support": ["sync"],
                    "dry_run_supported": False,
                    "side_effect_class": "observation",
                    "outcome_type": "observation",
                    "semantic_inputs": [],
                }
            ],
        },
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def _execute_response(
    *,
    request_id: str,
    status: str,
    outcome: dict,
    error: dict | None = None,
) -> dict:
    payload: dict = {
        "protocol": SUPPORTED_PROTOCOL,
        "sdep_version": SUPPORTED_VERSION,
        "message_type": "execute.response",
        "message_id": f"sdep-msg-{uuid4().hex}",
        "request_id": request_id,
        "timestamp": _now(),
        "responder": dict(RESPONDER),
        "status": status,
        "outcome": outcome,
        "metadata": {},
    }
    if error is not None:
        payload["error"] = error
    return payload


def _protocol_error(
    *,
    request_id: str,
    code: str,
    message: str,
    retryable: bool = False,
    details: dict | None = None,
) -> dict:
    """
    Use status="error" for protocol / wrapper / transport failures.
    Keep outcome.status="failed" + outcome_type="error".
    """
    return _execute_response(
        request_id=request_id,
        status="error",
        outcome={
            "execution_id": "",
            "status": "failed",
            "outcome_type": "error",
            "output": {},
            "artifacts": [],
            "metrics": {},
            "metadata": {"executor": RESPONDER["implementation"]},
        },
        error={
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": dict(details or {}),
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_response(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
