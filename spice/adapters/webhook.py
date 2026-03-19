from __future__ import annotations

from typing import Any
from uuid import uuid4

from spice.protocols import Observation


class WebhookAdapter:
    """
    Lightweight webhook normalization helper.

    This adapter does not run a server; it only converts webhook-style payloads
    into observation-ready data or Observation records.
    """

    def __init__(
        self,
        *,
        default_source: str = "webhook.adapter",
        default_observation_type: str = "webhook.event",
        event_type_field: str = "event_type",
        attributes_field: str = "data",
    ) -> None:
        self.default_source = default_source
        self.default_observation_type = default_observation_type
        self.event_type_field = event_type_field
        self.attributes_field = attributes_field

    def normalize_payload(
        self,
        payload: dict[str, Any],
        *,
        source: str | None = None,
        observation_type: str | None = None,
    ) -> dict[str, Any]:
        normalized_source = source or str(payload.get("source", self.default_source))
        normalized_type = observation_type or str(
            payload.get(self.event_type_field, self.default_observation_type)
        )

        attributes = payload.get(self.attributes_field)
        if not isinstance(attributes, dict):
            attributes = self._fallback_attributes(payload)

        metadata = dict(payload.get("metadata", {}))
        refs_raw = payload.get("refs", [])
        refs = list(refs_raw) if isinstance(refs_raw, list) else []

        return {
            "id": str(payload.get("id") or f"obs-{uuid4().hex}"),
            "observation_type": normalized_type,
            "source": normalized_source,
            "attributes": dict(attributes),
            "metadata": metadata,
            "refs": refs,
            "timestamp": payload.get("timestamp"),
        }

    def to_observation(
        self,
        payload: dict[str, Any],
        *,
        source: str | None = None,
        observation_type: str | None = None,
    ) -> Observation:
        normalized = self.normalize_payload(
            payload,
            source=source,
            observation_type=observation_type,
        )
        observation = Observation(
            id=normalized["id"],
            observation_type=normalized["observation_type"],
            source=normalized["source"],
            attributes=normalized["attributes"],
            metadata=normalized["metadata"],
            refs=normalized["refs"],
        )
        if normalized.get("timestamp") is not None:
            # Keep webhook timestamp as provided when upstream already normalized it.
            observation.timestamp = normalized["timestamp"]
        return observation

    @staticmethod
    def _fallback_attributes(payload: dict[str, Any]) -> dict[str, Any]:
        excluded = {"id", "timestamp", "refs", "metadata", "source", "event_type"}
        return {key: value for key, value in payload.items() if key not in excluded}
