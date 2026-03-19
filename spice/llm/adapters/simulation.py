from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from spice.llm.core import LLMClient, LLMModelConfigOverride, LLMRequest, LLMTaskHook
from spice.llm.simulation import SimulationModel
from spice.llm.util import extract_first_json_object, strip_markdown_fences
from spice.protocols import Decision, ExecutionIntent, WorldState

_MODEL_STDOUT_ATTR = "_spice_model_stdout"
_MODEL_STDERR_ATTR = "_spice_model_stderr"


@dataclass(slots=True)
class LLMSimulationAdapter(SimulationModel):
    client: LLMClient
    model_override: LLMModelConfigOverride | None = None
    _last_model_stdout: str = field(default="", init=False, repr=False)
    _last_model_stderr: str = field(default="", init=False, repr=False)
    _last_timeout_seconds: float | None = field(default=None, init=False, repr=False)

    def simulate(
        self,
        state: WorldState,
        *,
        decision: Decision | None = None,
        intent: ExecutionIntent | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._last_model_stdout = ""
        self._last_model_stderr = ""
        self._last_timeout_seconds = None
        request = LLMRequest(
            task_hook=LLMTaskHook.SIMULATION_ADVISE,
            domain=_domain_from_context(context),
            input_text=_build_prompt(
                state=state,
                decision=decision,
                intent=intent,
                context=context,
            ),
            response_format_hint="json_object",
            metadata={"state_id": state.id},
        )
        self._last_timeout_seconds = _resolve_timeout_seconds(
            client=self.client,
            request=request,
            model_override=self.model_override,
        )
        response = self.client.generate(request, model_override=self.model_override)
        self._last_model_stdout, self._last_model_stderr = _extract_model_io_from_response(response)
        try:
            payload = _parse_json_object(response.output_text)
            return payload
        except Exception as exc:
            _attach_model_io(
                exc,
                stdout=self._last_model_stdout,
                stderr=self._last_model_stderr,
            )
            raise


def _build_prompt(
    *,
    state: WorldState,
    decision: Decision | None,
    intent: ExecutionIntent | None,
    context: dict[str, Any] | None,
) -> str:
    payload = {
        "state": {
            "id": state.id,
            "status": state.status,
            "resources": state.resources,
            "signals": state.signals,
            "risks": state.risks,
        },
        "decision": _decision_payload(decision),
        "intent": _intent_payload(intent),
        "context": context or {},
    }
    return (
        "You are a SPICE simulation advisor.\n"
        "Task: using the JSON input below, provide simulation advice for candidate evaluation before execution.\n"
        "JSON object only.\n"
        "Required top-level fields: suggestion_text (string), score (number), confidence (number), urgency (string).\n"
        "Normalize score to [0.0, 1.0].\n"
        "suggestion_text must be concrete, concise (1-2 sentences), and aligned with decision.selected_action.\n"
        "Forbidden in suggestion_text: response/system/model/prompt/instruction/policy/process commentary.\n"
        "Forbidden in suggestion_text: generic template advice with no concrete action.\n"
        "Domain-specific contracts may be provided in context and should be followed when present.\n"
        "No markdown.\n"
        "No prose outside the JSON object.\n"
        "Non-JSON output is invalid.\n"
        "Missing required fields means the response is invalid.\n"
        + json.dumps(payload, ensure_ascii=True, sort_keys=True)
    )


def _decision_payload(decision: Decision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "id": decision.id,
        "decision_type": decision.decision_type,
        "status": decision.status,
        "selected_action": decision.selected_action,
        "refs": decision.refs,
        "metadata": decision.metadata,
        "attributes": decision.attributes,
    }


def _intent_payload(intent: ExecutionIntent | None) -> dict[str, Any] | None:
    if intent is None:
        return None
    return {
        "id": intent.id,
        "intent_type": intent.intent_type,
        "status": intent.status,
        "executor_type": intent.executor_type,
        "target": intent.target,
        "operation": intent.operation,
        "input_payload": intent.input_payload,
        "parameters": intent.parameters,
        "provenance": intent.provenance,
        "refs": intent.refs,
    }


def _domain_from_context(context: dict[str, Any] | None) -> str | None:
    if context is None:
        return None
    value = context.get("domain")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_json_object(text: str) -> dict[str, Any]:
    normalized = strip_markdown_fences(text)
    candidate = extract_first_json_object(normalized)
    if candidate is None:
        raise ValueError("No JSON object found in response.")
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("Simulation adapter expected JSON object response.")
    return payload


def _extract_model_io_from_response(response: Any) -> tuple[str, str]:
    raw_payload = response.raw_payload if isinstance(getattr(response, "raw_payload", None), dict) else {}
    stdout = raw_payload.get("stdout")
    stderr = raw_payload.get("stderr")
    normalized_stdout = stdout if isinstance(stdout, str) else response.output_text
    normalized_stderr = stderr if isinstance(stderr, str) else ""
    return normalized_stdout, normalized_stderr


def _attach_model_io(exc: Exception, *, stdout: str, stderr: str) -> None:
    existing_stdout = getattr(exc, _MODEL_STDOUT_ATTR, "")
    existing_stderr = getattr(exc, _MODEL_STDERR_ATTR, "")
    try:
        if not isinstance(existing_stdout, str) or not existing_stdout:
            setattr(exc, _MODEL_STDOUT_ATTR, stdout if isinstance(stdout, str) else "")
        if not isinstance(existing_stderr, str) or not existing_stderr:
            setattr(exc, _MODEL_STDERR_ATTR, stderr if isinstance(stderr, str) else "")
    except Exception:
        return


def _resolve_timeout_seconds(
    *,
    client: LLMClient,
    request: LLMRequest,
    model_override: LLMModelConfigOverride | None,
) -> float | None:
    try:
        model_config = client.resolve_model_config(
            request.task_hook,
            domain=request.domain,
            model_override=model_override,
        )
    except Exception:
        return None

    timeout = getattr(model_config, "timeout_sec", None)
    if isinstance(timeout, (int, float)):
        return float(timeout)
    return None
