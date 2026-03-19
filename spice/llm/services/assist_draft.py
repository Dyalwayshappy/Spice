from __future__ import annotations

from dataclasses import dataclass

from spice.llm.core.client import LLMClient
from spice.llm.core.router import LLMModelConfigOverride
from spice.llm.core.task_hooks import LLMTaskHook
from spice.llm.core.types import LLMRequest


@dataclass(slots=True)
class AssistDraftService:
    client: LLMClient
    model_override: LLMModelConfigOverride | None = None

    def draft(
        self,
        *,
        domain_name: str,
        brief: str,
        attempt: int,
        feedback: str,
    ) -> str:
        prompt = _build_assist_prompt(
            domain_name=domain_name,
            brief=brief,
            attempt=attempt,
            feedback=feedback,
        )
        request = LLMRequest(
            task_hook=LLMTaskHook.ASSIST_DRAFT,
            domain=domain_name,
            input_text=prompt,
            system_text="You draft Spice DomainSpec proposals only.",
            response_format_hint="json_object",
            temperature=0.0,
            max_tokens=2500,
            timeout_sec=60.0,
            metadata={
                "domain_name": domain_name,
                "attempt": attempt,
            },
        )
        response = self.client.generate(
            request,
            model_override=self.model_override,
        )
        return response.output_text

    def resolved_provider_id(self, *, domain: str | None = None) -> str:
        config = self.client.resolve_model_config(
            LLMTaskHook.ASSIST_DRAFT,
            domain=domain,
            model_override=self.model_override,
        )
        return config.provider_id


def _build_assist_prompt(
    *,
    domain_name: str,
    brief: str,
    attempt: int,
    feedback: str,
) -> str:
    feedback_block = feedback.strip() or "none"
    return (
        "You draft Spice DomainSpec v1 payloads.\n"
        "Return JSON only. No markdown. No code fences. No prose.\n"
        "Return exactly one JSON object with keys:\n"
        "- draft_spec (object)\n"
        "- assumptions (array of strings)\n"
        "- warnings (array of strings)\n"
        "- missing_info (array of strings)\n"
        "- confidence (object)\n\n"
        "draft_spec must include:\n"
        "- schema_version\n"
        "- domain.id\n"
        "- vocabulary.observation_types\n"
        "- vocabulary.action_types\n"
        "- vocabulary.outcome_types\n"
        "- state.entity_id\n"
        "- state.fields\n"
        "- actions[] with executor and expected_outcome_type\n"
        "- decision.default_action\n"
        "- demo.observations[]\n\n"
        f"Domain name hint: {domain_name}\n"
        f"Attempt: {attempt}\n"
        f"Validation feedback from previous attempts: {feedback_block}\n\n"
        "User brief:\n"
        f"{brief}\n"
    )
