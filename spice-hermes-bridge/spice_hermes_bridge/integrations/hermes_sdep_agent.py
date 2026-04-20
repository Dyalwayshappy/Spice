from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from spice.executors.sdep import build_error_response
from spice.protocols import (
    SDEP_AGENT_DESCRIBE_REQUEST,
    SDEPActionCapability,
    SDEPAgentDescription,
    SDEPDescribeRequest,
    SDEPDescribeResponse,
    SDEPEndpointIdentity,
    SDEPExecuteRequest,
    SDEPExecuteResponse,
    SDEPExecutionOutcome,
    SDEPProtocolSupport,
)
from spice.protocols.sdep import SDEP_EXECUTE_REQUEST, SDEP_ROLE_EXECUTOR, SDEP_VERSION

from spice_hermes_bridge.integrations.hermes_sdep_native import (
    HermesCodexNativeRunner,
    HermesNativeOutcome,
    HermesNativeSubprocessError,
    HermesNativeTimeout,
)


DELEGATE_ACTION_TYPE = "decision_hub.delegate_to_executor"
SUPPORTED_ACTION_TYPES = {DELEGATE_ACTION_TYPE}

RESPONDER = SDEPEndpointIdentity(
    id="agent.hermes_codex",
    name="Hermes Codex SDEP Executor",
    version="0.1.0",
    vendor="Spice Hermes Bridge",
    implementation="hermes-sdep-wrapper",
    role=SDEP_ROLE_EXECUTOR,
)


def handle_payload(
    payload: dict[str, Any],
    *,
    native_runner: HermesCodexNativeRunner | None = None,
) -> dict[str, Any]:
    message_type = str(payload.get("message_type", ""))
    if message_type == SDEP_EXECUTE_REQUEST:
        return _handle_execute(payload, native_runner=native_runner)
    if message_type == SDEP_AGENT_DESCRIBE_REQUEST:
        return _handle_describe(payload)
    return build_error_response(
        str(payload.get("request_id", "unknown")),
        responder=RESPONDER,
        code="sdep.message_type.unsupported",
        message=f"Unsupported SDEP message_type: {message_type!r}",
        retryable=False,
        details={"message_type": message_type},
    )


def _handle_execute(
    payload: dict[str, Any],
    *,
    native_runner: HermesCodexNativeRunner | None,
) -> dict[str, Any]:
    try:
        request = SDEPExecuteRequest.from_dict(payload)
    except Exception as exc:
        return build_error_response(
            str(payload.get("request_id", "unknown")),
            responder=RESPONDER,
            code="sdep.execute_request.invalid",
            message=str(exc),
            retryable=False,
        )

    action_type = request.execution.action_type
    if action_type not in SUPPORTED_ACTION_TYPES:
        return build_error_response(
            request.request_id,
            responder=RESPONDER,
            code="sdep.action.unsupported",
            message=f"Hermes SDEP wrapper only supports {sorted(SUPPORTED_ACTION_TYPES)}.",
            retryable=False,
            details={"action_type": action_type},
        )

    runner = native_runner or HermesCodexNativeRunner()
    try:
        native_outcome = runner.execute(request)
    except HermesNativeTimeout as exc:
        return build_error_response(
            request.request_id,
            responder=RESPONDER,
            code="hermes.timeout",
            message=str(exc),
            retryable=True,
            details=exc.to_details(),
        )
    except HermesNativeSubprocessError as exc:
        return build_error_response(
            request.request_id,
            responder=RESPONDER,
            code="hermes.subprocess_failed",
            message=str(exc),
            retryable=True,
            details=exc.to_details(),
        )

    return _build_execute_response(request, native_outcome)


