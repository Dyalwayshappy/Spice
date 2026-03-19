from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from spice.executors.base import Executor
from spice.protocols import ExecutionIntent, ExecutionResult


ParserMode = Literal["json", "text"]


@dataclass(slots=True)
class CLIInvocation:
    argv: list[str]
    stdin_text: str = ""
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None

    def validate(self) -> None:
        if not self.argv:
            raise ValueError("CLIInvocation.argv must be a non-empty list.")
        for idx, part in enumerate(self.argv):
            if not isinstance(part, str) or not part.strip():
                raise ValueError(f"CLIInvocation.argv[{idx}] must be a non-empty string.")


@dataclass(slots=True)
class CLIActionMapping:
    action_type: str
    render_invocation: Callable[[Any], CLIInvocation]
    parser_mode: ParserMode = "text"
    default_outcome_type: str = "observation"
    success_exit_codes: tuple[int, ...] = (0,)

    def validate(self) -> None:
        if not self.action_type:
            raise ValueError("CLIActionMapping.action_type is required.")
        if self.parser_mode not in {"json", "text"}:
            raise ValueError("CLIActionMapping.parser_mode must be 'json' or 'text'.")
        if not self.success_exit_codes:
            raise ValueError("CLIActionMapping.success_exit_codes must not be empty.")


@dataclass(slots=True)
class CLIAdapterProfile:
    profile_id: str
    display_name: str
    action_mappings: dict[str, CLIActionMapping]
    default_timeout_seconds: float = 30.0
    base_env: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.profile_id:
            raise ValueError("CLIAdapterProfile.profile_id is required.")
        if not self.display_name:
            raise ValueError("CLIAdapterProfile.display_name is required.")
        if self.default_timeout_seconds <= 0:
            raise ValueError("CLIAdapterProfile.default_timeout_seconds must be > 0.")
        if not self.action_mappings:
            raise ValueError("CLIAdapterProfile.action_mappings must not be empty.")
        for action_key, mapping in self.action_mappings.items():
            mapping.validate()
            if mapping.action_type != action_key:
                raise ValueError(
                    "CLIAdapterProfile.action_mappings keys must match mapping.action_type: "
                    f"{action_key!r} != {mapping.action_type!r}"
                )


@dataclass(slots=True)
class _CLIRequestContext:
    intent: ExecutionIntent
    action_type: str
    target: dict[str, Any]
    input_payload: dict[str, Any]
    parameters: dict[str, Any]
    constraints: list[dict[str, Any]]
    mode: str
    dry_run: bool


@dataclass(slots=True)
class _CLIExecutionCapture:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool


