from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from examples.decision_hub_demo.state import DOMAIN_KEY

from spice_hermes_bridge.adapters.whatsapp import (
    WhatsAppInboundMessage,
    observe_whatsapp_message,
)
from spice_hermes_bridge.integrations.spice_demo import SpiceDemoSession
from spice_hermes_bridge.integrations.whatsapp_reply import (
    format_confirmation_resolution_for_whatsapp,
    format_control_result_for_whatsapp,
)
from spice_hermes_bridge.observations import StructuredObservation, build_observation
from spice_hermes_bridge.storage.pending import DEFAULT_PENDING_STORE


Choice = str
NowProvider = Callable[[], datetime]


class WhatsAppSender(Protocol):
    def send(self, chat_id: str, text: str) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class DryRunWhatsAppSender:
    """Default sender used when a Hermes send endpoint is not configured."""

    sent_messages: list[dict[str, Any]] = field(default_factory=list)

    def send(self, chat_id: str, text: str) -> dict[str, Any]:
        payload = {"chat_id": chat_id, "text": text}
        self.sent_messages.append(payload)
        return {"status": "dry_run", **payload}


@dataclass(slots=True)
class HttpWhatsAppSender:
    """Thin HTTP sender for a Hermes WhatsApp send endpoint.

    Configure with HERMES_WHATSAPP_SEND_URL. Hermes' local WhatsApp bridge
    accepts JSON shaped as {"chatId": "...", "message": "..."} at /send.
    """

    url: str
    token: str | None = None
    timeout_seconds: int = 10

    def send(self, chat_id: str, text: str) -> dict[str, Any]:
        body = json.dumps({"chatId": chat_id, "message": text}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                parsed = _parse_json_object(raw)
                return {
                    "status": "sent",
                    "chat_id": chat_id,
                    "http_status": response.status,
                    "response": parsed or raw,
                }
        except urllib.error.URLError as exc:
            return {
                "status": "send_failed",
                "chat_id": chat_id,
                "error": str(exc),
            }


@dataclass(slots=True)
class WhatsAppChatSession:
    chat_id: str
    spice_session: SpiceDemoSession
    active_confirmation_id: str | None = None
    executor_capability_ingested: bool = False


@dataclass(slots=True)
class WhatsAppWebhookResult:
    chat_id: str
    input_type: str
    reply_text: str
    send_result: dict[str, Any]
    ingress: dict[str, Any] | None = None
    recommendation: dict[str, Any] | None = None
    control: dict[str, Any] | None = None
    resolution: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "input_type": self.input_type,
            "reply_text": self.reply_text,
            "send_result": self.send_result,
            "ingress": self.ingress,
            "recommendation": self.recommendation,
            "control": self.control,
            "resolution": self.resolution,
        }


