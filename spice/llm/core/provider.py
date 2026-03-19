from __future__ import annotations

from abc import ABC, abstractmethod

from spice.llm.core.types import LLMModelConfig, LLMRequest, LLMResponse


class LLMProviderError(RuntimeError):
    """Base class for normalized provider errors."""


class LLMTransportError(LLMProviderError):
    """Raised when transport-level execution fails."""


class LLMAuthError(LLMProviderError):
    """Raised when authentication/authorization fails."""


class LLMRateLimitError(LLMProviderError):
    """Raised when provider indicates throttling/rate limits."""


class LLMResponseError(LLMProviderError):
    """Raised when provider response cannot be consumed."""


class LLMProvider(ABC):
    provider_id: str

    @abstractmethod
    def generate(self, request: LLMRequest, model: LLMModelConfig) -> LLMResponse:
        """Send one request using the provided model configuration."""
