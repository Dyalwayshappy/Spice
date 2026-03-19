from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from spice.llm.core import LLMClient, LLMModelConfigOverride, LLMRequest, LLMTaskHook
from spice.llm.reflection import ReflectionModel
from spice.llm.util import extract_first_json_object, strip_markdown_fences
from spice.protocols import ExecutionResult, Outcome, Reflection, WorldState


@dataclass(slots=True)
class LLMReflectionAdapter(ReflectionModel):
    client: LLMClient
    model_override: LLMModelConfigOverride | None = None

    def synthesize(
        self,
        state: WorldState,
        outcome: Outcome,
        *,
        execution_result: ExecutionResult | None = None,
        context: dict[str, Any] | None = None,
    ) -> Reflection:
        request = LLMRequest(
            task_hook=LLMTaskHook.REFLECTION_SYNTHESIZE,
            domain=_domain_from_context(context),
            input_text=_build_prompt(
                state=state,
                outcome=outcome,
                execution_result=execution_result,
                context=context,
            ),
            response_format_hint="json_object",
            metadata={"state_id": state.id, "outcome_id": outcome.id},
        )
        response = self.client.generate(request, model_override=self.model_override)
        payload = _parse_json_object(response.output_text)
        return _reflection_from_payload(payload, outcome)


def _build_prompt(
    *,
    state: WorldState,
    outcome: Outcome,
    execution_result: ExecutionResult | None,
    context: dict[str, Any] | None,
) -> str:
    payload = {
        "state": {
            "id": state.id,
            "status": state.status,
            "resources": state.resources,
            "signals": state.signals,
            "recent_outcomes": state.recent_outcomes,
        },
        "outcome": {
            "id": outcome.id,
            "outcome_type": outcome.outcome_type,
            "status": outcome.status,
            "changes": outcome.changes,
            "refs": outcome.refs,
            "attributes": outcome.attributes,
        },
        "execution_result": _execution_result_payload(execution_result),
        "context": context or {},
    }
    return (
        "Return a JSON object for a Spice Reflection proposal.\n"
        "Keys: id, reflection_type, status, refs, insights, attributes.\n"
        "JSON only.\n"
        + json.dumps(payload, ensure_ascii=True, sort_keys=True)
    )


def _execution_result_payload(result: ExecutionResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "id": result.id,
        "status": result.status,
        "executor": result.executor,
        "output": result.output,
        "error": result.error,
        "attributes": result.attributes,
        "refs": result.refs,
    }


def _reflection_from_payload(payload: dict[str, Any], outcome: Outcome) -> Reflection:
    reflection_id = _as_non_empty_string(payload.get("id")) or f"ref-{uuid4().hex}"
    reflection_type = _as_non_empty_string(payload.get("reflection_type")) or "post_execution"
    status = _as_non_empty_string(payload.get("status")) or "recorded"
    refs_raw = payload.get("refs")
    refs = [item for item in refs_raw if isinstance(item, str)] if isinstance(refs_raw, list) else []
    if outcome.id not in refs:
        refs.append(outcome.id)
    insights = payload.get("insights")
    insights = dict(insights) if isinstance(insights, dict) else {}
    attributes = payload.get("attributes")
    attributes = dict(attributes) if isinstance(attributes, dict) else {}
    return Reflection(
        id=reflection_id,
        reflection_type=reflection_type,
        status=status,
        refs=refs,
        insights=insights,
        attributes=attributes,
    )


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
        raise ValueError("Reflection adapter expected JSON object response.")
    return payload


def _as_non_empty_string(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""
