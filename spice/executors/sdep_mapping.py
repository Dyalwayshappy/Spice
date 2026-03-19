from __future__ import annotations

from typing import Any
from uuid import uuid4

from spice.protocols.execution import ExecutionIntent
from spice.protocols.sdep import (
    SDEPDescribeQuery,
    SDEPDescribeRequest,
    SDEPEndpointIdentity,
    SDEPExecutionPayload,
    SDEPExecuteRequest,
)


def spice_runtime_sender_identity() -> SDEPEndpointIdentity:
    return SDEPEndpointIdentity(
        id="spice.runtime",
        name="Spice Runtime",
        version="0.1",
        vendor="Spice",
        implementation="spice-runtime",
        role="brain",
    )


def build_sdep_execute_request(
    intent: ExecutionIntent,
    *,
    request_id: str | None = None,
    sender: SDEPEndpointIdentity | None = None,
    metadata: dict[str, Any] | None = None,
) -> SDEPExecuteRequest:
    operation = dict(intent.operation)
    execution = SDEPExecutionPayload(
        action_type=str(operation.get("name", intent.intent_type)),
        target=dict(intent.target),
        parameters=dict(intent.parameters),
        input=dict(intent.input_payload),
        constraints=list(intent.constraints),
        success_criteria=list(intent.success_criteria),
        failure_policy=dict(intent.failure_policy),
        mode=str(operation.get("mode", "sync")),
        dry_run=bool(operation.get("dry_run", False)),
        metadata={"intent_type": intent.intent_type},
    )

    traceability = {
        "spice": {
            "intent_id": intent.id,
            "intent_type": intent.intent_type,
            "executor_type": intent.executor_type,
            "objective": dict(intent.objective),
            "refs": list(intent.refs),
            "provenance": dict(intent.provenance),
        }
    }

    request = SDEPExecuteRequest(
        request_id=request_id or f"sdep-req-{uuid4().hex}",
        execution=execution,
        sender=sender or spice_runtime_sender_identity(),
        idempotency_key=intent.id,
        traceability=traceability,
        metadata=dict(metadata or {}),
    )
    request.validate()
    return request


def build_sdep_describe_request(
    *,
    request_id: str | None = None,
    sender: SDEPEndpointIdentity | None = None,
    action_types: list[str] | None = None,
    include_capabilities: bool = True,
    metadata: dict[str, Any] | None = None,
) -> SDEPDescribeRequest:
    request = SDEPDescribeRequest(
        request_id=request_id or f"sdep-req-{uuid4().hex}",
        sender=sender or spice_runtime_sender_identity(),
        query=SDEPDescribeQuery(
            include_capabilities=include_capabilities,
            action_types=list(action_types or []),
        ),
        metadata=dict(metadata or {}),
    )
    request.validate()
    return request
