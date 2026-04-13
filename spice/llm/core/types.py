from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spice.llm.core.task_hooks import LLMTaskHook


@dataclass(slots=True, frozen=True)
class LLMRequest:
    task_hook: LLMTaskHook
    domain: str | None = None
    input_text: str = ""
    system_text: str = ""
    response_format_hint: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_sec: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class LLMModelConfig:
    provider_id: str
    model_id: str
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_sec: float | None = None
    response_format_hint: str = ""


@dataclass(slots=True, frozen=True)
class LLMResponse:
    provider_id: str
    model_id: str
    output_text: str
    raw_payload: dict[str, Any]
    finish_reason: str
    usage: dict[str, Any]
    latency_ms: int
    request_id: str
