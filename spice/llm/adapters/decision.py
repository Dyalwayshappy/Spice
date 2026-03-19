from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from spice.llm.core import LLMClient, LLMModelConfigOverride, LLMRequest, LLMTaskHook
from spice.llm.decision import DecisionModel
from spice.llm.util import (
    extract_first_json_array,
    extract_first_json_object,
    strip_markdown_fences,
)
from spice.protocols import Decision, WorldState

_MODEL_STDOUT_ATTR = "_spice_model_stdout"
_MODEL_STDERR_ATTR = "_spice_model_stderr"


@dataclass(slots=True)
class LLMDecisionAdapter(DecisionModel):
    client: LLMClient
    model_override: LLMModelConfigOverride | None = None
    _last_model_stdout: str = field(default="", init=False, repr=False)
    _last_model_stderr: str = field(default="", init=False, repr=False)
    _last_field_fallback_used: bool = field(default=False, init=False, repr=False)
    _last_field_fallback_events: list[dict[str, Any]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def propose(
        self,
        state: WorldState,
        *,
        context: dict[str, Any] | None = None,
        max_candidates: int | None = None,
    ) -> list[Decision]:
        self._last_model_stdout = ""
        self._last_model_stderr = ""
        self._last_field_fallback_used = False
        self._last_field_fallback_events = []
        request = LLMRequest(
            task_hook=LLMTaskHook.DECISION_PROPOSE,
            domain=_domain_from_context(context),
            input_text=_build_prompt(state, context=context, max_candidates=max_candidates),
            response_format_hint="json_array",
            metadata={"state_id": state.id},
        )
        response = self.client.generate(request, model_override=self.model_override)
        self._last_model_stdout, self._last_model_stderr = _extract_model_io_from_response(response)

        try:
            payload = _parse_json_payload(response.output_text)

            raw_candidates: list[Any]
            if isinstance(payload, list):
                raw_candidates = payload
            elif isinstance(payload, dict):
                inner = payload.get("candidates", [])
                if not isinstance(inner, list):
                    raise ValueError("Decision adapter expected list in `candidates`.")
                raw_candidates = inner
            else:
                raise ValueError("Decision adapter expected JSON list or object payload.")

            proposals: list[Decision] = []
            for item in raw_candidates:
                if not isinstance(item, dict):
                    continue
                decision, compat = _decision_from_payload(item, state)
                self._last_field_fallback_events.append(compat)
                if bool(compat.get("field_fallback_used")):
                    self._last_field_fallback_used = True
                proposals.append(decision)
                if max_candidates is not None and max_candidates > 0 and len(proposals) >= max_candidates:
                    break
            return proposals
        except Exception as exc:
            _attach_model_io(
                exc,
                stdout=self._last_model_stdout,
                stderr=self._last_model_stderr,
            )
            raise


def _build_prompt(
    state: WorldState,
    *,
    context: dict[str, Any] | None,
    max_candidates: int | None,
) -> str:
    allowed_actions = _allowed_actions_from_context(context)
    payload = {
        "state": {
            "id": state.id,
            "status": state.status,
            "resources": state.resources,
            "signals": state.signals,
            "active_intents": state.active_intents,
            "recent_outcomes": state.recent_outcomes,
            "domain_state": state.domain_state,
        },
        "context": context or {},
        "allowed_actions": allowed_actions,
        "max_candidates": max_candidates,
    }
    allowed_actions_line = (
        "selected_action must be one of payload.allowed_actions.\n"
        if allowed_actions
        else "selected_action must follow payload.allowed_actions when provided.\n"
    )
    return (
        "Return JSON for Spice Decision proposals.\n"
        "Use either a JSON array of decisions or {\"candidates\": [...]}.\n"
        "JSON only.\n"
        "Each candidate must include selected_action, decision_type, and status.\n"
        + allowed_actions_line
        + "Do not use action or type as primary fields.\n"
        + json.dumps(payload, ensure_ascii=True, sort_keys=True)
    )


def _decision_from_payload(payload: dict[str, Any], state: WorldState) -> tuple[Decision, dict[str, Any]]:
    decision_id = _as_non_empty_string(payload.get("id")) or f"dec-{uuid4().hex}"
    decision_type_value = _as_non_empty_string(payload.get("decision_type"))
    fallback_type_value = _as_non_empty_string(payload.get("type"))
    decision_type_fallback_used = False
    if not decision_type_value and fallback_type_value:
        decision_type_value = fallback_type_value
        decision_type_fallback_used = True
    decision_type = decision_type_value or "generic"

    status = _as_non_empty_string(payload.get("status")) or "proposed"
    selected_action_raw = payload.get("selected_action")
    fallback_action_raw = payload.get("action")
    selected_action_value = _as_non_empty_string(selected_action_raw)
    selected_action_fallback_used = False
    if not selected_action_value:
        fallback_action_value = _as_non_empty_string(fallback_action_raw)
        if fallback_action_value:
            selected_action_value = fallback_action_value
            selected_action_fallback_used = True
    selected_action = (
        selected_action_value
        if selected_action_value
        else None
    )
    refs_raw = payload.get("refs")
    refs = [item for item in refs_raw if isinstance(item, str)] if isinstance(refs_raw, list) else []
    if state.id not in refs:
        refs.append(state.id)
    metadata = payload.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    attributes = payload.get("attributes")
    attributes = dict(attributes) if isinstance(attributes, dict) else {}
    decision = Decision(
        id=decision_id,
        decision_type=decision_type,
        status=status,
        selected_action=selected_action,
        refs=refs,
        metadata=metadata,
        attributes=attributes,
    )
    compat = {
        "field_fallback_used": (selected_action_fallback_used or decision_type_fallback_used),
        "selected_action_fallback_used": selected_action_fallback_used,
        "decision_type_fallback_used": decision_type_fallback_used,
        "original_selected_action": _as_non_empty_string(selected_action_raw),
        "fallback_action": _as_non_empty_string(fallback_action_raw),
        "resolved_selected_action": selected_action or "",
        "original_decision_type": _as_non_empty_string(payload.get("decision_type")),
        "fallback_type": fallback_type_value,
        "resolved_decision_type": decision_type,
    }
    return decision, compat


def _domain_from_context(context: dict[str, Any] | None) -> str | None:
    if context is None:
        return None
    value = context.get("domain")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_json_payload(text: str) -> Any:
    normalized = strip_markdown_fences(text)
    first_obj = normalized.find("{")
    first_arr = normalized.find("[")

    if first_arr >= 0 and (first_obj < 0 or first_arr < first_obj):
        arr_candidate = extract_first_json_array(normalized)
        if arr_candidate is not None:
            return json.loads(arr_candidate)

    obj_candidate = extract_first_json_object(normalized)
    if obj_candidate is not None:
        return json.loads(obj_candidate)

    arr_candidate = extract_first_json_array(normalized)
    if arr_candidate is not None:
        return json.loads(arr_candidate)
    raise ValueError("No JSON payload found in response.")


def _as_non_empty_string(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _allowed_actions_from_context(context: dict[str, Any] | None) -> list[str]:
    if not isinstance(context, dict):
        return []
    raw = context.get("allowed_actions")
    if not isinstance(raw, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        token = _as_non_empty_string(item)
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


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
