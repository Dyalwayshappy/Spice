from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION_V1 = "spice.domain_spec.v1"

_MISSING = object()
_DOMAIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_FIELD_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_FIELD_TYPES = {"string", "number", "integer", "boolean", "object", "array"}
_ALLOWED_EXECUTOR_TYPES = {"mock", "cli", "sdep"}


class DomainSpecValidationError(ValueError):
    """Raised when a DomainSpec payload is invalid."""


@dataclass(slots=True)
class DomainInfo:
    id: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainInfo":
        domain_id = _require_non_empty_string(payload.get("id", ""), field_name="domain.id")
        _validate_domain_id(domain_id, field_name="domain.id")
        return cls(id=domain_id)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id}


@dataclass(slots=True)
class DomainVocabulary:
    observation_types: tuple[str, ...]
    action_types: tuple[str, ...]
    outcome_types: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainVocabulary":
        observation_types = _validate_kind_list(
            payload.get("observation_types"),
            field_name="vocabulary.observation_types",
            min_items=1,
        )
        action_types = _validate_kind_list(
            payload.get("action_types"),
            field_name="vocabulary.action_types",
            min_items=1,
        )
        outcome_types = _validate_kind_list(
            payload.get("outcome_types"),
            field_name="vocabulary.outcome_types",
            min_items=1,
        )
        return cls(
            observation_types=observation_types,
            action_types=action_types,
            outcome_types=outcome_types,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_types": list(self.observation_types),
            "action_types": list(self.action_types),
            "outcome_types": list(self.outcome_types),
        }


@dataclass(slots=True)
class StateField:
    name: str
    field_type: str = "string"
    default: Any = _MISSING
    description: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, index: int) -> "StateField":
        name = _require_non_empty_string(
            payload.get("name", ""),
            field_name=f"state.fields[{index}].name",
        )
        if not _FIELD_NAME_PATTERN.fullmatch(name):
            raise DomainSpecValidationError(
                "state.fields[{idx}].name must match pattern {pattern!r}, got {value!r}.".format(
                    idx=index,
                    pattern=_FIELD_NAME_PATTERN.pattern,
                    value=name,
                )
            )

        raw_type = payload.get("type", "string")
        field_type = _require_non_empty_string(
            raw_type,
            field_name=f"state.fields[{index}].type",
        )
        if field_type not in _ALLOWED_FIELD_TYPES:
            allowed = ", ".join(sorted(_ALLOWED_FIELD_TYPES))
            raise DomainSpecValidationError(
                f"state.fields[{index}].type must be one of [{allowed}], got {field_type!r}."
            )

        description_raw = payload.get("description", "")
        if not isinstance(description_raw, str):
            raise DomainSpecValidationError(f"state.fields[{index}].description must be a string.")
        description = description_raw.strip()

        default = payload["default"] if "default" in payload else _MISSING
        return cls(
            name=name,
            field_type=field_type,
            default=default,
            description=description,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.field_type,
        }
        if self.default is not _MISSING:
            payload["default"] = self.default
        if self.description:
            payload["description"] = self.description
        return payload


@dataclass(slots=True)
class DomainState:
    entity_id: str
    fields: tuple[StateField, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainState":
        entity_id = _require_non_empty_string(
            payload.get("entity_id", ""),
            field_name="state.entity_id",
        )
        _validate_domain_id(entity_id, field_name="state.entity_id")

        fields_raw = payload.get("fields")
        if not isinstance(fields_raw, list):
            raise DomainSpecValidationError("state.fields must be a list.")
        if not fields_raw:
            raise DomainSpecValidationError("state.fields must contain at least 1 field.")

        fields: list[StateField] = []
        seen: set[str] = set()
        for idx, item in enumerate(fields_raw):
            if not isinstance(item, dict):
                raise DomainSpecValidationError(f"state.fields[{idx}] must be an object.")
            field = StateField.from_dict(item, index=idx)
            if field.name in seen:
                raise DomainSpecValidationError(
                    f"state.fields has duplicate field name {field.name!r}."
                )
            seen.add(field.name)
            fields.append(field)

        return cls(entity_id=entity_id, fields=tuple(fields))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "fields": [field.to_dict() for field in self.fields],
        }


@dataclass(slots=True)
class DomainActionExecutor:
    type: str
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        field_prefix: str,
    ) -> "DomainActionExecutor":
        executor_type = _require_non_empty_string(
            payload.get("type", ""),
            field_name=f"{field_prefix}.type",
        )
        if executor_type not in _ALLOWED_EXECUTOR_TYPES:
            allowed = ", ".join(sorted(_ALLOWED_EXECUTOR_TYPES))
            raise DomainSpecValidationError(
                f"{field_prefix}.type must be one of [{allowed}], got {executor_type!r}."
            )

        operation = _require_non_empty_string(
            payload.get("operation", ""),
            field_name=f"{field_prefix}.operation",
        )

        parameters_raw = payload.get("parameters", {})
        if not isinstance(parameters_raw, dict):
            raise DomainSpecValidationError(f"{field_prefix}.parameters must be an object.")

        return cls(
            type=executor_type,
            operation=operation,
            parameters=dict(parameters_raw),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "type": self.type,
            "operation": self.operation,
        }
        if self.parameters:
            payload["parameters"] = dict(self.parameters)
        return payload


