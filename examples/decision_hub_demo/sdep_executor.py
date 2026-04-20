from __future__ import annotations

import os
import shlex
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from spice.executors.sdep import SDEPTransport, SubprocessSDEPTransport
from spice.executors.sdep_mapping import build_sdep_execute_request
from spice.protocols.execution import ExecutionIntent
from spice.protocols.sdep import SDEPExecuteRequest, SDEPExecuteResponse

from examples.decision_hub_demo.execution_adapter import ExecutionOutcome, ExecutionRequest


DEMO_DELEGATE_ACTION_TYPE = "delegate_to_executor"
SDEP_DELEGATE_ACTION_TYPE = "decision_hub.delegate_to_executor"
SUPPORTED_DEMO_ACTION_TYPES = {DEMO_DELEGATE_ACTION_TYPE, SDEP_DELEGATE_ACTION_TYPE}
SDEP_EXECUTOR_ADAPTER = "decision_hub_demo.sdep_executor"
SDEP_COMMAND_ENV = "SPICE_DECISION_HUB_SDEP_COMMAND"
SDEP_TIMEOUT_ENV = "SPICE_DECISION_HUB_SDEP_TIMEOUT_SECONDS"
DEFAULT_SDEP_TIMEOUT_SECONDS = 120.0


class SDEPBackedExecutor:
    """Demo-side executor adapter that routes ExecutionRequest through SDEP.

    This is the canonical demo execution boundary. Tests and legacy callers can
    still inject another Executor explicitly, but the public demo default should
    route through an SDEP execute.request and return a demo ExecutionOutcome.
    """

    name = "sdep"

    def __init__(
        self,
        transport: SDEPTransport,
        *,
        executor_name: str = "hermes-sdep",
    ) -> None:
        self.transport = transport
        self.name = executor_name

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        try:
            intent = execution_request_to_intent(request)
            sdep_request = execution_intent_to_sdep_request(intent)
            response_payload = self.transport.execute(sdep_request)
            return sdep_response_to_execution_outcome(request, response_payload)
        except Exception as exc:
            return _failed_outcome(
                request,
                summary=f"SDEP execution failed before a valid response was produced: {exc}",
                blocking_issue="sdep_executor_error",
                metadata={
                    "executor": self.name,
                    "adapter": SDEP_EXECUTOR_ADAPTER,
                    "sdep_boundary": "demo_executor",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "execution_id": request.execution_id,
                    "decision_id": request.decision_id,
                    "trace_ref": _trace_ref(request),
                    "acted_on": request.acted_on,
                },
            )


def create_default_sdep_executor(*, env: dict[str, str] | None = None) -> SDEPBackedExecutor:
    """Build the default Hermes-backed SDEP executor for the demo path."""

    effective_env = dict(os.environ if env is None else env)
    transport = SubprocessSDEPTransport(
        command=_default_sdep_command(effective_env),
        timeout_seconds=_default_sdep_timeout(effective_env),
        env=_default_transport_env(effective_env),
    )
    return SDEPBackedExecutor(transport, executor_name="hermes-sdep")


def execution_request_to_intent(request: ExecutionRequest) -> ExecutionIntent:
    if request.action_type not in SUPPORTED_DEMO_ACTION_TYPES:
        raise ValueError(f"Unsupported SDEP-backed demo action: {request.action_type}")

    trace_ref = _trace_ref(request)
    success_criteria = _success_criteria_from_request(request)
    target: dict[str, Any] = {
        "kind": "work_item" if request.acted_on else "unknown",
        "id": request.acted_on or "unknown",
    }
    if request.params.get("target_title"):
        target["title"] = request.params["target_title"]
    if request.params.get("target_url"):
        target["url"] = request.params["target_url"]

    return ExecutionIntent(
        id=request.execution_id,
        refs=_refs(request, trace_ref),
        intent_type="decision_hub.execution_request",
        status="planned",
        objective={
            "id": request.decision_id,
            "description": "Execute the selected Spice decision action through SDEP.",
        },
        executor_type=request.executor or "sdep",
        target=target,
        operation={
            "name": SDEP_DELEGATE_ACTION_TYPE,
            "mode": "sync",
            "dry_run": False,
        },
        input_payload={
            "decision_id": request.decision_id,
            "trace_ref": trace_ref,
            "acted_on": request.acted_on,
            "selected_action": SDEP_DELEGATE_ACTION_TYPE,
            "demo_action_type": request.action_type,
        },
        parameters=dict(request.params),
        constraints=[],
        success_criteria=success_criteria,
        failure_policy={"strategy": "fail_fast", "max_retries": 0},
        provenance={
            "adapter": SDEP_EXECUTOR_ADAPTER,
            "execution_id": request.execution_id,
            "spice_decision_id": request.decision_id,
            "trace_ref": trace_ref,
            "acted_on": request.acted_on,
            "demo_action_type": request.action_type,
            "created_at": request.created_at,
        },
        metadata={
            "source_execution_request": request.to_payload(),
        },
    )


