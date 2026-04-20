from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


SUPPORTED_OBSERVATION_TYPES = {
    "commitment_declared",
    "work_item_opened",
    "executor_capability_observed",
    "execution_result_observed",
}

VALID_EXECUTION_STATUSES = {
    "success",
    "failed",
    "partial",
    "abandoned",
    "skipped",
}

VALID_RISK_CHANGES = {
    "reduced",
    "increased",
    "unchanged",
    "unknown",
}

OBSERVATION_ID_PATTERN = re.compile(r"^obs_[0-9a-f]{32}$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_observation_id() -> str:
    return f"obs_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class ObservationValidationIssue:
    severity: str
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
        }


@dataclass(slots=True)
class BaseObservation:
    observation_id: str | None = None
    observation_type: str = ""
    source: str = ""
    observed_at: str = ""
    confidence: Any = 1.0
    provenance: Any = field(default_factory=dict)


@dataclass(slots=True)
class StructuredObservation(BaseObservation):
    attributes: Any = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "observation_type": self.observation_type,
            "source": self.source,
            "observed_at": self.observed_at,
            "confidence": self.confidence,
            "attributes": self.attributes,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StructuredObservation:
        return cls(
            observation_id=payload.get("observation_id"),
            observation_type=str(payload.get("observation_type", "")),
            source=str(payload.get("source", "")),
            observed_at=str(payload.get("observed_at", "")),
            confidence=payload.get("confidence", 1.0),
            attributes=payload.get("attributes", {}),
            provenance=payload.get("provenance", {}),
        )

    @classmethod
    def from_json(cls, raw: str) -> StructuredObservation:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("observation JSON must be an object")
        return cls.from_dict(payload)


@dataclass(frozen=True, slots=True)
class CommitmentDeclaredAttributes:
    summary: str
    start_time: str
    end_time: str | None = None
    duration_minutes: int | None = None
    prep_start_time: str | None = None
    priority_hint: str | None = None
    flexibility_hint: str | None = None
    constraint_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkItemOpenedAttributes:
    kind: str
    repo: str
    item_id: str
    title: str
    action: str
    event_key: str
    url: str | None = None
    urgency_hint: str | None = None
    estimated_minutes_hint: int | None = None
    requires_attention: bool | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResultObservedAttributes:
    decision_id: str
    execution_ref: str
    acted_on: str
    selected_action: str
    status: str
    elapsed_minutes: int | None = None
    blocking_issue: str | None = None
    risk_change: str | None = None
    followup_needed: bool | None = None
    followup_summary: str | None = None
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutorCapabilityObservedAttributes:
    capability_id: str
    action_type: str
    executor: str
    supported_scopes: tuple[str, ...]
    requires_confirmation: bool
    reversible: bool
    default_time_budget_minutes: int
    availability: str


def validate_observation(
    observation: StructuredObservation,
) -> list[ObservationValidationIssue]:
    issues: list[ObservationValidationIssue] = []

    issues.extend(_validate_base(observation))

    if not isinstance(observation.attributes, dict):
        issues.append(
            ObservationValidationIssue(
                "error", "attributes", "attributes must be an object"
            )
        )
        return issues

    if observation.observation_type == "commitment_declared":
        issues.extend(_validate_commitment_declared(observation))
    elif observation.observation_type == "work_item_opened":
        issues.extend(_validate_work_item_opened(observation))
    elif observation.observation_type == "executor_capability_observed":
        issues.extend(_validate_executor_capability_observed(observation))
    elif observation.observation_type == "execution_result_observed":
        issues.extend(_validate_execution_result_observed(observation))

    return issues


def build_event_key(
    *,
    source: str,
    namespace: str,
    item_type: str,
    item_id: str | int,
    action: str,
) -> str:
    return f"{source}:{namespace}:{item_type}:{item_id}:{action}"