@dataclass(slots=True)
class DomainAction:
    id: str
    executor: DomainActionExecutor
    expected_outcome_type: str
    description: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, index: int) -> "DomainAction":
        action_id = _require_non_empty_string(
            payload.get("id", ""),
            field_name=f"actions[{index}].id",
        )
        _validate_domain_id(action_id, field_name=f"actions[{index}].id")

        executor_payload = payload.get("executor")
        if not isinstance(executor_payload, dict):
            raise DomainSpecValidationError(f"actions[{index}].executor must be an object.")
        executor = DomainActionExecutor.from_dict(
            executor_payload,
            field_prefix=f"actions[{index}].executor",
        )

        expected_outcome_type = _require_non_empty_string(
            payload.get("expected_outcome_type", ""),
            field_name=f"actions[{index}].expected_outcome_type",
        )
        _validate_domain_id(
            expected_outcome_type,
            field_name=f"actions[{index}].expected_outcome_type",
        )

        description_raw = payload.get("description", "")
        if not isinstance(description_raw, str):
            raise DomainSpecValidationError(f"actions[{index}].description must be a string.")

        return cls(
            id=action_id,
            executor=executor,
            expected_outcome_type=expected_outcome_type,
            description=description_raw.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "executor": self.executor.to_dict(),
            "expected_outcome_type": self.expected_outcome_type,
        }
        if self.description:
            payload["description"] = self.description
        return payload


@dataclass(slots=True)
class DomainDecision:
    default_action: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainDecision":
        default_action = _require_non_empty_string(
            payload.get("default_action", ""),
            field_name="decision.default_action",
        )
        _validate_domain_id(default_action, field_name="decision.default_action")
        return cls(default_action=default_action)

    def to_dict(self) -> dict[str, Any]:
        return {"default_action": self.default_action}


@dataclass(slots=True)
class DemoObservation:
    type: str
    source: str
    attributes: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        index: int,
        domain_id: str,
    ) -> "DemoObservation":
        observation_type = _require_non_empty_string(
            payload.get("type", ""),
            field_name=f"demo.observations[{index}].type",
        )
        _validate_domain_id(observation_type, field_name=f"demo.observations[{index}].type")

        source = _require_non_empty_string(
            payload.get("source", f"{domain_id}.demo"),
            field_name=f"demo.observations[{index}].source",
        )

        attributes = _coerce_dict(
            payload.get("attributes", {}),
            field_name=f"demo.observations[{index}].attributes",
        )
        metadata = _coerce_dict(
            payload.get("metadata", {}),
            field_name=f"demo.observations[{index}].metadata",
        )
        return cls(
            type=observation_type,
            source=source,
            attributes=attributes,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "source": self.source,
        }
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(slots=True)
class DomainDemo:
    observations: tuple[DemoObservation, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, domain_id: str) -> "DomainDemo":
        observations_raw = payload.get("observations")
        if not isinstance(observations_raw, list):
            raise DomainSpecValidationError("demo.observations must be a list.")
        if not observations_raw:
            raise DomainSpecValidationError("demo.observations must contain at least 1 item.")

        observations: list[DemoObservation] = []
        for idx, item in enumerate(observations_raw):
            if not isinstance(item, dict):
                raise DomainSpecValidationError(f"demo.observations[{idx}] must be an object.")
            observations.append(
                DemoObservation.from_dict(
                    item,
                    index=idx,
                    domain_id=domain_id,
                )
            )
        return cls(observations=tuple(observations))

    def to_dict(self) -> dict[str, Any]:
        return {"observations": [item.to_dict() for item in self.observations]}