class CLIAdapterExecutor(Executor):
    """
    Executor adapter that maps semantic action intents to external CLI invocations.

    This adapter is intentionally lightweight:
    - exact action_type matching only
    - private internal request normalization
    - JSON-first parsing when configured, text fallback otherwise
    """

    def __init__(
        self,
        profile: CLIAdapterProfile,
        *,
        executor_name: str = "cli-adapter",
    ) -> None:
        self.profile = profile
        self.executor_name = executor_name
        self.profile.validate()

    def execute(self, intent: ExecutionIntent) -> ExecutionResult:
        action_type = self._resolve_action_type(intent)
        if not action_type:
            return self._failed_result(
                intent,
                action_type="",
                result_type="error",
                error="Could not resolve action_type from intent.operation.name or intent.intent_type.",
                trace_payload={},
            )

        mapping = self.profile.action_mappings.get(action_type)
        if mapping is None:
            return self._failed_result(
                intent,
                action_type=action_type,
                result_type="error",
                error=f"No CLI mapping configured for action_type={action_type!r}.",
                trace_payload={
                    "available_action_types": sorted(self.profile.action_mappings.keys()),
                },
            )

        context = _CLIRequestContext(
            intent=intent,
            action_type=action_type,
            target=dict(intent.target),
            input_payload=dict(intent.input_payload),
            parameters=dict(intent.parameters),
            constraints=list(intent.constraints),
            mode=str(intent.operation.get("mode", "sync")),
            dry_run=bool(intent.operation.get("dry_run", False)),
        )

        try:
            invocation = mapping.render_invocation(context)
            invocation.validate()
        except Exception as exc:
            return self._failed_result(
                intent,
                action_type=action_type,
                result_type=mapping.default_outcome_type or "error",
                error=f"Failed to render CLI invocation: {exc}",
                trace_payload={},
            )

        timeout_seconds = (
            float(invocation.timeout_seconds)
            if invocation.timeout_seconds is not None
            else float(self.profile.default_timeout_seconds)
        )

        try:
            capture = self._run_subprocess(invocation, timeout_seconds=timeout_seconds)
        except subprocess.TimeoutExpired:
            return self._failed_result(
                intent,
                action_type=action_type,
                result_type="error",
                error=f"CLI invocation timed out after {timeout_seconds:.1f}s.",
                trace_payload={
                    "invocation": {
                        "argv": list(invocation.argv),
                        "cwd": invocation.cwd,
                        "timeout_seconds": timeout_seconds,
                        "parser_mode": mapping.parser_mode,
                    },
                    "capture": {
                        "exit_code": None,
                        "stdout": "",
                        "stderr": "",
                        "duration_ms": 0,
                        "timed_out": True,
                    },
                    "mapping": {
                        "action_type": mapping.action_type,
                        "default_outcome_type": mapping.default_outcome_type,
                        "success_exit_codes": list(mapping.success_exit_codes),
                    },
                },
            )
        except Exception as exc:
            return self._failed_result(
                intent,
                action_type=action_type,
                result_type="error",
                error=f"CLI invocation failed before completion: {exc}",
                trace_payload={
                    "invocation": {
                        "argv": list(invocation.argv),
                        "cwd": invocation.cwd,
                        "timeout_seconds": timeout_seconds,
                        "parser_mode": mapping.parser_mode,
                    },
                },
            )

        output, parser_error, parsed_json = self._parse_output(
            capture.stdout,
            parser_mode=mapping.parser_mode,
        )

        status = (
            "success"
            if (not capture.timed_out and capture.exit_code in mapping.success_exit_codes)
            else "failed"
        )

        result_type = self._resolve_result_type(
            output=output,
            default_outcome_type=mapping.default_outcome_type,
        )

        error: str | None = None
        if status == "failed":
            stderr_value = capture.stderr.strip()
            if stderr_value:
                error = stderr_value
            elif parser_error:
                error = parser_error
            else:
                error = f"CLI exit_code={capture.exit_code}"

        refs = [intent.id]
        trace_payload = {
            "profile_id": self.profile.profile_id,
            "action_type": action_type,
            "invocation": {
                "argv": list(invocation.argv),
                "cwd": invocation.cwd,
                "timeout_seconds": timeout_seconds,
                "parser_mode": mapping.parser_mode,
            },
            "capture": {
                "exit_code": capture.exit_code,
                "stdout": capture.stdout,
                "stderr": capture.stderr,
                "duration_ms": capture.duration_ms,
                "timed_out": capture.timed_out,
            },
            "parse": {
                "parsed_json": parsed_json,
                "parser_error": parser_error,
            },
            "mapping": {
                "action_type": mapping.action_type,
                "default_outcome_type": mapping.default_outcome_type,
                "success_exit_codes": list(mapping.success_exit_codes),
            },
        }

        return ExecutionResult(
            id=f"result-{uuid4().hex}",
            result_type=result_type,
            status=status,
            executor=self.executor_name,
            output=output,
            error=error,
            refs=refs,
            attributes={"cli_adapter": trace_payload},
        )

    @staticmethod
    def _resolve_action_type(intent: ExecutionIntent) -> str:
        operation_name = str(intent.operation.get("name", "")).strip()
        if operation_name:
            return operation_name
        return str(intent.intent_type).strip()

    def _build_env(self, *, invocation_env: dict[str, str]) -> dict[str, str] | None:
        if not self.profile.base_env and not invocation_env:
            return None
        merged = os.environ.copy()
        merged.update(self.profile.base_env)
        merged.update(invocation_env)
        return merged

    def _run_subprocess(
        self,
        invocation: CLIInvocation,
        *,
        timeout_seconds: float,
    ) -> _CLIExecutionCapture:
        env = self._build_env(invocation_env=invocation.env)
        started_at = time.monotonic()
        completed = subprocess.run(
            invocation.argv,
            input=invocation.stdin_text,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            cwd=invocation.cwd,
            env=env,
            check=False,
        )
        duration_ms = int((time.monotonic() - started_at) * 1000)
        return _CLIExecutionCapture(
            exit_code=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_ms=duration_ms,
            timed_out=False,
        )

    @staticmethod
    def _parse_output(stdout: str, *, parser_mode: ParserMode) -> tuple[dict[str, Any], str | None, bool]:
        if parser_mode == "text":
            return ({"text": stdout}, None, False)

        if not stdout.strip():
            return ({}, None, False)

        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return (
                {"text": stdout},
                f"JSON parse failed: {exc}",
                False,
            )

        if isinstance(parsed, dict):
            return (dict(parsed), None, True)
        return ({"value": parsed}, None, True)

    @staticmethod
    def _resolve_result_type(
        *,
        output: dict[str, Any],
        default_outcome_type: str,
    ) -> str:
        outcome_type = output.get("outcome_type")
        if isinstance(outcome_type, str) and outcome_type.strip():
            return outcome_type.strip()

        result_type = output.get("result_type")
        if isinstance(result_type, str) and result_type.strip():
            return result_type.strip()

        return default_outcome_type or "observation"

    def _failed_result(
        self,
        intent: ExecutionIntent,
        *,
        action_type: str,
        result_type: str,
        error: str,
        trace_payload: dict[str, Any],
    ) -> ExecutionResult:
        return ExecutionResult(
            id=f"result-{uuid4().hex}",
            result_type=result_type or "error",
            status="failed",
            executor=self.executor_name,
            output={},
            error=error,
            refs=[intent.id],
            attributes={
                "cli_adapter": {
                    "profile_id": self.profile.profile_id,
                    "action_type": action_type,
                    **dict(trace_payload),
                }
            },
        )
