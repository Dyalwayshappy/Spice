from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from spice.llm.core.provider import LLMProvider


@dataclass(slots=True, frozen=True)
class ProviderRegistry:
    providers: Mapping[str, LLMProvider] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "ProviderRegistry":
        return cls()

    def register(self, provider: LLMProvider) -> "ProviderRegistry":
        provider_id = getattr(provider, "provider_id", "").strip()
        if not provider_id:
            raise ValueError("provider_id must be a non-empty string.")
        next_map = dict(self.providers)
        next_map[provider_id] = provider
        return ProviderRegistry(providers=next_map)

    def resolve(self, provider_id: str) -> LLMProvider:
        key = provider_id.strip()
        if not key:
            raise KeyError("provider_id is required.")
        provider = self.providers.get(key)
        if provider is None:
            raise KeyError(f"Unknown LLM provider: {provider_id!r}.")
        return provider
