from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

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
from spice.llm.core.provider import LLMProvider


@dataclass(slots=True)
class _CaptureProvider(LLMProvider):
    provider_id: str = "capture"
    last_model: LLMModelConfig | None = None
    last_request: LLMRequest | None = None

    def generate(self, request: LLMRequest, model: LLMModelConfig) -> LLMResponse:
        self.last_request = request
        self.last_model = model
        return LLMResponse(
            provider_id=self.provider_id,
            model_id=model.model_id,
            output_text="{}",
            raw_payload={},
            finish_reason="stop",
            usage={},
            latency_ms=0,
            request_id="capture-1",
        )


class LLMClientParamPrecedenceTests(unittest.TestCase):
    def test_request_overrides_router_model_for_dispatch(self) -> None:
        provider = _CaptureProvider()
        router_model = LLMModelConfig(
            provider_id="capture",
            model_id="router-model",
            temperature=0.2,
            max_tokens=128,
            timeout_sec=15.0,
            response_format_hint="json_object",
        )
        client = _build_client(provider=provider, model=router_model)
        request = LLMRequest(
            task_hook=LLMTaskHook.ASSIST_DRAFT,
            input_text="prompt",
            temperature=0.7,
            max_tokens=512,
            timeout_sec=3.0,
            response_format_hint="json_array",
        )

        client.generate(request)
        self.assertIsNotNone(provider.last_model)
        assert provider.last_model is not None
        self.assertEqual(provider.last_model.temperature, 0.7)
        self.assertEqual(provider.last_model.max_tokens, 512)
        self.assertEqual(provider.last_model.timeout_sec, 3.0)
        self.assertEqual(provider.last_model.response_format_hint, "json_array")
        self.assertEqual(provider.last_model.provider_id, "capture")
        self.assertEqual(provider.last_model.model_id, "router-model")

    def test_none_request_values_do_not_override_router_model(self) -> None:
        provider = _CaptureProvider()
        router_model = LLMModelConfig(
            provider_id="capture",
            model_id="router-model",
            temperature=0.4,
            max_tokens=256,
            timeout_sec=20.0,
            response_format_hint="json_object",
        )
        client = _build_client(provider=provider, model=router_model)
        request = LLMRequest(
            task_hook=LLMTaskHook.ASSIST_DRAFT,
            input_text="prompt",
        )

        client.generate(request)
        self.assertIsNotNone(provider.last_model)
        assert provider.last_model is not None
        self.assertEqual(provider.last_model.temperature, 0.4)
        self.assertEqual(provider.last_model.max_tokens, 256)
        self.assertEqual(provider.last_model.timeout_sec, 20.0)
        self.assertEqual(provider.last_model.response_format_hint, "json_object")

    def test_override_carries_relay_fields(self) -> None:
        provider = _CaptureProvider()
        router_model = LLMModelConfig(
            provider_id="capture",
            model_id="router-model",
            base_url="https://router.example.com",
            api_key="router-key",
            temperature=0.4,
            max_tokens=256,
            timeout_sec=20.0,
            response_format_hint="json_object",
        )
        client = _build_client(provider=provider, model=router_model)
        override = LLMModelConfigOverride(
            provider_id="capture",
            model_id="router-model",
            base_url="https://relay.internal",
            api_key="relay-secret",
        )
        request = LLMRequest(
            task_hook=LLMTaskHook.ASSIST_DRAFT,
            input_text="prompt",
        )

        client.generate(request, model_override=override)
        self.assertIsNotNone(provider.last_model)
        assert provider.last_model is not None
        self.assertEqual(provider.last_model.base_url, "https://relay.internal")
        self.assertEqual(provider.last_model.api_key, "relay-secret")


def _build_client(*, provider: LLMProvider, model: LLMModelConfig) -> LLMClient:
    registry = ProviderRegistry.empty().register(provider)
    router = LLMRouter(
        hook_defaults={
            LLMTaskHook.ASSIST_DRAFT: model,
        }
    )
    return LLMClient(registry=registry, router=router)


if __name__ == "__main__":
    unittest.main()
