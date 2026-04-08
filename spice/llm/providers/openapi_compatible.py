from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib import parse as urllib_parse

from spice.llm.core.provider import (
    LLMAuthError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponseError,
    LLMTransportError,
)
from spice.llm.core.types import LLMModelConfig, LLMRequest, LLMResponse


@dataclass(slots=True)
class OpenAPICompatibleLLMProvider(LLMProvider):
    provider_id: str = "openapi_compatible"

    def generate(self, request: LLMRequest, model: LLMModelConfig) -> LLMResponse:
        endpoint = _resolve_endpoint(model.base_url)
        safe_endpoint = _redact_url(endpoint)
        api_key = _require_api_key(model.api_key)
        messages = _build_messages(request)
        payload = {
            "model": model.model_id,
            "messages": messages,
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        timeout_sec = (
            model.timeout_sec
            if model.timeout_sec is not None
            else request.timeout_sec
        )
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        http_request = urllib_request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        start = time.perf_counter()
        try:
            with urllib_request.urlopen(http_request, timeout=timeout_sec) as response:
                raw_bytes = response.read()
                status_code = int(getattr(response, "status", response.getcode()))
        except urllib_error.HTTPError as exc:
            message = _error_message_from_response(exc, secret=api_key)
            raise _normalize_http_error(
                status_code=int(exc.code),
                message=message,
                secret=api_key,
            ) from exc
        except urllib_error.URLError as exc:
            raise LLMTransportError(
                "openapi_compatible transport failure: "
                f"{_sanitize_text(str(exc.reason), secret=api_key)}"
            ) from exc
        except OSError as exc:
            raise LLMTransportError(
                "openapi_compatible transport failure: "
                f"{_sanitize_text(str(exc), secret=api_key)}"
            ) from exc
        except socket.timeout as exc:
            raise LLMTransportError(
                f"openapi_compatible transport timeout after {timeout_sec}s"
            ) from exc

        latency_ms = int((time.perf_counter() - start) * 1000)
        if not raw_bytes:
            raise LLMResponseError("openapi_compatible provider returned empty response body.")

        raw_text = raw_bytes.decode("utf-8", errors="replace")
        try:
            payload_obj = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise LLMResponseError("openapi_compatible provider returned non-JSON response.") from exc
        if not isinstance(payload_obj, dict):
            raise LLMResponseError("openapi_compatible provider response must be a JSON object.")

        output_text = _redact_secret(_extract_output_text(payload_obj), secret=api_key)
        if not output_text.strip():
            raise LLMResponseError("openapi_compatible provider response did not contain output text.")

        usage = payload_obj.get("usage")
        usage_payload = dict(usage) if isinstance(usage, dict) else {
            "input_chars": len(request.input_text),
            "output_chars": len(output_text),
        }
        request_id = str(
            payload_obj.get("id")
            or payload_obj.get("request_id")
            or payload_obj.get("response_id")
            or f"openapi-{int(time.time() * 1000)}"
        )

        return LLMResponse(
            provider_id=self.provider_id,
            model_id=model.model_id,
            output_text=output_text,
            raw_payload={
                "endpoint": safe_endpoint,
                "status_code": status_code,
                "response": _redact_payload(payload_obj, secret=api_key),
            },
            finish_reason=_extract_finish_reason(payload_obj),
            usage=usage_payload,
            latency_ms=latency_ms,
            request_id=request_id,
        )


def _require_api_key(value: str | None) -> str:
    token = (value or "").strip()
    if not token:
        raise LLMAuthError("openapi_compatible provider requires a non-empty API key.")
    return token


def _resolve_endpoint(base_url: str | None) -> str:
    token = (base_url or "").strip().rstrip("/")
    if not token:
        raise LLMTransportError("openapi_compatible provider requires a non-empty base_url.")
    if token.endswith("/chat/completions"):
        return token
    return token + "/chat/completions"


def _build_messages(request: LLMRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if request.system_text.strip():
        messages.append({"role": "system", "content": request.system_text.strip()})
    messages.append({"role": "user", "content": request.input_text})
    return messages


def _extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str):
        return direct

    text_value = payload.get("text")
    if isinstance(text_value, str):
        return text_value

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                extracted = _normalize_content(content)
                if extracted is not None:
                    return extracted
            legacy_text = first.get("text")
            if isinstance(legacy_text, str):
                return legacy_text

    content = payload.get("content")
    normalized = _normalize_content(content)
    if normalized is not None:
        return normalized

    return ""


def _normalize_content(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)
    return None


def _extract_finish_reason(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            reason = first.get("finish_reason")
            if isinstance(reason, str) and reason.strip():
                return reason
    reason = payload.get("finish_reason")
    if isinstance(reason, str) and reason.strip():
        return reason
    return "stop"


def _normalize_http_error(*, status_code: int, message: str, secret: str) -> Exception:
    cleaned = _sanitize_text(message, secret=secret)
    if status_code in {401, 403}:
        return LLMAuthError(
            f"openapi_compatible authentication failed (status={status_code}): {cleaned}"
        )
    if status_code == 429:
        return LLMRateLimitError(
            f"openapi_compatible rate limit exceeded (status=429): {cleaned}"
        )
    return LLMTransportError(
        f"openapi_compatible request failed (status={status_code}): {cleaned}"
    )


def _error_message_from_response(exc: urllib_error.HTTPError, *, secret: str) -> str:
    try:
        raw = exc.read()
    except Exception:
        raw = b""
    if not raw:
        return exc.reason if isinstance(exc.reason, str) else f"http_{exc.code}"
    text = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _sanitize_text(text, secret=secret)
    if isinstance(payload, dict):
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            message = error_obj.get("message")
            if isinstance(message, str) and message.strip():
                return _sanitize_text(message, secret=secret)
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return _sanitize_text(message, secret=secret)
    return _sanitize_text(text, secret=secret)


def _sanitize_text(value: str, *, secret: str | None = None) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "<no details>"
    single_line = cleaned.replace("\n", " ")
    return _redact_secret(single_line[:500], secret=secret)


def _redact_payload(payload: Any, *, secret: str | None = None) -> Any:
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if key.lower() in {"api_key", "authorization", "proxy_authorization"}:
                redacted[key] = "<redacted>"
                continue
            redacted[key] = _redact_payload(value, secret=secret)
        return redacted
    if isinstance(payload, list):
        return [_redact_payload(item, secret=secret) for item in payload]
    if isinstance(payload, str):
        return _redact_secret(payload, secret=secret)
    return payload


def _redact_secret(value: str, *, secret: str | None) -> str:
    if secret:
        return value.replace(secret, "<redacted>")
    return value


def _redact_url(url: str) -> str:
    parsed = urllib_parse.urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    authless_netloc = hostname + port
    return urllib_parse.urlunsplit(
        (parsed.scheme, authless_netloc, parsed.path, parsed.query, parsed.fragment)
    )
