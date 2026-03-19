from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from spice.llm.core import LLMClient, LLMModelConfigOverride, LLMRequest, LLMTaskHook
from spice.llm.perception import PerceptionModel
from spice.llm.util import extract_first_json_object, strip_markdown_fences
from spice.protocols import Observation


@dataclass(slots=True)
class LLMPerceptionAdapter(PerceptionModel):
    client: LLMClient
    model_override: LLMModelConfigOverride | None = None

    def interpret(
        self,
        raw_input: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> Observation:
        request = LLMRequest(
            task_hook=LLMTaskHook.PERCEPTION_INTERPRET,
            domain=_domain_from_context(context),
            input_text=_build_prompt(raw_input, context),
            response_format_hint="json_object",
            metadata={"raw_input": dict(raw_input)},
        )
        response = self.client.generate(request, model_override=self.model_override)
        payload = _parse_json_object(response.output_text)

        observation_id = _as_non_empty_string(payload.get("id")) or _as_non_empty_string(
            raw_input.get("id")
        )
        if not observation_id:
            observation_id = f"obs-{uuid4().hex}"

        observation_type = _as_non_empty_string(payload.get("observation_type")) or _as_non_empty_string(
            raw_input.get("observation_type")
        )
        if not observation_type:
            observation_type = "generic"

        source_raw = payload.get("source", raw_input.get("source"))
        source = source_raw if isinstance(source_raw, str) and source_raw.strip() else None

        attributes = payload.get("attributes")
        if not isinstance(attributes, dict):
            attributes = raw_input.get("attributes")
        attributes = dict(attributes) if isinstance(attributes, dict) else {}

        metadata = payload.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        if context is not None:
            metadata.setdefault("context", dict(context))
        return Observation(
            id=observation_id,
            observation_type=observation_type,
            source=source,
            attributes=attributes,
            metadata=metadata,
        )


def _build_prompt(raw_input: dict[str, Any], context: dict[str, Any] | None) -> str:
    payload = {"raw_input": raw_input, "context": context or {}}
    return (
        "Return a JSON object for a Spice Observation proposal.\n"
        "Keys: id, observation_type, source, attributes, metadata.\n"
        "JSON only.\n"
        + json.dumps(payload, ensure_ascii=True, sort_keys=True)
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
        raise ValueError("Perception adapter expected JSON object response.")
    return payload


def _as_non_empty_string(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""