def _validate_base(
    observation: StructuredObservation,
) -> list[ObservationValidationIssue]:
    issues: list[ObservationValidationIssue] = []

    if not isinstance(observation.observation_id, str) or not (
        OBSERVATION_ID_PATTERN.match(observation.observation_id)
    ):
        issues.append(
            ObservationValidationIssue(
                "error",
                "observation_id",
                "observation_id is required and must be generated as obs_<32 hex chars>",
            )
        )

    if observation.observation_type not in SUPPORTED_OBSERVATION_TYPES:
        issues.append(
            ObservationValidationIssue(
                "error",
                "observation_type",
                f"unsupported observation type: {observation.observation_type}",
            )
        )

    if not observation.source:
        issues.append(
            ObservationValidationIssue("error", "source", "source is required")
        )

    if not _is_iso8601_with_timezone(observation.observed_at):
        issues.append(
            ObservationValidationIssue(
                "error",
                "observed_at",
                "observed_at is required and must be ISO-8601 with timezone",
            )
        )

    if (
        not isinstance(observation.confidence, int | float)
        or isinstance(observation.confidence, bool)
        or not 0 <= observation.confidence <= 1
    ):
        issues.append(
            ObservationValidationIssue(
                "error", "confidence", "confidence must be between 0 and 1"
            )
        )

    if not isinstance(observation.provenance, dict):
        issues.append(
            ObservationValidationIssue(
                "error", "provenance", "provenance must be an object"
            )
        )

    return issues


def _validate_commitment_declared(
    observation: StructuredObservation,
) -> list[ObservationValidationIssue]:
    issues: list[ObservationValidationIssue] = []
    attributes = observation.attributes

    _require_string(attributes, "summary", issues)
    _require_iso_datetime(attributes, "start_time", issues)
    if "end_time" not in attributes and "duration_minutes" not in attributes:
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.end_time",
                "commitment_declared requires end_time or duration_minutes",
            )
        )
    if "end_time" in attributes:
        _require_iso_datetime(attributes, "end_time", issues)
    if "duration_minutes" in attributes:
        _require_positive_int(attributes, "duration_minutes", issues)
    if "prep_start_time" in attributes:
        _require_iso_datetime(attributes, "prep_start_time", issues)
    if "priority_hint" in attributes and not isinstance(
        attributes.get("priority_hint"), str
    ):
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.priority_hint",
                "priority_hint must be a string when present",
            )
        )
    if "flexibility_hint" in attributes and not isinstance(
        attributes.get("flexibility_hint"), str
    ):
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.flexibility_hint",
                "flexibility_hint must be a string when present",
            )
        )
    if "constraint_hints" in attributes:
        _require_string_list(attributes, "constraint_hints", issues)

    return issues


def _validate_work_item_opened(
    observation: StructuredObservation,
) -> list[ObservationValidationIssue]:
    issues: list[ObservationValidationIssue] = []
    attributes = observation.attributes

    _require_string(attributes, "kind", issues)
    _require_string(attributes, "repo", issues)
    _require_string(attributes, "item_id", issues)
    _require_string(attributes, "title", issues)
    _require_string(attributes, "action", issues)
    _require_string(attributes, "event_key", issues)
    if "url" in attributes and not isinstance(attributes.get("url"), str):
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.url",
                "url must be a string when present",
            )
        )
    if "estimated_minutes_hint" in attributes:
        _require_positive_int(attributes, "estimated_minutes_hint", issues)
    if "urgency_hint" in attributes and not isinstance(
        attributes.get("urgency_hint"), str
    ):
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.urgency_hint",
                "urgency_hint must be a string when present",
            )
        )
    if "requires_attention" in attributes and not isinstance(
        attributes.get("requires_attention"), bool
    ):
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.requires_attention",
                "requires_attention must be a boolean when present",
            )
        )

    return issues