class WhatsAppWebhookRuntime:
    """Minimal WhatsApp -> Bridge -> Spice demo control loop.

    The runtime is intentionally process-local. It keeps one Spice demo session
    per chat_id and one active confirmation per chat for the v1 demo path.
    """

    def __init__(
        self,
        *,
        sender: WhatsAppSender | None = None,
        executor: Any | None = None,
        extractor: str = "deterministic",
        default_timezone: str = "Asia/Shanghai",
        pending_store_path: Path | None = DEFAULT_PENDING_STORE,
        now_provider: NowProvider | None = None,
        auto_ingest_executor_capability: bool = True,
    ) -> None:
        self.sender = sender or sender_from_environment()
        # Keep None as None so SpiceDemoSession uses the decision_hub_demo
        # default SDEP-backed executor spine, matching run-demo-flow.
        self.executor = executor
        self.extractor = extractor
        self.default_timezone = default_timezone
        self.pending_store_path = pending_store_path
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.auto_ingest_executor_capability = auto_ingest_executor_capability
        self.sessions: dict[str, WhatsAppChatSession] = {}

    def session_for(self, chat_id: str) -> WhatsAppChatSession:
        if chat_id not in self.sessions:
            self.sessions[chat_id] = WhatsAppChatSession(
                chat_id=chat_id,
                spice_session=SpiceDemoSession(executor=self.executor),
            )
        session = self.sessions[chat_id]
        if self.auto_ingest_executor_capability and not session.executor_capability_ingested:
            session.spice_session.ingest_into_spice(build_default_executor_capability_observation())
            session.executor_capability_ingested = True
        return session

    def ingest_observation_for_chat(
        self,
        chat_id: str,
        observation: StructuredObservation,
    ) -> None:
        self.session_for(chat_id).spice_session.ingest_into_spice(observation)

    def handle_payload(self, payload: dict[str, Any]) -> WhatsAppWebhookResult:
        message = inbound_message_from_payload(payload)
        chat_id = message.chat_id or "whatsapp.default"
        text = message.text.strip()
        session = self.session_for(chat_id)

        choice = _choice_from_text(text)
        if choice:
            return self._handle_choice(session, choice)
        return self._handle_natural_message(session, message)

    def _handle_choice(
        self,
        session: WhatsAppChatSession,
        choice: Choice,
    ) -> WhatsAppWebhookResult:
        if not session.active_confirmation_id:
            reply = "当前没有待确认的 Spice 决策。请先发送一个需要决策的信息。"
            return self._reply(session.chat_id, "invalid_choice", reply)

        resolution = session.spice_session.resolve_confirmation(
            session.active_confirmation_id,
            choice=choice,
            now=self.now_provider(),
        )
        if resolution.status in {"executed", "rejected", "missing", "already_resolved"}:
            session.active_confirmation_id = None
        reply = format_confirmation_resolution_for_whatsapp(resolution)
        return self._reply(
            session.chat_id,
            f"confirmation_{choice}",
            reply,
            resolution=resolution.to_payload(),
        )

    def _handle_natural_message(
        self,
        session: WhatsAppChatSession,
        message: WhatsAppInboundMessage,
    ) -> WhatsAppWebhookResult:
        ingress = observe_whatsapp_message(
            message,
            default_timezone=self.default_timezone,
            extractor=self.extractor,
            pending_store_path=self.pending_store_path,
            persist_pending=True,
            resolve_pending=True,
        )
        if ingress.result_type == "pending_confirmation":
            pending = ingress.pending_confirmation
            reply = pending.message if pending else "信息不够明确，请补充具体时间或时长。"
            return self._reply(
                session.chat_id,
                "pending_confirmation",
                reply,
                ingress=ingress.to_dict(),
            )
        if ingress.result_type == "ignored":
            reply = "我没理解你的意思，可以再说清楚一点。"
            return self._reply(
                session.chat_id,
                "ignored",
                reply,
                ingress=ingress.to_dict(),
            )
        if ingress.observation is None:
            reply = "我没理解你的意思，可以再说清楚一点。"
            return self._reply(
                session.chat_id,
                "invalid",
                reply,
                ingress=ingress.to_dict(),
            )

        session.spice_session.ingest_into_spice(ingress.observation)
        if not _has_open_work_items(session.spice_session):
            reply = "已记录到 Spice state。当前没有打开的 work item，因此没有触发执行建议。"
            return self._reply(
                session.chat_id,
                "observation_recorded",
                reply,
                ingress=ingress.to_dict(),
            )

        try:
            recommendation = session.spice_session.recommend(now=self.now_provider())
        except (LookupError, ValueError, StopIteration) as exc:
            reply = f"已记录到 Spice state，但当前无法生成稳定建议：{exc}"
            return self._reply(
                session.chat_id,
                "decision_unavailable",
                reply,
                ingress=ingress.to_dict(),
            )
        control = session.spice_session.handle_recommendation(
            recommendation,
            now=self.now_provider(),
        )
        if control.confirmation_request:
            session.active_confirmation_id = str(control.confirmation_request["confirmation_id"])
        reply = format_control_result_for_whatsapp(control)
        return self._reply(
            session.chat_id,
            "decision_control",
            reply,
            ingress=ingress.to_dict(),
            recommendation=recommendation,
            control=control.to_payload(),
        )

    def _reply(
        self,
        chat_id: str,
        input_type: str,
        reply: str,
        *,
        ingress: dict[str, Any] | None = None,
        recommendation: dict[str, Any] | None = None,
        control: dict[str, Any] | None = None,
        resolution: dict[str, Any] | None = None,
    ) -> WhatsAppWebhookResult:
        return WhatsAppWebhookResult(
            chat_id=chat_id,
            input_type=input_type,
            reply_text=reply,
            send_result=send_whatsapp_message(chat_id, reply, sender=self.sender),
            ingress=ingress,
            recommendation=recommendation,
            control=control,
            resolution=resolution,
        )


