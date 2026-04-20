from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


DEFAULT_MESSAGES_URL = "http://127.0.0.1:3000/messages"
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 10

JsonGetter = Callable[[str, int], Any]
JsonPoster = Callable[[str, dict[str, Any], int], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RelayedWhatsAppMessage:
    chat_id: str
    sender: str
    text: str
    timestamp: str
    message_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_webhook_payload(self) -> dict[str, Any]:
        payload = {
            "chat_id": self.chat_id,
            "sender": self.sender,
            "text": self.text,
            "timestamp": self.timestamp,
            "received_at": self.timestamp,
            "raw": self.raw,
        }
        if self.message_id:
            payload["message_id"] = self.message_id
        return payload


@dataclass(frozen=True, slots=True)
class RelayPollResult:
    status: str
    forwarded: int
    skipped: int
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "forwarded": self.forwarded,
            "skipped": self.skipped,
            "issues": list(self.issues),
        }


class HermesInboundRelay:
    """Forward Hermes WhatsApp bridge inbound messages to the Spice webhook.

    Hermes' local WhatsApp bridge exposes a simple queue at GET /messages.
    This relay drains that queue, normalizes message fields, and forwards each
    message to WHATSAPP_WEBHOOK_URL. It intentionally does not parse schedules,
    update Spice state, or make decisions.
    """

    def __init__(
        self,
        *,
        webhook_url: str,
        messages_url: str = DEFAULT_MESSAGES_URL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        http_get_json: JsonGetter | None = None,
        http_post_json: JsonPoster | None = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.messages_url = messages_url
        self.timeout_seconds = timeout_seconds
        self._http_get_json = http_get_json or http_get_json_stdlib
        self._http_post_json = http_post_json or http_post_json_stdlib
        self._seen_message_keys: set[str] = set()

    def poll_once(self) -> RelayPollResult:
        try:
            response = self._http_get_json(self.messages_url, self.timeout_seconds)
        except Exception as exc:  # pragma: no cover - covered through injected failure paths.
            return RelayPollResult(
                status="error",
                forwarded=0,
                skipped=0,
                issues=(f"failed to read Hermes messages: {exc}",),
            )

        raw_messages = extract_message_list(response)
        forwarded = 0
        skipped = 0
        issues: list[str] = []
        for raw in raw_messages:
            if not isinstance(raw, dict):
                skipped += 1
                issues.append("skipped non-object message")
                continue
            normalized = normalize_hermes_whatsapp_message(raw)
            if normalized is None:
                skipped += 1
                continue
            key = _message_dedup_key(normalized)
            if key in self._seen_message_keys:
                skipped += 1
                continue
            try:
                self._http_post_json(
                    self.webhook_url,
                    normalized.to_webhook_payload(),
                    self.timeout_seconds,
                )
            except Exception as exc:
                skipped += 1
                issues.append(f"failed to forward message {key}: {exc}")
                continue
            self._seen_message_keys.add(key)
            forwarded += 1

        status = "ok" if not issues else ("partial" if forwarded else "error")
        return RelayPollResult(
            status=status,
            forwarded=forwarded,
            skipped=skipped,
            issues=tuple(issues),
        )

    def run_forever(self, *, poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        print(f"Hermes inbound source: {self.messages_url}", flush=True)
        print(f"Webhook endpoint: {self.webhook_url}", flush=True)
        while True:
            result = self.poll_once()
            if result.forwarded or result.issues:
                print(json.dumps(result.to_dict(), ensure_ascii=False), flush=True)
            time.sleep(poll_interval_seconds)


def extract_message_list(response: Any) -> list[Any]:
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in ("messages", "data", "items", "events"):
            value = response.get(key)
            if isinstance(value, list):
                return value
    return []


def normalize_hermes_whatsapp_message(raw: dict[str, Any]) -> RelayedWhatsAppMessage | None:
    text = _first_string(raw, "body", "text", "message", "content")
    if not text:
        return None
    chat_id = _first_string(raw, "chatId", "chat_id", "thread_id", "from", "remoteJid")
    if not chat_id:
        return None
    sender = _first_string(
        raw,
        "senderId",
        "sender_id",
        "sender",
        "author",
        "participant",
        "from",
    ) or "unknown"
    timestamp = _normalize_timestamp(raw.get("timestamp") or raw.get("received_at") or raw.get("receivedAt"))
    message_id = _first_string(raw, "messageId", "message_id", "id")
    if not message_id:
        key = raw.get("key")
        if isinstance(key, dict):
            message_id = _first_string(key, "id")
    return RelayedWhatsAppMessage(
        chat_id=chat_id,
        sender=sender,
        text=text,
        timestamp=timestamp,
        message_id=message_id,
        raw=raw,
    )


def http_get_json_stdlib(url: str, timeout_seconds: int) -> Any:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw or "null")


def http_post_json_stdlib(url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
        if not raw:
            parsed: Any = {}
        else:
            parsed = json.loads(raw)
        return {
            "status": response.status,
            "body": parsed,
        }


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_timestamp(value: Any) -> str:
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds = seconds / 1000
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    if isinstance(value, str) and value.strip():
        stripped = value.strip()
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            return _now_utc()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    return _now_utc()


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _message_dedup_key(message: RelayedWhatsAppMessage) -> str:
    if message.message_id:
        return f"id:{message.chat_id}:{message.message_id}"
    return f"body:{message.chat_id}:{message.timestamp}:{message.text}"


def relay_from_environment(
    *,
    webhook_url: str | None = None,
    messages_url: str | None = None,
) -> HermesInboundRelay:
    resolved_webhook_url = webhook_url or os.getenv("WHATSAPP_WEBHOOK_URL")
    if not resolved_webhook_url:
        raise ValueError("WHATSAPP_WEBHOOK_URL is required, for example https://xxx.ngrok-free.app/whatsapp/webhook")
    return HermesInboundRelay(
        webhook_url=resolved_webhook_url,
        messages_url=messages_url or os.getenv("HERMES_WHATSAPP_MESSAGES_URL", DEFAULT_MESSAGES_URL),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Relay Hermes WhatsApp inbound messages to the Spice webhook.")
    parser.add_argument("--webhook-url", default=os.getenv("WHATSAPP_WEBHOOK_URL"))
    parser.add_argument(
        "--messages-url",
        default=os.getenv("HERMES_WHATSAPP_MESSAGES_URL", DEFAULT_MESSAGES_URL),
    )
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--once", action="store_true", help="Poll once and exit.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable poll result.")
    args = parser.parse_args(argv)

    if not args.webhook_url:
        print(
            "WHATSAPP_WEBHOOK_URL is required, for example https://xxx.ngrok-free.app/whatsapp/webhook",
            file=sys.stderr,
        )
        return 2

    relay = HermesInboundRelay(webhook_url=args.webhook_url, messages_url=args.messages_url)
    if args.once:
        result = relay.poll_once()
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False))
        else:
            print(f"Webhook endpoint: {args.webhook_url}")
            print(json.dumps(result.to_dict(), ensure_ascii=False))
        return 0 if result.status in {"ok", "partial"} else 1

    relay.run_forever(poll_interval_seconds=args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
