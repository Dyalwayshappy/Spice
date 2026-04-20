from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable

from spice.protocols import SDEPExecuteRequest


EXECUTION_STATUSES = {"success", "failed", "partial", "abandoned"}
RISK_CHANGES = {"reduced", "increased", "unchanged", "unknown"}
ILLEGAL_NATIVE_FIELDS = {"selected_action", "recommendation", "best_option"}
REQUIRED_NATIVE_FIELDS = {
    "status",
    "elapsed_minutes",
    "risk_change",
    "followup_needed",
    "summary",
}
OPTIONAL_NATIVE_FIELDS = {"blocking_issue", "execution_ref"}
ALLOWED_NATIVE_FIELDS = REQUIRED_NATIVE_FIELDS | OPTIONAL_NATIVE_FIELDS
NORMALIZED_OUTCOME_SCHEMA = "hermes_native_outcome.v1"


class HermesNativeError(Exception):
    """Base error for native Hermes invocation failures."""


class HermesNativeTimeout(HermesNativeError):
    """Hermes did not return within the configured timeout."""

    def __init__(self, message: str, *, timeout_seconds: float) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds

    def to_details(self) -> dict[str, Any]:
        return {"timeout_seconds": self.timeout_seconds}


class HermesNativeSubprocessError(HermesNativeError):
    """Hermes subprocess failed before producing a usable task outcome."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        stderr_excerpt: str | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr_excerpt = stderr_excerpt

    def to_details(self) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if self.exit_code is not None:
            details["exit_code"] = self.exit_code
        if self.stderr_excerpt:
            details["stderr_excerpt"] = self.stderr_excerpt
        return details


@dataclass(slots=True)
class HermesNativeOutcome:
    status: str
    elapsed_minutes: int
    risk_change: str
    followup_needed: bool
    summary: str
    blocking_issue: str | None = None
    execution_ref: str = ""
    raw_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "elapsed_minutes": self.elapsed_minutes,
            "risk_change": self.risk_change,
            "followup_needed": self.followup_needed,
            "summary": self.summary,
            "blocking_issue": self.blocking_issue,
            "execution_ref": self.execution_ref,
            "raw_output": self.raw_output,
            "metadata": dict(self.metadata),
        }


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class HermesCodexNativeRunner:
    """
    Internal Hermes/Codex native invocation layer for the SDEP wrapper.

    This is intentionally not exposed as a public executor path. The public boundary is
    the SDEP wrapper; this class only hides how Hermes is invoked underneath it.
    """

    def __init__(
        self,
        *,
        hermes_command: str = "hermes",
        timeout_seconds: float = 180.0,
        runner: CommandRunner | None = None,
    ) -> None:
        self.hermes_command = hermes_command
        self.timeout_seconds = timeout_seconds
        self._runner = runner or subprocess.run

    def execute(self, request: SDEPExecuteRequest) -> HermesNativeOutcome:
        prompt = build_hermes_codex_sdep_prompt(request)
        command = [self.hermes_command, "chat", "-q", prompt]
        started = time.monotonic()
        try:
            completed = self._runner(
                command,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HermesNativeTimeout(
                f"Hermes timed out after {self.timeout_seconds:.1f}s",
                timeout_seconds=self.timeout_seconds,
            ) from exc
        except OSError as exc:
            raise HermesNativeSubprocessError(str(exc)) from exc

        elapsed_seconds = max(0.0, time.monotonic() - started)
        stdout = str(completed.stdout or "")
        stderr = str(completed.stderr or "")
        if completed.returncode != 0:
            stderr_excerpt = stderr[:300]
            raise HermesNativeSubprocessError(
                f"Hermes exited with code {completed.returncode}: {stderr_excerpt}",
                exit_code=completed.returncode,
                stderr_excerpt=stderr_excerpt,
            )

        return normalize_hermes_sdep_output(
            request,
            raw_output=stdout,
            elapsed_seconds=elapsed_seconds,
            command=command[:3],
        )


def build_hermes_codex_sdep_prompt(request: SDEPExecuteRequest) -> str:
    execution = request.execution
    payload = {
        "request_id": request.request_id,
        "idempotency_key": request.idempotency_key,
        "action_type": execution.action_type,
        "target": execution.target,
        "parameters": execution.parameters,
        "input": execution.input,
        "constraints": execution.constraints,
        "success_criteria": execution.success_criteria,
        "failure_policy": execution.failure_policy,
        "traceability": request.traceability,
        "metadata": request.metadata,
    }
    return (
        "You are Hermes/Codex executing one delegated task for Spice through SDEP.\n"
        "Return exactly one JSON object and no prose.\n"
        "Do not choose a recommendation, do not select an action, and do not add new actions.\n"
        "You are only reporting the execution outcome for the already-selected action.\n\n"
        "Required JSON schema:\n"
        "{\n"
        '  "status": "success|failed|partial|abandoned",\n'
        '  "elapsed_minutes": 0,\n'
        '  "risk_change": "reduced|increased|unchanged|unknown",\n'
        '  "followup_needed": true,\n'
        '  "summary": "short factual outcome",\n'
        '  "blocking_issue": null\n'
        "}\n\n"
        "Forbidden fields: selected_action, recommendation, best_option.\n\n"
        "SDEP request:\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )


def normalize_hermes_sdep_output(
    request: SDEPExecuteRequest,
    *,
    raw_output: str,
    elapsed_seconds: float,
    command: list[str],
) -> HermesNativeOutcome:
    payload, parse_error = _extract_json_object(raw_output)
    if payload is None:
        return _failed_native_outcome(
            request,
            raw_output=raw_output,
            elapsed_seconds=elapsed_seconds,
            command=command,
            blocking_issue="invalid_hermes_output",
            summary="Hermes/Codex returned non-JSON output.",
            parse_error=parse_error,
        )

    validation_error = _validate_native_payload(payload)
    if validation_error:
        return _failed_native_outcome(
            request,
            raw_output=raw_output,
            elapsed_seconds=elapsed_seconds,
            command=command,
            blocking_issue="invalid_hermes_output",
            summary=f"Hermes/Codex returned invalid outcome JSON: {validation_error}",
            parsed_payload=payload,
        )

    return HermesNativeOutcome(
        status=str(payload["status"]),
        elapsed_minutes=int(payload["elapsed_minutes"]),
        risk_change=str(payload["risk_change"]),
        followup_needed=bool(payload["followup_needed"]),
        summary=str(payload["summary"]).strip(),
        blocking_issue=_optional_string(payload.get("blocking_issue")),
        execution_ref=str(
            payload.get("execution_ref")
            or _execution_ref(request, payload)
        ),
        raw_output=raw_output,
        metadata={
            "schema": NORMALIZED_OUTCOME_SCHEMA,
            "native_runner": "hermes.chat",
            "command": command,
            "parsed_json": True,
            "output_valid": True,
            "normalization_status": "valid",
            "elapsed_seconds": elapsed_seconds,
        },
    )


def _failed_native_outcome(
    request: SDEPExecuteRequest,
    *,
    raw_output: str,
    elapsed_seconds: float,
    command: list[str],
    blocking_issue: str,
    summary: str,
    parse_error: str | None = None,
    parsed_payload: dict[str, Any] | None = None,
) -> HermesNativeOutcome:
    metadata: dict[str, Any] = {
        "schema": NORMALIZED_OUTCOME_SCHEMA,
        "native_runner": "hermes.chat",
        "command": command,
        "parsed_json": parsed_payload is not None,
        "output_valid": False,
        "normalization_status": "failed",
        "elapsed_seconds": elapsed_seconds,
        "failure_kind": blocking_issue,
    }
    if parse_error:
        metadata["parse_error"] = parse_error
    if parsed_payload is not None:
        metadata["invalid_payload_keys"] = sorted(parsed_payload.keys())
    return HermesNativeOutcome(
        status="failed",
        elapsed_minutes=max(0, round(elapsed_seconds / 60)),
        risk_change="unknown",
        followup_needed=True,
        summary=summary,
        blocking_issue=blocking_issue,
        execution_ref=_execution_ref(request, {"failure_kind": blocking_issue}),
        raw_output=raw_output,
        metadata=metadata,
    )


def _extract_json_object(raw_output: str) -> tuple[dict[str, Any] | None, str | None]:
    text = raw_output.strip()
    if not text:
        return None, "empty_output"

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "json_root_not_object"
    return payload, None


def _validate_native_payload(payload: dict[str, Any]) -> str | None:
    illegal = sorted(ILLEGAL_NATIVE_FIELDS.intersection(payload))
    if illegal:
        return f"forbidden fields present: {', '.join(illegal)}"

    missing = sorted(REQUIRED_NATIVE_FIELDS.difference(payload))
    if missing:
        return f"missing required fields: {', '.join(missing)}"

    unknown = sorted(set(payload).difference(ALLOWED_NATIVE_FIELDS))
    if unknown:
        return f"unknown fields present: {', '.join(unknown)}"

    status = payload.get("status")
    if status not in EXECUTION_STATUSES:
        return "status must be one of success, failed, partial, abandoned"

    elapsed = payload.get("elapsed_minutes")
    if type(elapsed) is not int or elapsed < 0:
        return "elapsed_minutes must be a non-negative integer"

    risk_change = payload.get("risk_change")
    if risk_change not in RISK_CHANGES:
        return "risk_change must be one of reduced, increased, unchanged, unknown"

    followup_needed = payload.get("followup_needed")
    if type(followup_needed) is not bool:
        return "followup_needed must be a boolean"

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return "summary must be a non-empty string"

    blocking_issue = payload.get("blocking_issue")
    if blocking_issue is not None and not isinstance(blocking_issue, str):
        return "blocking_issue must be null or string"

    execution_ref = payload.get("execution_ref")
    if execution_ref is not None:
        if not isinstance(execution_ref, str):
            return "execution_ref must be a string when provided"
        if not execution_ref.strip():
            return "execution_ref must be non-empty when provided"

    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _execution_ref(request: SDEPExecuteRequest, payload: dict[str, Any]) -> str:
    seed = json.dumps(
        {
            "request_id": request.request_id,
            "idempotency_key": request.idempotency_key,
            "payload": payload,
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    digest = sha256(seed.encode("utf-8")).hexdigest()[:10]
    return f"hermes.codex.{request.request_id}.{digest}"