def inbound_message_from_payload(payload: dict[str, Any]) -> WhatsAppInboundMessage:
    return WhatsAppInboundMessage.from_payload(_flatten_message_payload(payload))


def send_whatsapp_message(
    chat_id: str,
    text: str,
    *,
    sender: WhatsAppSender | None = None,
) -> dict[str, Any]:
    return (sender or sender_from_environment()).send(chat_id, text)


def sender_from_environment() -> WhatsAppSender:
    url = os.getenv("HERMES_WHATSAPP_SEND_URL")
    if url:
        return HttpWhatsAppSender(
            url=url,
            token=os.getenv("HERMES_WHATSAPP_SEND_TOKEN"),
        )
    return DryRunWhatsAppSender()


def build_default_executor_capability_observation() -> StructuredObservation:
    return build_observation(
        observation_type="executor_capability_observed",
        source="hermes",
        confidence=1.0,
        attributes={
            "capability_id": "cap.external_executor.codex",
            "action_type": "delegate_to_executor",
            "executor": "codex",
            "supported_scopes": ["triage", "review_summary"],
            "requires_confirmation": True,
            "reversible": True,
            "default_time_budget_minutes": 10,
            "availability": "available",
        },
        provenance={
            "adapter": "whatsapp_server.hermes_capability.v1",
            "reported_by": "hermes",
            "notes": "Codex available through Hermes for WhatsApp control-loop demo.",
        },
    )


def _has_open_work_items(session: SpiceDemoSession) -> bool:
    demo = session.state.domain_state.get(DOMAIN_KEY, {})
    return any(
        item.get("status", "open") == "open" and item.get("requires_attention", True)
        for item in demo.get("work_items", {}).values()
        if isinstance(item, dict)
    )


def _choice_from_text(text: str) -> str | None:
    normalized = text.strip()
    aliases = {
        "1": "confirm",
        "同意": "confirm",
        "确认": "confirm",
        "confirm": "confirm",
        "2": "reject",
        "拒绝": "reject",
        "取消": "reject",
        "reject": "reject",
        "3": "details",
        "详情": "details",
        "details": "details",
    }
    return aliases.get(normalized)


def _flatten_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for candidate in _payload_candidates(payload):
        for key, value in candidate.items():
            if key not in flattened and value is not None:
                flattened[key] = value
    if "message" in payload and isinstance(payload["message"], str):
        flattened.setdefault("text", payload["message"])
    if "sender" in flattened and "sender_id" not in flattened:
        flattened["sender_id"] = flattened["sender"]
    return flattened


def _payload_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [payload]
    for key in ("data", "payload", "event"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
            message = value.get("message")
            if isinstance(message, dict):
                candidates.append(message)
    message = payload.get("message")
    if isinstance(message, dict):
        candidates.append(message)
    return candidates


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


DEFAULT_RUNTIME = WhatsAppWebhookRuntime()


def handle_whatsapp_webhook_payload(
    payload: dict[str, Any],
    *,
    runtime: WhatsAppWebhookRuntime | None = None,
) -> dict[str, Any]:
    return (runtime or DEFAULT_RUNTIME).handle_payload(payload).to_payload()


class WhatsAppWebhookASGIApp:
    def __init__(self) -> None:
        webhook_url = os.getenv("WHATSAPP_WEBHOOK_URL")
        if webhook_url:
            print(f"Webhook endpoint: {webhook_url}", flush=True)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await _send_response(send, 404, {"error": "unsupported scope"})
            return
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if method == "GET" and path == "/health":
            await _send_response(send, 200, {"status": "ok"})
            return
        if method != "POST" or path != "/whatsapp/webhook":
            await _send_response(send, 404, {"error": "not found"})
            return
        body = await _read_body(receive)
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            await _send_response(send, 400, {"error": "invalid JSON body"})
            return
        if not isinstance(payload, dict):
            await _send_response(send, 400, {"error": "body must be a JSON object"})
            return
        result = handle_whatsapp_webhook_payload(payload)
        await _send_response(send, 200, result)


async def _read_body(receive: Any) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


async def _send_response(send: Any, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": body})


app = WhatsAppWebhookASGIApp()
