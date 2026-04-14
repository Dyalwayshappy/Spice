from __future__ import annotations

from spice.llm.core import LLMModelConfigOverride


OPENROUTER_MODEL_PREFIX = "openrouter:"


def resolve_llm_model_override(
    raw: str | None,
    *,
    deterministic_model_id: str,
) -> LLMModelConfigOverride | None:
    if raw is None:
        return None
    token = raw.strip()
    if not token:
        return None
    if token.lower() == "deterministic":
        return LLMModelConfigOverride(
            provider_id="deterministic",
            model_id=deterministic_model_id,
        )
    if token.lower().startswith(OPENROUTER_MODEL_PREFIX):
        model_id = token[len(OPENROUTER_MODEL_PREFIX) :].strip()
        return LLMModelConfigOverride(
            provider_id="openrouter",
            model_id=model_id,
        )
    return LLMModelConfigOverride(
        provider_id="subprocess",
        model_id=token,
    )