def execution_intent_to_sdep_request(intent: ExecutionIntent) -> SDEPExecuteRequest:
    request = build_sdep_execute_request(
        intent,
        metadata={
            "runtime": "spice",
            "adapter": SDEP_EXECUTOR_ADAPTER,
            "demo_domain": "decision_hub_demo",
        },
    )
    provenance = dict(intent.provenance)
    request.traceability.update(
        {
            "execution_id": intent.id,
            "spice_decision_id": str(provenance.get("spice_decision_id", "")),
            "trace_ref": str(provenance.get("trace_ref", "")),
            "acted_on": provenance.get("acted_on"),
        }
    )
    request.execution.metadata.update(
        {
            "adapter": SDEP_EXECUTOR_ADAPTER,
            "demo_action_type": str(provenance.get("demo_action_type", "")),
        }
    )
    request.validate()
    return request


def sdep_response_to_execution_outcome(
    request: ExecutionRequest,
    response_payload: dict[str, Any] | SDEPExecuteResponse,
) -> ExecutionOutcome:
    try:
        response = (
            response_payload
            if isinstance(response_payload, SDEPExecuteResponse)
            else SDEPExecuteResponse.from_dict(response_payload)
        )
    except Exception as exc:
        return _failed_outcome(
            request,
            summary=f"SDEP executor returned an invalid response: {exc}",
            blocking_issue="invalid_sdep_response",
            metadata={
                "adapter": SDEP_EXECUTOR_ADAPTER,
                "sdep_response_status": "invalid",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "raw_response": response_payload if isinstance(response_payload, dict) else {},
            },
        )

    if response.status != "success":
        error = response.error
        code = error.code if error is not None else f"sdep_response_{response.status}"
        message = error.message if error is not None else f"SDEP response status was {response.status}"
        return _failed_outcome(
            request,
            summary=message,
            blocking_issue=code,
            metadata=_response_metadata(request, response)
            | {
                "sdep_error": error.to_dict() if error is not None else None,
            },
        )

    outcome = response.outcome
    output = dict(outcome.output)
    status = _normalize_outcome_status(output.get("status") or outcome.status)
    blocking_issue = output.get("blocking_issue")
    if blocking_issue is not None:
        blocking_issue = str(blocking_issue)
    if status == "failed" and not blocking_issue:
        blocking_issue = "sdep_outcome_failed"

    return ExecutionOutcome(
        status=status,
        elapsed_minutes=_coerce_int(
            output.get("elapsed_minutes"),
            fallback=_coerce_int(outcome.metrics.get("elapsed_minutes"), fallback=0),
        ),
        risk_change=_coerce_string(output.get("risk_change"), fallback="unknown"),
        followup_needed=_coerce_bool(
            output.get("followup_needed"),
            fallback=status in {"failed", "partial", "abandoned"},
        ),
        summary=_coerce_string(
            output.get("summary"),
            fallback=f"SDEP outcome status: {status}",
        ),
        execution_ref=_coerce_string(
            output.get("execution_ref"),
            fallback=outcome.execution_id or f"sdep.{request.execution_id}",
        ),
        blocking_issue=blocking_issue,
        metadata=_response_metadata(request, response)
        | {
            "sdep_output": output,
            "sdep_artifacts": list(outcome.artifacts),
            "sdep_metrics": dict(outcome.metrics),
            "sdep_outcome_metadata": dict(outcome.metadata),
        },
    )