def _validate_execution_result_observed(
    observation: StructuredObservation,
) -> list[ObservationValidationIssue]:
    issues: list[ObservationValidationIssue] = []
    attributes = observation.attributes

    _require_string(attributes, "decision_id", issues)
    _require_string(attributes, "execution_ref", issues)
    _require_string(attributes, "acted_on", issues)
    _require_string(attributes, "selected_action", issues)

    status = attributes.get("status")
    if status not in VALID_EXECUTION_STATUSES:
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.status",
                "status must be one of: " + ", ".join(sorted(VALID_EXECUTION_STATUSES)),
            )
        )

    risk_change = attributes.get("risk_change")
    if risk_change is not None and risk_change not in VALID_RISK_CHANGES:
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.risk_change",
                "risk_change must be one of: " + ", ".join(sorted(VALID_RISK_CHANGES)),
            )
        )

    if "elapsed_minutes" in attributes and attributes.get("elapsed_minutes") is not None:
        _require_non_negative_int(attributes, "elapsed_minutes", issues)
    if "followup_needed" in attributes and not isinstance(
        attributes.get("followup_needed"), bool
    ):
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.followup_needed",
                "followup_needed must be a boolean when present",
            )
        )

    return issues


def _validate_executor_capability_observed(
    observation: StructuredObservation,
) -> list[ObservationValidationIssue]:
    issues: list[ObservationValidationIssue] = []
    attributes = observation.attributes

    _require_string(attributes, "capability_id", issues)
    _require_string(attributes, "action_type", issues)
    _require_string(attributes, "executor", issues)
    _require_string_list(attributes, "supported_scopes", issues)
    _require_string(attributes, "availability", issues)
    if "requires_confirmation" not in attributes or not isinstance(
        attributes.get("requires_confirmation"), bool
    ):
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.requires_confirmation",
                "requires_confirmation is required and must be a boolean",
            )
        )
    if "reversible" not in attributes or not isinstance(
        attributes.get("reversible"), bool
    ):
        issues.append(
            ObservationValidationIssue(
                "error",
                "attributes.reversible",
                "reversible is required and must be a boolean",
            )
        )
    _require_positive_int(attributes, "default_time_budget_minutes", issues)

    return issues


def _require_string(
    attributes: dict[str, Any],
    field_name: str,
    issues: list[ObservationValidationIssue],
) -> None:
    value = attributes.get(field_name)
    if not isinstance(value, str) or not value.strip():
        issues.append(
            ObservationValidationIssue(
                "error",
                f"attributes.{field_name}",
                f"{field_name} is required and must be a non-empty string",
            )
        )


def _require_iso_datetime(
    attributes: dict[str, Any],
    field_name: str,
    issues: list[ObservationValidationIssue],
) -> None:
    value = attributes.get(field_name)
    if not isinstance(value, str) or not _is_iso8601_with_timezone(value):
        issues.append(
            ObservationValidationIssue(
                "error",
                f"attributes.{field_name}",
                f"{field_name} must be ISO-8601 with timezone",
            )
        )


def _require_positive_int(
    attributes: dict[str, Any],
    field_name: str,
    issues: list[ObservationValidationIssue],
) -> None:
    value = attributes.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        issues.append(
            ObservationValidationIssue(
                "error",
                f"attributes.{field_name}",
                f"{field_name} must be a positive integer",
            )
        )


def _require_non_negative_int(
    attributes: dict[str, Any],
    field_name: str,
    issues: list[ObservationValidationIssue],
) -> None:
    value = attributes.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        issues.append(
            ObservationValidationIssue(
                "error",
                f"attributes.{field_name}",
                f"{field_name} must be a non-negative integer",
            )
        )


def _require_string_list(
    attributes: dict[str, Any],
    field_name: str,
    issues: list[ObservationValidationIssue],
) -> None:
    value = attributes.get(field_name)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        issues.append(
            ObservationValidationIssue(
                "error",
                f"attributes.{field_name}",
                f"{field_name} must be a list of non-empty strings",
            )
        )


def _is_iso8601_with_timezone(value: str) -> bool:
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None
