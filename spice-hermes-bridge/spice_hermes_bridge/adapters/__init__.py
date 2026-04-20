"""External signal adapters live here."""
from spice_hermes_bridge.adapters.github_pr import (
    GitHubPollResult,
    GitHubWorkItemEvent,
    poll_github_repo,
)
from spice_hermes_bridge.adapters.whatsapp import (
    WhatsAppInboundMessage,
    WhatsAppIngressResult,
    observe_whatsapp_message,
)

__all__ = [
    "GitHubPollResult",
    "GitHubWorkItemEvent",
    "poll_github_repo",
    "WhatsAppInboundMessage",
    "WhatsAppIngressResult",
    "observe_whatsapp_message",
]