def _build_execute_response(
    request: SDEPExecuteRequest,
    native_outcome: HermesNativeOutcome,
) -> dict[str, Any]:
    output = {
        "decision_id": _first_string(
            request.execution.input.get("decision_id"),
            request.traceability.get("decision_id"),
            request.traceability.get("spice_decision_id"),
        ),
        "selected_action": _first_string(
            request.execution.input.get("selected_action"),
            request.execution.action_type,
        ),
        "acted_on": _first_string(
            request.execution.input.get("acted_on"),
            request.execution.target.get("id"),
        ),
        "status": native_outcome.status,
        "elapsed_minutes": native_outcome.elapsed_minutes,
        "risk_change": native_outcome.risk_change,
        "followup_needed": native_outcome.followup_needed,
        "summary": native_outcome.summary,
        "blocking_issue": native_outcome.blocking_issue,
        "execution_ref": native_outcome.execution_ref,
    }
    outcome = SDEPExecutionOutcome(
        execution_id=native_outcome.execution_ref,
        status=native_outcome.status,
        outcome_type="observation",
        output=output,
        metrics={"elapsed_minutes": native_outcome.elapsed_minutes},
        metadata={
            "executor": "hermes_codex",
            "native_runner": "hermes.chat",
            "sdep_wrapper": "hermes_sdep_agent",
            **native_outcome.metadata,
        },
    )
    return SDEPExecuteResponse(
        request_id=request.request_id,
        status="success",
        responder=RESPONDER,
        outcome=outcome,
        traceability=dict(request.traceability),
        metadata={
            "boundary": "spice-hermes-sdep",
            "native_call_hidden": True,
            "action_type": request.execution.action_type,
        },
    ).to_dict()


def _handle_describe(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        request = SDEPDescribeRequest.from_dict(payload)
    except Exception as exc:
        return build_error_response(
            str(payload.get("request_id", "unknown")),
            responder=RESPONDER,
            code="sdep.describe_request.invalid",
            message=str(exc),
            retryable=False,
        )

    requested = set(request.query.action_types)
    capabilities = [_delegate_capability()]
    if requested:
        capabilities = [
            capability for capability in capabilities if capability.action_type in requested
        ]
    description = SDEPAgentDescription(
        protocol_support=SDEPProtocolSupport(
            versions=[SDEP_VERSION],
            metadata={"canonical_boundary": "execution"},
        ),
        capabilities=capabilities if request.query.include_capabilities else [],
        capability_version="0.1.0",
        summary="SDEP wrapper around Hermes/Codex for delegated execution.",
        metadata={
            "native_invocation": "hermes chat -q",
            "native_invocation_exposed": False,
        },
    )
    return SDEPDescribeResponse(
        request_id=request.request_id,
        status="success",
        responder=RESPONDER,
        description=description,
        metadata={"boundary": "spice-hermes-sdep"},
    ).to_dict()


def _delegate_capability() -> SDEPActionCapability:
    return SDEPActionCapability(
        action_type=DELEGATE_ACTION_TYPE,
        target_kinds=["work_item"],
        mode_support=["sync"],
        dry_run_supported=False,
        side_effect_class="external_effect",
        outcome_type="observation",
        semantic_inputs=[
            "decision_id",
            "selected_action",
            "acted_on",
            "target_url",
            "success_criteria",
        ],
        input_expectation=(
            "input should identify the Spice decision and work item being delegated"
        ),
        parameter_expectation=(
            "parameters may include scope, time_budget_minutes, target_title, "
            "target_url, and success_criteria"
        ),
        metadata={
            "executor": "codex",
            "requires_confirmation": True,
            "supported_scopes": ["triage", "review_summary"],
        },
    )


def _first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def main(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    native_runner: HermesCodexNativeRunner | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        payload = json.loads(stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("SDEP wrapper input must be a JSON object.")
    except Exception as exc:
        response = build_error_response(
            "unknown",
            responder=RESPONDER,
            code="sdep.input.invalid_json",
            message=str(exc),
            retryable=False,
        )
    else:
        response = handle_payload(payload, native_runner=native_runner)
    stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True))
    stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
