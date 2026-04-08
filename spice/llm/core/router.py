from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from spice.llm.core.task_hooks import LLMTaskHook
from spice.llm.core.types import LLMModelConfig


class LLMRouteNotFoundError(KeyError):
    """Raised when router cannot resolve a model configuration for a task hook."""


@dataclass(slots=True, frozen=True)
class LLMModelConfigOverride:
    provider_id: str | None = None
    model_id: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_sec: float | None = None
    response_format_hint: str | None = None


@dataclass(slots=True, frozen=True)
class LLMRouter:
    global_default: LLMModelConfig | None = None
    hook_defaults: Mapping[LLMTaskHook, LLMModelConfig] = field(default_factory=dict)
    domain_routes: Mapping[tuple[LLMTaskHook, str], LLMModelConfig] = field(default_factory=dict)

    def resolve(
        self,
        task_hook: LLMTaskHook,
        *,
        domain: str | None = None,
        model_override: LLMModelConfigOverride | None = None,
    ) -> LLMModelConfig:
        normalized_domain = _normalize_domain(domain)
        base = None
        if normalized_domain:
            base = self.domain_routes.get((task_hook, normalized_domain))
        if base is None:
            base = self.hook_defaults.get(task_hook)
        if base is None:
            base = self.global_default
        if base is None:
            raise LLMRouteNotFoundError(
                f"No LLM model config route for hook={task_hook.value!r} domain={normalized_domain!r}."
            )
        if model_override is None:
            return base
        return _apply_override(base, model_override)


def _apply_override(
    base: LLMModelConfig,
    override: LLMModelConfigOverride,
) -> LLMModelConfig:
    payload = {}
    if override.provider_id is not None:
        payload["provider_id"] = override.provider_id
    if override.model_id is not None:
        payload["model_id"] = override.model_id
    if override.base_url is not None:
        payload["base_url"] = override.base_url
    if override.api_key is not None:
        payload["api_key"] = override.api_key
    if override.temperature is not None:
        payload["temperature"] = override.temperature
    if override.max_tokens is not None:
        payload["max_tokens"] = override.max_tokens
    if override.timeout_sec is not None:
        payload["timeout_sec"] = override.timeout_sec
    if override.response_format_hint is not None:
        payload["response_format_hint"] = override.response_format_hint
    if not payload:
        return base
    return replace(base, **payload)


def _normalize_domain(domain: str | None) -> str:
    if domain is None:
        return ""
    return domain.strip().lower()