def _success_criteria_from_request(request: ExecutionRequest) -> list[dict[str, Any]]:
    value = request.params.get("success_criteria")
    if isinstance(value, str) and value.strip():
        return [
            {
                "id": "decision_hub.execution_success",
                "description": value.strip(),
            }
        ]
    if isinstance(value, list):
        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(value):
            if isinstance(item, dict):
                normalized.append(dict(item))
            elif isinstance(item, str) and item.strip():
                normalized.append(
                    {
                        "id": f"decision_hub.execution_success.{idx}",
                        "description": item.strip(),
                    }
                )
        return normalized
    return []


def _response_metadata(
    request: ExecutionRequest,
    response: SDEPExecuteResponse,
) -> dict[str, Any]:
    return {
        "adapter": SDEP_EXECUTOR_ADAPTER,
        "execution_id": request.execution_id,
        "decision_id": request.decision_id,
        "trace_ref": _trace_ref(request),
        "acted_on": request.acted_on,
        "sdep_response_status": response.status,
        "sdep_outcome_status": response.outcome.status,
        "sdep_request_id": response.request_id,
        "sdep_responder": response.responder.to_dict(),
        "sdep_response_metadata": dict(response.metadata),
        "sdep_traceability": dict(response.traceability),
    }


def _failed_outcome(
    request: ExecutionRequest,
    *,
    summary: str,
    blocking_issue: str,
    metadata: dict[str, Any],
) -> ExecutionOutcome:
    return ExecutionOutcome(
        status="failed",
        elapsed_minutes=0,
        risk_change="unknown",
        followup_needed=True,
        summary=summary,
        execution_ref=f"sdep.{request.execution_id}",
        blocking_issue=blocking_issue,
        metadata={
            "adapter": SDEP_EXECUTOR_ADAPTER,
            "execution_id": request.execution_id,
            "decision_id": request.decision_id,
            "trace_ref": _trace_ref(request),
            "acted_on": request.acted_on,
        }
        | dict(metadata),
    )


def _refs(request: ExecutionRequest, trace_ref: str) -> list[str]:
    refs = [request.execution_id, request.decision_id]
    if trace_ref:
        refs.append(trace_ref)
    if request.acted_on:
        refs.append(request.acted_on)
    return refs


def _trace_ref(request: ExecutionRequest) -> str:
    value = request.params.get("trace_ref")
    return str(value) if value is not None else ""


def _normalize_outcome_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"success", "succeeded", "ok", "completed"}:
        return "success"
    if normalized in {"failed", "failure", "error", "rejected"}:
        return "failed"
    if normalized in {"partial", "partially_completed"}:
        return "partial"
    if normalized in {"abandoned", "cancelled", "canceled", "skipped"}:
        return "abandoned"
    return "failed"


def _coerce_bool(value: Any, *, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    return fallback


def _coerce_int(value: Any, *, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_string(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def execution_request_payload(request: ExecutionRequest) -> dict[str, Any]:
    """Small debug helper used by tests and local inspection."""
    return asdict(request)


def _default_sdep_command(env: dict[str, str]) -> list[str]:
    raw = env.get(SDEP_COMMAND_ENV)
    if raw and raw.strip():
        return shlex.split(raw)
    return [
        sys.executable,
        "-m",
        "spice_hermes_bridge.integrations.hermes_sdep_agent",
    ]


def _default_sdep_timeout(env: dict[str, str]) -> float:
    raw = env.get(SDEP_TIMEOUT_ENV)
    try:
        parsed = float(raw) if raw is not None else DEFAULT_SDEP_TIMEOUT_SECONDS
    except ValueError:
        return DEFAULT_SDEP_TIMEOUT_SECONDS
    return parsed if parsed > 0 else DEFAULT_SDEP_TIMEOUT_SECONDS


def _default_transport_env(env: dict[str, str]) -> dict[str, str]:
    transport_env = dict(env)
    repo_root = Path(__file__).resolve().parents[2]
    bridge_root = repo_root / "spice-hermes-bridge"
    paths = [str(bridge_root), str(repo_root)]
    existing_pythonpath = transport_env.get("PYTHONPATH")
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    transport_env["PYTHONPATH"] = os.pathsep.join(paths)
    return transport_env
