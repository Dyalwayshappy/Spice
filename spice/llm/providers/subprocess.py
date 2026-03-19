from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from uuid import uuid4

from spice.llm.core.provider import (
    LLMAuthError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponseError,
    LLMTransportError,
)
from spice.llm.core.types import LLMModelConfig, LLMRequest, LLMResponse

_MODEL_STDOUT_ATTR = "_spice_model_stdout"
_MODEL_STDERR_ATTR = "_spice_model_stderr"


@dataclass(slots=True)
class SubprocessLLMProvider(LLMProvider):
    provider_id: str = "subprocess"

    def generate(self, request: LLMRequest, model: LLMModelConfig) -> LLMResponse:
        command_raw = model.model_id.strip()
        if not command_raw:
            raise LLMResponseError("subprocess model_id command cannot be empty.")
        command = shlex.split(command_raw)
        if not command:
            raise LLMResponseError("subprocess model_id command cannot be parsed.")

        prompt = request.input_text
        if request.system_text.strip():
            prompt = request.system_text.strip() + "\n\n" + request.input_text

        timeout_sec = (
            model.timeout_sec
            if model.timeout_sec is not None
            else request.timeout_sec
        )

        start = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMTransportError(
                f"subprocess provider timed out after {timeout_sec}s: {command_raw}"
            ) from exc
        except OSError as exc:
            raise LLMTransportError(
                f"subprocess provider failed to execute command {command_raw!r}: {exc}"
            ) from exc

        latency_ms = int((time.perf_counter() - start) * 1000)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            error = _normalize_nonzero_error(
                return_code=completed.returncode,
                stderr=stderr,
            )
            _attach_model_io(error, stdout=stdout, stderr=stderr)
            raise error
        if not stdout.strip():
            error = LLMResponseError("subprocess provider returned empty stdout.")
            _attach_model_io(error, stdout=stdout, stderr=stderr)
            raise error

        return LLMResponse(
            provider_id=self.provider_id,
            model_id=model.model_id,
            output_text=stdout,
            raw_payload={
                "command": command,
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
            finish_reason="stop",
            usage={
                "input_chars": len(prompt),
                "output_chars": len(stdout),
            },
            latency_ms=latency_ms,
            request_id=f"sub-{uuid4().hex}",
        )


def _normalize_nonzero_error(*, return_code: int, stderr: str) -> Exception:
    normalized = stderr.strip().lower()
    message = (
        "subprocess provider command failed "
        f"(exit={return_code}): {stderr.strip() or '<no stderr>'}"
    )
    if _contains_any(normalized, ("unauthorized", "forbidden", "api key", "authentication")):
        return LLMAuthError(message)
    if _contains_any(normalized, ("rate limit", "too many requests", "429", "throttle")):
        return LLMRateLimitError(message)
    return LLMTransportError(message)


def _contains_any(value: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern in value:
            return True
    return False


def _attach_model_io(exc: Exception, *, stdout: str, stderr: str) -> None:
    try:
        setattr(exc, _MODEL_STDOUT_ATTR, stdout if isinstance(stdout, str) else "")
        setattr(exc, _MODEL_STDERR_ATTR, stderr if isinstance(stderr, str) else "")
    except Exception:
        return
