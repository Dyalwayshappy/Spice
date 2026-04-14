from __future__ import annotations

import json
import os
import time
import urllib.error as urllib_error
import urllib.request as urllib_request
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from spice.llm.core.provider import (
    LLMAuthError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponseError,
    LLMTransportError,
)
from spice.llm.core.types import LLMModelConfig, LLMRequest, LLMResponse


OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
OPENROUTER_BASE_URL_ENV = "SPICE_OPENROUTER_BASE_URL"
OPENROUTER_SITE_URL_ENV = "SPICE_OPENROUTER_SITE_URL"
OPENROUTER_APP_NAME_ENV = "SPICE_OPENROUTER_APP_NAME"
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(slots=True)
class OpenRouterLLMProvider(LLMProvider):
    provider_id: str = "openrouter"
    api_key_env: str = OPENROUTER_API_KEY_ENV
    base_url_env: str = OPENROUTER_BASE_URL_ENV
    site_url_env: str = OPENROUTER_SITE_URL_ENV
    app_name_env: str = OPENROUTER_APP_NAME_ENV

    def generate(self, request: LLMRequest, model: LLMModelConfig) -> LLMResponse:
        api_key = _env_value(self.api_key_env)
        if not api_key:
            raise LLMAuthError(f"{self.api_key_env} is required for OpenRouter provider.")
        if not model.model_id.strip():
            raise LLMResponseError("OpenRouter model_id is required.")

        endpoint = _chat_completions_endpoint(_env_value(self.base_url_env))
        payload = _build_chat_payload(request=request, model=model)
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        http_request = urllib_request.Request(
            endpoint,
            data=body,
            headers=self._headers(api_key),
            method="POST",
        )

        timeout_sec = (
            model.timeout_sec
            if model.timeout_sec is not None
            else request.timeout_sec
        )
        start = time.perf_counter()
        try:
            with urllib_request.urlopen(http_request, timeout=timeout_sec) as response:
                response_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            raise _normalize_http_error(exc) from exc
        except urllib_error.URLError as exc:
            raise LLMTransportError(f"OpenRouter request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMTransportError(
                f"OpenRouter request timed out after {timeout_sec}s."
            ) from exc

        latency_ms = int((time.perf_counter() - start) * 1000)
        parsed = _parse_response_json(response_body)
        output_text, finish_reason = _extract_choice(parsed)
        usage = parsed.get("usage")
        if not isinstance(usage, dict):
            usage = {}

        return LLMResponse(
            provider_id=self.provider_id,
            model_id=str(parsed.get("model") or model.model_id),
            output_text=output_text,
            raw_payload=parsed,
            finish_reason=finish_reason,
            usage=usage,
            latency_ms=latency_ms,
            request_id=str(parsed.get("id") or f"or-{uuid4().hex}"),
        )

    def _headers(self, api_key: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        site_url = _env_value(self.site_url_env)
        if site_url:
            headers["HTTP-Referer"] = site_url
        app_name = _env_value(self.app_name_env)
        if app_name:
            headers["X-OpenRouter-Title"] = app_name
        return headers


def _build_chat_payload(*, request: LLMRequest, model: LLMModelConfig) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    system_text = request.system_text.strip()
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": request.input_text})

    payload: dict[str, Any] = {
        "model": model.model_id,
        "messages": messages,
    }
    if model.temperature is not None:
        payload["temperature"] = model.temperature
    if model.max_tokens is not None:
        payload["max_tokens"] = model.max_tokens
    if model.response_format_hint == "json_object":
        payload["response_format"] = {"type": "json_object"}
    return payload


def _chat_completions_endpoint(base_url: str | None) -> str:
    normalized = (base_url or OPENROUTER_DEFAULT_BASE_URL).strip()
    if not normalized:
        normalized = OPENROUTER_DEFAULT_BASE_URL
    return normalized.rstrip("/") + "/chat/completions"


def _parse_response_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMResponseError("OpenRouter response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise LLMResponseError("OpenRouter response JSON must be an object.")
    return payload


def _extract_choice(payload: dict[str, Any]) -> tuple[str, str]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError("OpenRouter response missing choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMResponseError("OpenRouter first choice must be an object.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMResponseError("OpenRouter first choice missing message.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMResponseError("OpenRouter first choice message content is empty.")
    finish_reason = first.get("finish_reason")
    return content, str(finish_reason or "")


def _normalize_http_error(exc: urllib_error.HTTPError) -> Exception:
    body = _safe_error_body(exc)
    reason = str(getattr(exc, "reason", "") or getattr(exc, "msg", "") or "")
    message = (
        "OpenRouter request failed "
        f"(status={exc.code}): {body or reason or '<no response body>'}"
    )
    if exc.code in (401, 403):
        return LLMAuthError(message)
    if exc.code == 429:
        return LLMRateLimitError(message)
    if exc.code in (400, 404, 422):
        return LLMResponseError(message)
    return LLMTransportError(message)


def _safe_error_body(exc: urllib_error.HTTPError) -> str:
    try:
        body = exc.read()
    except Exception:
        return ""
    if not body:
        return ""
    try:
        return body.decode("utf-8").strip()
    except Exception:
        return repr(body)


def _env_value(name: str) -> str:
    return os.environ.get(name, "").strip()
