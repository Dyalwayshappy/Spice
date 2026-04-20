from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable

from examples.decision_hub_demo.execution_adapter import (
    ExecutionOutcome,
    ExecutionRequest,
    MockExecutor,
)


CommandRunner = Callable[[list[str], str, int], subprocess.CompletedProcess[str]]


@dataclass(slots=True)
class HermesCodexExecutor:
    """Legacy/debug direct Hermes executor.

    Public demo and WhatsApp flows use the SDEP-backed executor. This direct
    wrapper is kept only for explicit debug overrides and older tests. It maps a
    Spice execution request into a Hermes prompt, captures the response, and
    normalizes it into the demo execution outcome schema. It does not update
    Spice state directly.
    """

    hermes_command: str = "hermes"
    timeout_seconds: int = 180
    runner: CommandRunner | None = None
    name: str = "hermes_codex"

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        prompt = build_hermes_codex_prompt(request)
        started = time.monotonic()
        try:
            completed = self._run(prompt)
        except FileNotFoundError as exc:
            return _failed_outcome(
                request,
                elapsed_seconds=time.monotonic() - started,
                reason=f"hermes command not found: {exc}",
                execution_ref_prefix="hermes.missing",
            )
        except subprocess.TimeoutExpired:
            return _failed_outcome(
                request,
                elapsed_seconds=time.monotonic() - started,
                reason="hermes execution timed out",
                execution_ref_prefix="hermes.timeout",
            )
        except subprocess.SubprocessError as exc:
            return _failed_outcome(
                request,
                elapsed_seconds=time.monotonic() - started,
                reason=f"hermes execution failed: {exc}",
                execution_ref_prefix="hermes.error",
            )

        elapsed_seconds = time.monotonic() - started
        raw_output = (completed.stdout or "").strip()
        raw_error = (completed.stderr or "").strip()
        if completed.returncode != 0:
            return _failed_outcome(
                request,
                elapsed_seconds=elapsed_seconds,
                reason=raw_error or raw_output or f"hermes exited with {completed.returncode}",
                execution_ref_prefix="hermes.failed",
                raw_output=raw_output,
            )

        return normalize_hermes_output(
            request,
            raw_output=raw_output,
            elapsed_seconds=elapsed_seconds,
            command=list(_command_args(self.hermes_command)),
        )

    def _run(self, prompt: str) -> subprocess.CompletedProcess[str]:
        command = [*_command_args(self.hermes_command), "chat", "-q", prompt]
        if self.runner is not None:
            return self.runner(command, prompt, self.timeout_seconds)
        return subprocess.run(
            command,
            input=None,
            capture_output=True,
            check=False,
            text=True,
            timeout=self.timeout_seconds,
        )


@dataclass(slots=True)
class FallbackExecutor:
    """Legacy/debug helper for the explicit direct-Hermes override mode."""

    primary: HermesCodexExecutor
    fallback: MockExecutor
    name: str = "hermes_or_mock"

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        outcome = self.primary.execute(request)
        if outcome.status == "failed" and outcome.blocking_issue in {
            "hermes_unavailable",
            "hermes_execution_failed",
        }:
            fallback = self.fallback.execute(request)
            fallback.metadata["fallback_from"] = outcome.to_payload()
            fallback.metadata["executor"] = self.name
            return fallback
        return outcome


def create_executor(mode: str = "auto") -> Any:
    """Create legacy/debug executors for explicit override modes.

    The public demo default is SDEP-backed and does not call this factory.
    """
    if mode == "mock":
        return MockExecutor()
    if mode == "hermes":
        return HermesCodexExecutor()
    if mode != "auto":
        raise ValueError("executor mode must be one of: auto, mock, hermes")
    if shutil.which("hermes"):
        return FallbackExecutor(primary=HermesCodexExecutor(), fallback=MockExecutor())
    return MockExecutor()


def build_hermes_codex_prompt(request: ExecutionRequest) -> str:
    payload = request.to_payload()
    return (
        "You are executing a delegated task from Spice through Hermes/Codex.\n"
        "Do the requested scoped work only. Return one JSON object and no prose.\n"
        "Required JSON fields: status, elapsed_minutes, risk_change, followup_needed, "
        "summary, blocking_issue.\n"
        "Allowed status values: success, failed, partial, abandoned.\n"
        "Allowed risk_change values: reduced, increased, unchanged, unknown.\n"
        "Execution request:\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )


def normalize_hermes_output(
    request: ExecutionRequest,
    *,
    raw_output: str,
    elapsed_seconds: float,
    command: list[str] | None = None,
) -> ExecutionOutcome:
    parsed = _extract_json(raw_output)
    elapsed_minutes = _non_negative_int(
        parsed.get("elapsed_minutes") if parsed else None,
        fallback=max(1, round(elapsed_seconds / 60)),
    )
    status = _allowed(
        parsed.get("status") if parsed else None,
        {"success", "failed", "partial", "abandoned"},
        fallback="partial",
    )
    risk_change = _allowed(
        parsed.get("risk_change") if parsed else None,
        {"reduced", "increased", "unchanged", "unknown"},
        fallback="unknown",
    )
    followup_needed = _bool(parsed.get("followup_needed") if parsed else None, fallback=True)
    summary = str(parsed.get("summary") if parsed else raw_output).strip()
    if not summary:
        summary = "Hermes/Codex returned no summary."
    blocking_issue = parsed.get("blocking_issue") if parsed else None
    if blocking_issue is not None:
        blocking_issue = str(blocking_issue)

    return ExecutionOutcome(
        status=status,
        elapsed_minutes=elapsed_minutes,
        risk_change=risk_change,
        followup_needed=followup_needed,
        summary=summary[:1000],
        execution_ref=_execution_ref("hermes", request, raw_output),
        blocking_issue=blocking_issue,
        metadata={
            "executor": "hermes_codex",
            "mode": "real",
            "command": command or ["hermes"],
            "raw_output": raw_output[:4000],
            "parsed_json": bool(parsed),
        },
    )


def _failed_outcome(
    request: ExecutionRequest,
    *,
    elapsed_seconds: float,
    reason: str,
    execution_ref_prefix: str,
    raw_output: str = "",
) -> ExecutionOutcome:
    return ExecutionOutcome(
        status="failed",
        elapsed_minutes=max(0, round(elapsed_seconds / 60)),
        risk_change="unknown",
        followup_needed=True,
        summary=reason[:1000],
        execution_ref=_execution_ref(execution_ref_prefix, request, raw_output or reason),
        blocking_issue="hermes_unavailable"
        if execution_ref_prefix == "hermes.missing"
        else "hermes_execution_failed",
        metadata={
            "executor": "hermes_codex",
            "mode": "real",
            "raw_output": raw_output[:4000],
        },
    )


def _command_args(command: str) -> tuple[str, ...]:
    return tuple(part for part in command.split(" ") if part)


def _execution_ref(prefix: str, request: ExecutionRequest, raw: str) -> str:
    digest = sha256(
        repr(
            {
                "execution_id": request.execution_id,
                "decision_id": request.decision_id,
                "raw": raw,
            }
        ).encode("utf-8")
    ).hexdigest()[:10]
    return f"{prefix}.{request.execution_id}.{digest}"


def _extract_json(raw: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _allowed(value: Any, allowed: set[str], *, fallback: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return fallback


def _non_negative_int(value: Any, *, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, parsed)


def _bool(value: Any, *, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback
