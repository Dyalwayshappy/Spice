from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
REPO_ROOT = THIS_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from adapter_contract import (  # noqa: E402
    NativeAdapterExecutionError,
    NativeAdapterRequest,
    NativeAdapterResult,
    NativeAdapterTimeoutError,
    NativeAgentAdapter,
)
from adapters.subprocess_json_adapter import SubprocessJsonAdapter  # noqa: E402
from spice.executors.sdep import build_error_response  # noqa: E402
from spice.protocols import (  # noqa: E402
    SDEPActionCapability,
    SDEPAgentDescription,
    SDEPDescribeRequest,
    SDEPDescribeResponse,
    SDEPEndpointIdentity,
    SDEPError,
    SDEPExecutionOutcome,
    SDEPExecuteRequest,
    SDEPExecuteResponse,
    SDEPProtocolSupport,
)
from spice.protocols.sdep import (  # noqa: E402
    SDEP_AGENT_DESCRIBE_REQUEST,
    SDEP_EXECUTE_REQUEST,
    SDEP_VERSION,
)


DEFAULT_CAPABILITY_ACTIONS = (
    "personal.gather_evidence",
    "personal.system",
    "personal.communicate",
    "personal.schedule",
)
DEFAULT_TARGET_KINDS = ("external.service", "service")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdep-wrapper-template",
        description=(
            "Thin SDEP wrapper template for bridging non-SDEP external agents."
        ),
    )
    parser.add_argument(
        "--adapter",
        choices=("subprocess-json",),
        default="subprocess-json",
        help="Internal wrapper adapter implementation.",
    )
    parser.add_argument(
        "--agent-command",
        type=str,
        default="",
        help=(
            "Command for the non-SDEP native agent subprocess. "
            "Required for --adapter=subprocess-json."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=20.0,
        help="Adapter subprocess timeout in seconds.",
    )
    parser.add_argument(
        "--capability-action",
        action="append",
        default=None,
        help="Static capability action_type to expose (repeatable).",
    )
    parser.add_argument(
        "--capability-target-kind",
        action="append",
        default=None,
        help="Static capability target kind to expose (repeatable).",
    )
    parser.add_argument("--responder-id", type=str, default="agent.sdep_wrapper_template")
    parser.add_argument("--responder-name", type=str, default="SDEP Wrapper Template")
    parser.add_argument("--responder-version", type=str, default="0.1")
    parser.add_argument("--responder-vendor", type=str, default="SpiceExamples")
    parser.add_argument(
        "--responder-implementation",
        type=str,
        default="sdep-wrapper-template",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    responder = _build_responder_identity(args)
    capability_actions = _resolve_capability_actions(args.capability_action)
    target_kinds = _resolve_target_kinds(args.capability_target_kind)
    adapter = _build_adapter(args)

    raw = sys.stdin.read()
    payload, parse_error = _parse_json_payload(raw)
    if parse_error is not None:
        _write_json(
            build_error_response(
                "",
                responder=responder,
                code="request.invalid",
                message=parse_error,
            )
        )
        return 0

    message_type = str(payload.get("message_type", "")).strip()
    if message_type == SDEP_EXECUTE_REQUEST:
        response = _handle_execute(
            payload=payload,
            adapter=adapter,
            responder=responder,
            capability_actions=capability_actions,
            adapter_name=args.adapter,
        )
        _write_json(response)
        return 0

    if message_type == SDEP_AGENT_DESCRIBE_REQUEST:
        response = _handle_describe(
            payload=payload,
            responder=responder,
            capability_actions=capability_actions,
            target_kinds=target_kinds,
        )
        _write_json(response)
        return 0

    request_id = ""
    if isinstance(payload, dict):
        request_id = str(payload.get("request_id", "")).strip()
    _write_json(
        build_error_response(
            request_id,
            responder=responder,
            code="request.invalid",
            message=(
                "Unsupported or missing message_type; expected "
                f"{SDEP_EXECUTE_REQUEST!r} or {SDEP_AGENT_DESCRIBE_REQUEST!r}."
            ),
        )
    )
    return 0


def _handle_execute(
    *,
    payload: dict[str, Any],
    adapter: NativeAgentAdapter,
    responder: SDEPEndpointIdentity,
    capability_actions: tuple[str, ...],
    adapter_name: str,
) -> dict[str, Any]:
    request_id_hint = str(payload.get("request_id", "")).strip()
    try:
        request = SDEPExecuteRequest.from_dict(payload)
    except Exception as exc:
        return build_error_response(
            request_id_hint,
            responder=responder,
            code="request.invalid",
            message=f"Invalid execute.request payload: {exc}",
        )

    action_type = request.execution.action_type
    if capability_actions and action_type not in capability_actions:
        return build_error_response(
            request.request_id,
            responder=responder,
            code="action.unsupported",
            message=f"Action type is not supported by this wrapper: {action_type!r}",
            details={"action_type": action_type},
        )

    adapter_request = NativeAdapterRequest(
        request_id=request.request_id,
        action_type=action_type,
        target=dict(request.execution.target),
        input_payload=dict(request.execution.input),
        parameters=dict(request.execution.parameters),
        constraints=[entry for entry in request.execution.constraints if isinstance(entry, dict)],
        success_criteria=[
            entry for entry in request.execution.success_criteria if isinstance(entry, dict)
        ],
        failure_policy=dict(request.execution.failure_policy),
        mode=request.execution.mode,
        dry_run=bool(request.execution.dry_run),
        idempotency_key=request.idempotency_key,
        traceability=dict(request.traceability),
        metadata=dict(request.execution.metadata),
    )
    try:
        adapter_result = adapter.execute(adapter_request)
    except NativeAdapterTimeoutError as exc:
        return build_error_response(
            request.request_id,
            responder=responder,
            code="adapter.timeout",
            message=str(exc),
            retryable=True,
            details={"action_type": action_type},
        )
    except NativeAdapterExecutionError as exc:
        return build_error_response(
            request.request_id,
            responder=responder,
            code="adapter.failed",
            message=str(exc),
            retryable=bool(exc.retryable),
            details={"action_type": action_type},
        )
    except Exception as exc:
        return build_error_response(
            request.request_id,
            responder=responder,
            code="adapter.failed",
            message=f"Unexpected adapter failure: {exc}",
            details={"action_type": action_type},
        )

    if adapter_result.status != "success":
        details: dict[str, Any] = {"action_type": action_type}
        if adapter_result.error_code:
            details["native_error_code"] = adapter_result.error_code
        if adapter_result.metadata:
            details["native_metadata"] = dict(adapter_result.metadata)
        return build_error_response(
            request.request_id,
            responder=responder,
            code="adapter.failed",
            message=adapter_result.error_message or "Native adapter reported failure.",
            retryable=bool(adapter_result.retryable),
            details=details,
        )

    return _build_execute_success_response(
        request=request,
        responder=responder,
        adapter_result=adapter_result,
        adapter_name=adapter_name,
    )


def _handle_describe(
    *,
    payload: dict[str, Any],
    responder: SDEPEndpointIdentity,
    capability_actions: tuple[str, ...],
    target_kinds: tuple[str, ...],
) -> dict[str, Any]:
    request_id_hint = str(payload.get("request_id", "")).strip()
    try:
        request = SDEPDescribeRequest.from_dict(payload)
    except Exception as exc:
        response = SDEPDescribeResponse(
            request_id=request_id_hint,
            status="error",
            responder=responder,
            description=SDEPAgentDescription(
                protocol_support=SDEPProtocolSupport(
                    protocol="sdep",
                    versions=[SDEP_VERSION],
                ),
                capabilities=[],
                capability_version="sdep-wrapper-template.v1",
                summary="Describe request validation failed.",
                metadata={"wrapper": "sdep_wrapper_template"},
            ),
            error=SDEPError(
                code="request.invalid",
                message=f"Invalid agent.describe.request payload: {exc}",
                retryable=False,
                details={},
            ),
            metadata={"wrapper": "sdep_wrapper_template"},
        )
        return response.to_dict()

    selected_actions = list(capability_actions)
    if request.query.include_capabilities and request.query.action_types:
        filter_set = {
            token.strip()
            for token in request.query.action_types
            if isinstance(token, str) and token.strip()
        }
        selected_actions = [action for action in selected_actions if action in filter_set]
    if not request.query.include_capabilities:
        selected_actions = []

    capabilities = [
        SDEPActionCapability(
            action_type=action_type,
            target_kinds=list(target_kinds),
            mode_support=["sync"],
            dry_run_supported=True,
            side_effect_class="external_effect",
            outcome_type="observation",
            semantic_inputs=["input_payload"],
            input_expectation="object payload",
            parameter_expectation="object payload",
            metadata={"wrapper_adapter": "subprocess-json"},
        )
        for action_type in selected_actions
    ]
    response = SDEPDescribeResponse(
        request_id=request.request_id,
        status="success",
        responder=responder,
        description=SDEPAgentDescription(
            protocol_support=SDEPProtocolSupport(
                protocol="sdep",
                versions=[SDEP_VERSION],
            ),
            capabilities=capabilities,
            capability_version="sdep-wrapper-template.v1",
            summary="Static capabilities for SDEP wrapper template.",
            metadata={"wrapper": "sdep_wrapper_template"},
        ),
        metadata={"wrapper": "sdep_wrapper_template"},
    )
    return response.to_dict()


def _build_execute_success_response(
    *,
    request: SDEPExecuteRequest,
    responder: SDEPEndpointIdentity,
    adapter_result: NativeAdapterResult,
    adapter_name: str,
) -> dict[str, Any]:
    outcome = SDEPExecutionOutcome(
        execution_id=adapter_result.execution_id or f"exec-{uuid4().hex}",
        status="success",
        outcome_type=adapter_result.outcome_type or "observation",
        output=dict(adapter_result.output),
        artifacts=[entry for entry in adapter_result.artifacts if isinstance(entry, dict)],
        metrics=dict(adapter_result.metrics),
        metadata={
            **dict(adapter_result.metadata),
            "wrapper_adapter": adapter_name,
        },
    )
    response = SDEPExecuteResponse(
        request_id=request.request_id,
        status="success",
        responder=responder,
        outcome=outcome,
        traceability={
            "wrapper": {
                "adapter": adapter_name,
                "source_request_id": request.request_id,
            }
        },
        metadata={"wrapper": "sdep_wrapper_template"},
    )
    return response.to_dict()


def _build_adapter(args: argparse.Namespace) -> NativeAgentAdapter:
    if args.adapter == "subprocess-json":
        command = shlex.split(str(args.agent_command or "").strip())
        if not command:
            raise ValueError(
                "--agent-command is required for --adapter=subprocess-json."
            )
        return SubprocessJsonAdapter(
            command,
            timeout_seconds=float(args.timeout_seconds),
        )
    raise ValueError(f"Unsupported adapter type: {args.adapter!r}")


def _build_responder_identity(args: argparse.Namespace) -> SDEPEndpointIdentity:
    return SDEPEndpointIdentity(
        id=str(args.responder_id),
        name=str(args.responder_name),
        version=str(args.responder_version),
        vendor=str(args.responder_vendor),
        implementation=str(args.responder_implementation),
        role="executor",
    )


def _resolve_capability_actions(raw: list[str] | None) -> tuple[str, ...]:
    if not raw:
        return tuple(DEFAULT_CAPABILITY_ACTIONS)
    normalized = [token.strip() for token in raw if isinstance(token, str) and token.strip()]
    if not normalized:
        return tuple(DEFAULT_CAPABILITY_ACTIONS)
    return tuple(dict.fromkeys([*DEFAULT_CAPABILITY_ACTIONS, *normalized]))


def _resolve_target_kinds(raw: list[str] | None) -> tuple[str, ...]:
    if not raw:
        return tuple(DEFAULT_TARGET_KINDS)
    normalized = [token.strip() for token in raw if isinstance(token, str) and token.strip()]
    if not normalized:
        return tuple(DEFAULT_TARGET_KINDS)
    return tuple(dict.fromkeys(normalized))


def _parse_json_payload(raw: str) -> tuple[dict[str, Any], str | None]:
    if not isinstance(raw, str) or not raw.strip():
        return {}, "No request payload was provided on stdin."
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"Request payload is not valid JSON: {exc}"
    if not isinstance(payload, dict):
        return {}, "Request payload must be a JSON object."
    return dict(payload), None


def _write_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
