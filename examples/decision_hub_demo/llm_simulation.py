from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

from spice.llm.core import (
    LLMClient,
    LLMModelConfig,
    LLMModelConfigOverride,
    LLMRequest,
    LLMResponse,
    LLMRouter,
    LLMTaskHook,
    ProviderRegistry,
)
from spice.llm.providers import (
    DeterministicLLMProvider,
    OpenRouterLLMProvider,
    SubprocessLLMProvider,
)
from spice.llm.services.model_override import resolve_llm_model_override
from spice.llm.simulation import SimulationModel
from spice.llm.util import extract_first_json_object, strip_markdown_fences
from spice.protocols import Decision, ExecutionIntent, WorldState

from examples.decision_hub_demo.simulation import StructuredSimulationRunner


SIMULATION_ENABLED_ENV = "SPICE_DECISION_HUB_SIMULATION_ENABLED"
SIMULATION_MODEL_ENV = "SPICE_DECISION_HUB_SIMULATION_MODEL"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
DEFAULT_SIMULATION_MODEL = "deterministic.decision_hub_simulation.stub.v1"
DEFAULT_MAX_TOKENS = 900
DEFAULT_TIMEOUT_SEC = 20.0


@dataclass(slots=True)
class DecisionHubLLMSimulationModel(SimulationModel):
    """Demo-specific LLM adapter for structured consequence estimation only."""

    client: LLMClient
    model_override: LLMModelConfigOverride | None
    model_name: str

    def simulate(
        self,
        state: WorldState | None,
        *,
        decision: Decision | None = None,
        intent: ExecutionIntent | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del state, intent
        if decision is None:
            raise ValueError("decision seed is required for consequence estimation")
        if not isinstance(context, dict):
            raise ValueError("simulation context must be a dict")
        active_context = context.get("active_decision_context")
        candidate = context.get("candidate")
        if not isinstance(active_context, dict):
            raise ValueError("active_decision_context is required")
        if not isinstance(candidate, dict):
            raise ValueError("candidate is required")

        candidate_id = str(candidate.get("candidate_id") or "")
        action_type = str(candidate.get("action_type") or decision.selected_action)
        request = LLMRequest(
            task_hook=LLMTaskHook.SIMULATION_ADVISE,
            domain="decision_hub_demo",
            system_text=_system_prompt(),
            input_text=_input_prompt(
                decision=decision,
                active_context=active_context,
                candidate=candidate,
            ),
            response_format_hint="json_object",
            temperature=0.0,
            max_tokens=DEFAULT_MAX_TOKENS,
            timeout_sec=DEFAULT_TIMEOUT_SEC,
            metadata={
                "candidate_id": candidate_id,
                "action_type": action_type,
                "llm_role": "consequence_estimation_only",
                "final_recommendation_allowed": False,
            },
        )
        response = self.client.generate(request, model_override=self.model_override)
        payload = _parse_json_object(response.output_text)
        _attach_llm_metadata(
            payload,
            response=response,
            model_name=self.model_name,
        )
        return payload


def build_simulation_runner_from_env(
    env: Mapping[str, str] | None = None,
) -> StructuredSimulationRunner:
    """Build the demo simulation runner from env, falling back when disabled."""

    if not _truthy(_env_value(env, SIMULATION_ENABLED_ENV)):
        return StructuredSimulationRunner()

    raw_model = _env_value(env, SIMULATION_MODEL_ENV)
    if not raw_model:
        return StructuredSimulationRunner()

    model_override = resolve_llm_model_override(
        raw_model,
        deterministic_model_id=DEFAULT_SIMULATION_MODEL,
    )
    if model_override is None:
        return StructuredSimulationRunner()
    if (
        model_override.provider_id == "openrouter"
        and not _env_value(env, OPENROUTER_API_KEY_ENV)
    ):
        return StructuredSimulationRunner()

    model = DecisionHubLLMSimulationModel(
        client=_build_llm_client(),
        model_override=model_override,
        model_name=raw_model,
    )
    return StructuredSimulationRunner(model)


def _build_llm_client() -> LLMClient:
    registry = (
        ProviderRegistry.empty()
        .register(DeterministicLLMProvider())
        .register(OpenRouterLLMProvider())
        .register(SubprocessLLMProvider())
    )
    router = LLMRouter(
        global_default=LLMModelConfig(
            provider_id="deterministic",
            model_id=DEFAULT_SIMULATION_MODEL,
            temperature=0.0,
            max_tokens=DEFAULT_MAX_TOKENS,
            timeout_sec=DEFAULT_TIMEOUT_SEC,
            response_format_hint="json_object",
        )
    )
    return LLMClient(registry=registry, router=router)


def _system_prompt() -> str:
    return """You are the Spice decision_hub_demo consequence estimator.

You estimate consequences for exactly one provided candidate action.

Allowed role:
- estimate structured consequences
- express uncertainty and assumptions
- return valid JSON only

Forbidden role:
- do not recommend an action
- do not choose selected_action
- do not name a best_option
- do not create new candidate actions
- do not compare candidates
- do not mutate state
- do not decide confirmation

Return only one JSON object matching this schema:
{
  "candidate_id": "string",
  "action_type": "string",
  "expected_time_cost_minutes": 0,
  "commitment_risk": "low | medium | high",
  "work_item_risk_change": "reduced | unchanged | increased",
  "reversibility": "low | medium | high",
  "attention_cost": "none | low | medium | high",
  "followup_needed": true,
  "followup_summary": "string",
  "executor_load": "none | low | medium | high",
  "requires_confirmation": true,
  "confidence": 0.0,
  "assumptions": ["string"],
  "metadata": {}
}

Never include these fields anywhere in the JSON:
recommendation, selected_action, best_option, new_candidate, candidate_actions.
"""


def _input_prompt(
    *,
    decision: Decision,
    active_context: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    payload = {
        "task": "estimate_one_candidate_consequence",
        "decision_seed": {
            "id": decision.id,
            "decision_type": decision.decision_type,
            "selected_action": decision.selected_action,
        },
        "candidate": candidate,
        "active_decision_context": active_context,
        "output_constraints": {
            "json_only": True,
            "one_candidate_only": True,
            "final_recommendation_allowed": False,
            "new_candidate_actions_allowed": False,
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _parse_json_object(raw: str) -> dict[str, Any]:
    normalized = strip_markdown_fences(raw or "")
    extracted = extract_first_json_object(normalized)
    if not extracted:
        raise ValueError("LLM output did not contain a JSON object")
    try:
        payload = json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM output JSON could not be parsed") from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM output JSON must be an object")
    return payload


def _attach_llm_metadata(
    payload: dict[str, Any],
    *,
    response: LLMResponse,
    model_name: str,
) -> None:
    target = payload.get("consequence", payload)
    if not isinstance(target, dict):
        return
    metadata = target.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.update(
        {
            "simulation_source": "llm",
            "simulation_model": response.model_id or model_name,
            "simulation_provider": response.provider_id,
            "llm_request_id": response.request_id,
            "llm_recommendation_allowed": False,
        }
    )
    target["metadata"] = metadata


def _env_value(env: Mapping[str, str] | None, name: str) -> str:
    if env is None:
        return os.environ.get(name, "").strip()
    return str(env.get(name, "")).strip()


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
