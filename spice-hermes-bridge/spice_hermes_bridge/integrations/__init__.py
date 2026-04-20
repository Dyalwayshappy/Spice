"""Thin glue between bridge ingress, the Spice demo domain, and executors."""

from spice_hermes_bridge.integrations.spice_demo import (
    SpiceDemoSession,
    bridge_observation_to_spice,
    sample_bridge_observations,
)
from spice_hermes_bridge.integrations.hermes_relay import (
    HermesInboundRelay,
    normalize_hermes_whatsapp_message,
    relay_from_environment,
)
from spice_hermes_bridge.integrations.whatsapp_server import (
    DryRunWhatsAppSender,
    HttpWhatsAppSender,
    WhatsAppWebhookRuntime,
    handle_whatsapp_webhook_payload,
    send_whatsapp_message,
)
from spice_hermes_bridge.integrations.whatsapp_reply import (
    format_confirmation_resolution_for_whatsapp,
    format_control_result_for_whatsapp,
    format_execution_result_for_whatsapp,
)

__all__ = [
    "SpiceDemoSession",
    "bridge_observation_to_spice",
    "DryRunWhatsAppSender",
    "format_confirmation_resolution_for_whatsapp",
    "format_control_result_for_whatsapp",
    "format_execution_result_for_whatsapp",
    "handle_whatsapp_webhook_payload",
    "HermesInboundRelay",
    "HttpWhatsAppSender",
    "normalize_hermes_whatsapp_message",
    "relay_from_environment",
    "sample_bridge_observations",
    "send_whatsapp_message",
    "WhatsAppWebhookRuntime",
]