@dataclass(slots=True)
class DomainSpec:
    schema_version: str
    domain: DomainInfo
    vocabulary: DomainVocabulary
    state: DomainState
    actions: tuple[DomainAction, ...]
    decision: DomainDecision
    demo: DomainDemo

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainSpec":
        if not isinstance(payload, dict):
            raise DomainSpecValidationError(
                f"DomainSpec payload must be an object, got {type(payload)!r}."
            )

        schema_version = _require_non_empty_string(
            payload.get("schema_version", ""),
            field_name="schema_version",
        )
        if schema_version != SCHEMA_VERSION_V1:
            raise DomainSpecValidationError(
                f"schema_version must be {SCHEMA_VERSION_V1!r}, got {schema_version!r}."
            )

        domain_payload = payload.get("domain")
        if not isinstance(domain_payload, dict):
            raise DomainSpecValidationError("domain must be an object.")
        domain = DomainInfo.from_dict(domain_payload)

        vocabulary_payload = payload.get("vocabulary")
        if not isinstance(vocabulary_payload, dict):
            raise DomainSpecValidationError("vocabulary must be an object.")
        vocabulary = DomainVocabulary.from_dict(vocabulary_payload)

        state_payload = payload.get("state")
        if not isinstance(state_payload, dict):
            raise DomainSpecValidationError("state must be an object.")
        state = DomainState.from_dict(state_payload)

        actions_payload = payload.get("actions")
        if not isinstance(actions_payload, list):
            raise DomainSpecValidationError("actions must be a list.")
        if not actions_payload:
            raise DomainSpecValidationError("actions must contain at least 1 action.")

        action_map: dict[str, DomainAction] = {}
        for idx, item in enumerate(actions_payload):
            if not isinstance(item, dict):
                raise DomainSpecValidationError(f"actions[{idx}] must be an object.")
            action = DomainAction.from_dict(item, index=idx)
            if action.id in action_map:
                raise DomainSpecValidationError(f"actions has duplicate action id {action.id!r}.")
            action_map[action.id] = action

        action_types = set(vocabulary.action_types)
        for action_id in action_map:
            if action_id not in action_types:
                raise DomainSpecValidationError(
                    f"actions contains id {action_id!r} not present in vocabulary.action_types."
                )
        for action_type in vocabulary.action_types:
            if action_type not in action_map:
                raise DomainSpecValidationError(
                    f"vocabulary.action_types contains {action_type!r} without a matching actions entry."
                )

        outcome_types = set(vocabulary.outcome_types)
        for action in action_map.values():
            if action.expected_outcome_type not in outcome_types:
                raise DomainSpecValidationError(
                    "actions[{action_id}].expected_outcome_type must be in vocabulary.outcome_types.".format(
                        action_id=action.id
                    )
                )

        ordered_actions = tuple(action_map[action_type] for action_type in vocabulary.action_types)

        decision_payload = payload.get("decision")
        if not isinstance(decision_payload, dict):
            raise DomainSpecValidationError("decision must be an object.")
        decision = DomainDecision.from_dict(decision_payload)
        if decision.default_action not in action_types:
            raise DomainSpecValidationError(
                "decision.default_action must be in vocabulary.action_types."
            )

        demo_payload = payload.get("demo")
        if not isinstance(demo_payload, dict):
            raise DomainSpecValidationError("demo must be an object.")
        demo = DomainDemo.from_dict(demo_payload, domain_id=domain.id)
        observation_types = set(vocabulary.observation_types)
        for idx, item in enumerate(demo.observations):
            if item.type not in observation_types:
                raise DomainSpecValidationError(
                    "demo.observations[{idx}].type must be in vocabulary.observation_types.".format(
                        idx=idx
                    )
                )

        return cls(
            schema_version=schema_version,
            domain=domain,
            vocabulary=vocabulary,
            state=state,
            actions=ordered_actions,
            decision=decision,
            demo=demo,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "domain": self.domain.to_dict(),
            "vocabulary": self.vocabulary.to_dict(),
            "state": self.state.to_dict(),
            "actions": [item.to_dict() for item in self.actions],
            "decision": self.decision.to_dict(),
            "demo": self.demo.to_dict(),
        }


def load_domain_spec(path: str | Path) -> DomainSpec:
    file_path = Path(path)
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DomainSpecValidationError(
            f"DomainSpec file must contain an object, got {type(payload)!r}."
        )
    return DomainSpec.from_dict(payload)


def domain_id_to_slug(domain_id: str) -> str:
    _validate_domain_id(domain_id, field_name="domain_id")
    return domain_id.replace(".", "_")


def derive_package_name(domain_id: str) -> str:
    slug = domain_id_to_slug(domain_id)
    return f"{slug}_domain"


def derive_domain_pack_class_name(domain_id: str) -> str:
    slug = domain_id_to_slug(domain_id)
    words = [part for part in slug.split("_") if part]
    stem = "".join(word.capitalize() for word in words) or "Domain"
    return f"{stem}DomainPack"


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainSpecValidationError(
            f"{field_name} is required and must be a non-empty string."
        )
    return value.strip()


def _coerce_dict(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DomainSpecValidationError(f"{field_name} must be an object.")
    return dict(value)


def _validate_domain_id(value: str, *, field_name: str) -> None:
    if not _DOMAIN_ID_PATTERN.fullmatch(value):
        raise DomainSpecValidationError(
            f"{field_name} must match pattern {_DOMAIN_ID_PATTERN.pattern!r}, got {value!r}."
        )


def _validate_kind_list(
    value: Any,
    *,
    field_name: str,
    min_items: int,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DomainSpecValidationError(f"{field_name} must be a list.")

    normalized: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(value):
        token = _require_non_empty_string(item, field_name=f"{field_name}[{idx}]")
        _validate_domain_id(token, field_name=f"{field_name}[{idx}]")
        if token in seen:
            raise DomainSpecValidationError(f"{field_name} has duplicate value {token!r}.")
        seen.add(token)
        normalized.append(token)

    if len(normalized) < min_items:
        raise DomainSpecValidationError(
            f"{field_name} must contain at least {min_items} item(s)."
        )
    return tuple(normalized)
