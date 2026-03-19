from __future__ import annotations

from dataclasses import replace

from spice.llm.core.registry import ProviderRegistry
from spice.llm.core.router import LLMModelConfigOverride, LLMRouter
from spice.llm.core.task_hooks import LLMTaskHook
from spice.llm.core.types import LLMModelConfig, LLMRequest, LLMResponse


class LLMClient:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        router: LLMRouter,
    ) -> None:
        self._registry = registry
        self._router = router

    def resolve_model_config(
        self,
        task_hook: LLMTaskHook,
        *,
        domain: str | None = None,
        model_override: LLMModelConfigOverride | None = None,
    ) -> LLMModelConfig:
        return self._router.resolve(
            task_hook,
            domain=domain,
            model_override=model_override,
        )

    def generate(
        self,
        request: LLMRequest,
        *,
        model_override: LLMModelConfigOverride | None = None,
    ) -> LLMResponse:
        base_model = self.resolve_model_config(
            request.task_hook,
            domain=request.domain,
            model_override=model_override,
        )
        dispatch_model = self.resolve_dispatch_config(
            request=request,
            base_model=base_model,
        )
        provider = self._registry.resolve(dispatch_model.provider_id)
        return provider.generate(request, dispatch_model)

    def resolve_dispatch_config(
        self,
        *,
        request: LLMRequest,
        base_model: LLMModelConfig,
    ) -> LLMModelConfig:
        updates: dict[str, object] = {}
        if request.temperature is not None:
            updates["temperature"] = request.temperature
        if request.max_tokens is not None:
            updates["max_tokens"] = request.max_tokens
        if request.timeout_sec is not None:
            updates["timeout_sec"] = request.timeout_sec
        if request.response_format_hint is not None:
            updates["response_format_hint"] = request.response_format_hint
        if not updates:
            return base_model
        return replace(base_model, **updates)
