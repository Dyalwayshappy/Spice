from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from spice.protocols.base import utc_now


SDEP_PROTOCOL = "sdep"
SDEP_VERSION = "0.1"
SDEP_EXECUTE_REQUEST = "execute.request"
SDEP_EXECUTE_RESPONSE = "execute.response"
SDEP_AGENT_DESCRIBE_REQUEST = "agent.describe.request"
SDEP_AGENT_DESCRIBE_RESPONSE = "agent.describe.response"
SDEP_SUPPORTED_VERSIONS = (SDEP_VERSION,)
SDEP_ROLE_BRAIN = "brain"
SDEP_ROLE_EXECUTOR = "executor"
SDEP_ACTION_VERB_PRIMITIVES = (
    "observe",
    "create",
    "update",
    "delete",
    "notify",
    "run",
    "request",
    "approve",
)
SDEP_SIDE_EFFECT_CLASSES = (
    "read_only",
    "state_change",
    "external_effect",
)
SDEP_OUTCOME_TYPES = (
    "ack",
    "state_delta",
    "artifact_bundle",
    "observation",
    "request_state",
    "approval_state",
    "error",
)


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return []


def _require_non_empty_string(value: Any, *, field_name: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{field_name} is required and must be a non-empty string.")
    return value.strip()


def _require_non_empty_string_list(
    value: Any,
    *,
    field_name: str,
    context: str,
    min_items: int = 0,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{context}.{field_name} must be a list of non-empty strings.")

    normalized: list[str] = []
    for idx, item in enumerate(value):
        normalized.append(
            _require_non_empty_string(
                item,
                field_name=f"{field_name}[{idx}]",
                context=context,
            )
        )

    if len(normalized) < min_items:
        raise ValueError(f"{context}.{field_name} must contain at least {min_items} item(s).")
    return normalized


def _require_bool(value: Any, *, field_name: str, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context}.{field_name} is required and must be a boolean.")
    return value


def _validate_side_effect_class(value: str) -> str:
    if not value:
        return value
    if value not in SDEP_SIDE_EFFECT_CLASSES:
        allowed = ", ".join(SDEP_SIDE_EFFECT_CLASSES)
        raise ValueError(
            f"description.capability.side_effect_class must be one of [{allowed}], got {value!r}."
        )
    return value


def _validate_outcome_type(value: str, *, context: str, field_name: str) -> str:
    if not value:
        return value
    if value in SDEP_OUTCOME_TYPES:
        return value
    # Domain-extensible semantics: allow namespaced custom outcome types.
    if "." in value:
        return value
    allowed = ", ".join(SDEP_OUTCOME_TYPES)
    raise ValueError(
        f"{context}.{field_name} must be one of [{allowed}] or namespaced custom type, got {value!r}."
    )


def _validate_envelope(
    *,
    context: str,
    protocol: str,
    sdep_version: str,
    message_type: str,
    expected_message_type: str,
    message_id: str,
) -> None:
    if protocol != SDEP_PROTOCOL:
        raise ValueError(f"{context}.protocol must be {SDEP_PROTOCOL!r}.")

    if sdep_version not in SDEP_SUPPORTED_VERSIONS:
        supported = ", ".join(SDEP_SUPPORTED_VERSIONS)
        raise ValueError(
            f"{context}.sdep_version must be one of [{supported}], got {sdep_version!r}."
        )

    if message_type != expected_message_type:
        raise ValueError(
            f"{context}.message_type must be {expected_message_type!r}, got {message_type!r}."
        )

    _require_non_empty_string(message_id, field_name="message_id", context=context)


@dataclass(slots=True)
class SDEPEndpointIdentity:
    # stable logical agent identifier
    id: str
    # human-readable label
    name: str
    # agent release/build version
    version: str
    # organization/publisher (recommended)
    vendor: str = ""
    # concrete software implementation family
    implementation: str = ""
    # constrained protocol role
    role: str = ""

    def validate(
        self,
        *,
        context: str,
        require_core: bool = False,
        require_role: bool = False,
        require_implementation: bool = False,
        expected_role: str | None = None,
    ) -> None:
        if require_core:
            _require_non_empty_string(self.id, field_name="id", context=context)
            _require_non_empty_string(self.name, field_name="name", context=context)
            _require_non_empty_string(self.version, field_name="version", context=context)
        if require_role:
            _require_non_empty_string(self.role, field_name="role", context=context)
        if expected_role is not None and self.role != expected_role:
            raise ValueError(f"{context}.role must be {expected_role!r}, got {self.role!r}.")
        if require_implementation:
            _require_non_empty_string(
                self.implementation,
                field_name="implementation",
                context=context,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "vendor": self.vendor,
            "implementation": self.implementation,
            "role": self.role,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        context: str = "endpoint",
        require_core: bool = False,
    ) -> "SDEPEndpointIdentity":
        identity = cls(
            id=str(payload.get("id", "")),
            name=str(payload.get("name", "")),
            version=str(payload.get("version", "")),
            vendor=str(payload.get("vendor", "")),
            implementation=str(payload.get("implementation", "")),
            role=str(payload.get("role", "")),
        )
        identity.validate(context=context, require_core=require_core)
        return identity


@dataclass(slots=True)
class SDEPExecutionPayload:
    action_type: str
    target: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    success_criteria: list[dict[str, Any]] = field(default_factory=list)
    failure_policy: dict[str, Any] = field(default_factory=dict)
    mode: str = "sync"
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _require_non_empty_string(self.action_type, field_name="action_type", context="execution")
        if not isinstance(self.target, dict):
            raise ValueError("execution.target must be an object.")
        _require_non_empty_string(self.target.get("kind"), field_name="target.kind", context="execution")
        _require_non_empty_string(self.target.get("id"), field_name="target.id", context="execution")
        if not isinstance(self.success_criteria, list):
            raise ValueError("execution.success_criteria must be a list when provided.")
        if not isinstance(self.failure_policy, dict):
            raise ValueError("execution.failure_policy must be an object when provided.")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "action_type": self.action_type,
            "target": dict(self.target),
            "parameters": dict(self.parameters),
            "input": dict(self.input),
            "constraints": list(self.constraints),
            "success_criteria": list(self.success_criteria),
            "failure_policy": dict(self.failure_policy),
            "mode": self.mode,
            "dry_run": self.dry_run,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPExecutionPayload":
        execution = cls(
            action_type=str(payload.get("action_type", "")),
            target=_coerce_dict(payload.get("target")),
            parameters=_coerce_dict(payload.get("parameters")),
            input=_coerce_dict(payload.get("input")),
            constraints=_coerce_list(payload.get("constraints")),
            success_criteria=_coerce_list(payload.get("success_criteria")),
            failure_policy=_coerce_dict(payload.get("failure_policy")),
            mode=str(payload.get("mode", "sync")),
            dry_run=bool(payload.get("dry_run", False)),
            metadata=_coerce_dict(payload.get("metadata")),
        )
        execution.validate()
        return execution


@dataclass(slots=True)
class SDEPExecutionOutcome:
    execution_id: str = ""
    status: str = "unknown"
    outcome_type: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _validate_outcome_type(
            self.outcome_type,
            context="outcome",
            field_name="outcome_type",
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "execution_id": self.execution_id,
            "status": self.status,
            "outcome_type": self.outcome_type,
            "output": dict(self.output),
            "artifacts": list(self.artifacts),
            "metrics": dict(self.metrics),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPExecutionOutcome":
        outcome = cls(
            execution_id=str(payload.get("execution_id", "")),
            status=str(payload.get("status", "unknown")),
            outcome_type=str(payload.get("outcome_type", "")),
            output=dict(payload.get("output", {})),
            artifacts=list(payload.get("artifacts", [])),
            metrics=dict(payload.get("metrics", {})),
            metadata=dict(payload.get("metadata", {})),
        )
        outcome.validate()
        return outcome


@dataclass(slots=True)
class SDEPError:
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPError":
        return cls(
            code=str(payload.get("code", "sdep.error")),
            message=str(payload.get("message", "")),
            retryable=bool(payload.get("retryable", False)),
            details=dict(payload.get("details", {})),
        )


@dataclass(slots=True)
class SDEPDescribeQuery:
    include_capabilities: bool = True
    action_types: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _require_bool(
            self.include_capabilities,
            field_name="include_capabilities",
            context="describe.query",
        )
        _require_non_empty_string_list(
            self.action_types,
            field_name="action_types",
            context="describe.query",
            min_items=0,
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "include_capabilities": self.include_capabilities,
            "action_types": list(self.action_types),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPDescribeQuery":
        raw_include = payload.get("include_capabilities", True)
        query = cls(
            include_capabilities=raw_include if isinstance(raw_include, bool) else raw_include,
            action_types=_coerce_list(payload.get("action_types")),
            metadata=_coerce_dict(payload.get("metadata")),
        )
        query.validate()
        return query


@dataclass(slots=True)
class SDEPProtocolSupport:
    protocol: str = SDEP_PROTOCOL
    versions: list[str] = field(default_factory=lambda: [SDEP_VERSION])
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.protocol != SDEP_PROTOCOL:
            raise ValueError(
                f"description.protocol_support.protocol must be {SDEP_PROTOCOL!r}, got {self.protocol!r}."
            )
        _require_non_empty_string_list(
            self.versions,
            field_name="versions",
            context="description.protocol_support",
            min_items=1,
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "protocol": self.protocol,
            "versions": list(self.versions),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPProtocolSupport":
        protocol_support = cls(
            protocol=str(payload.get("protocol", "")),
            versions=_coerce_list(payload.get("versions")),
            metadata=_coerce_dict(payload.get("metadata")),
        )
        protocol_support.validate()
        return protocol_support


@dataclass(slots=True)
class SDEPActionCapability:
    action_type: str
    target_kinds: list[str] = field(default_factory=list)
    mode_support: list[str] = field(default_factory=lambda: ["sync"])
    dry_run_supported: bool = False
    side_effect_class: str = ""
    outcome_type: str = ""
    semantic_inputs: list[str] = field(default_factory=list)
    input_expectation: str = "unspecified"
    parameter_expectation: str = "unspecified"
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _require_non_empty_string(
            self.action_type,
            field_name="action_type",
            context="description.capability",
        )
        _require_non_empty_string_list(
            self.target_kinds,
            field_name="target_kinds",
            context="description.capability",
            min_items=1,
        )
        _require_non_empty_string_list(
            self.mode_support,
            field_name="mode_support",
            context="description.capability",
            min_items=1,
        )
        _require_bool(
            self.dry_run_supported,
            field_name="dry_run_supported",
            context="description.capability",
        )
        _validate_side_effect_class(self.side_effect_class)
        _validate_outcome_type(
            self.outcome_type,
            context="description.capability",
            field_name="outcome_type",
        )
        _require_non_empty_string_list(
            self.semantic_inputs,
            field_name="semantic_inputs",
            context="description.capability",
            min_items=0,
        )
        _require_non_empty_string(
            self.input_expectation,
            field_name="input_expectation",
            context="description.capability",
        )
        _require_non_empty_string(
            self.parameter_expectation,
            field_name="parameter_expectation",
            context="description.capability",
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "action_type": self.action_type,
            "target_kinds": list(self.target_kinds),
            "mode_support": list(self.mode_support),
            "dry_run_supported": self.dry_run_supported,
            "side_effect_class": self.side_effect_class,
            "outcome_type": self.outcome_type,
            "semantic_inputs": list(self.semantic_inputs),
            "input_expectation": self.input_expectation,
            "parameter_expectation": self.parameter_expectation,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPActionCapability":
        raw_dry_run = payload.get("dry_run_supported", False)
        raw_semantic_inputs = payload.get("semantic_inputs", [])
        capability = cls(
            action_type=str(payload.get("action_type", "")),
            target_kinds=_coerce_list(payload.get("target_kinds")),
            mode_support=_coerce_list(payload.get("mode_support")),
            dry_run_supported=raw_dry_run,
            side_effect_class=str(payload.get("side_effect_class", "")),
            outcome_type=str(payload.get("outcome_type", "")),
            semantic_inputs=raw_semantic_inputs,
            input_expectation=str(payload.get("input_expectation", "")),
            parameter_expectation=str(payload.get("parameter_expectation", "")),
            metadata=_coerce_dict(payload.get("metadata")),
        )
        capability.validate()
        return capability


@dataclass(slots=True)
class SDEPAgentDescription:
    protocol_support: SDEPProtocolSupport
    capabilities: list[SDEPActionCapability] = field(default_factory=list)
    capability_version: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        self.protocol_support.validate()
        if not isinstance(self.capabilities, list):
            raise ValueError("description.capabilities must be a list.")
        for idx, capability in enumerate(self.capabilities):
            if not isinstance(capability, SDEPActionCapability):
                raise ValueError(
                    f"description.capabilities[{idx}] must be an SDEPActionCapability object."
                )
            capability.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        payload: dict[str, Any] = {
            "protocol_support": self.protocol_support.to_dict(),
            "capabilities": [capability.to_dict() for capability in self.capabilities],
            "metadata": dict(self.metadata),
        }
        if self.capability_version:
            payload["capability_version"] = self.capability_version
        if self.summary:
            payload["summary"] = self.summary
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPAgentDescription":
        protocol_support_payload = payload.get("protocol_support")
        if not isinstance(protocol_support_payload, dict):
            raise ValueError("description.protocol_support is required and must be an object.")

        capabilities_payload = payload.get("capabilities")
        if not isinstance(capabilities_payload, list):
            raise ValueError("description.capabilities is required and must be a list.")

        capabilities: list[SDEPActionCapability] = []
        for idx, item in enumerate(capabilities_payload):
            if not isinstance(item, dict):
                raise ValueError(f"description.capabilities[{idx}] must be an object.")
            capabilities.append(SDEPActionCapability.from_dict(item))

        description = cls(
            protocol_support=SDEPProtocolSupport.from_dict(protocol_support_payload),
            capabilities=capabilities,
            capability_version=str(payload.get("capability_version", "")),
            summary=str(payload.get("summary", "")),
            metadata=_coerce_dict(payload.get("metadata")),
        )
        description.validate()
        return description


def _default_agent_description() -> SDEPAgentDescription:
    return SDEPAgentDescription(
        protocol_support=SDEPProtocolSupport(protocol=SDEP_PROTOCOL, versions=[SDEP_VERSION]),
        capabilities=[],
    )


@dataclass(slots=True)
class SDEPDescribeRequest:
    request_id: str
    sender: SDEPEndpointIdentity
    query: SDEPDescribeQuery = field(default_factory=SDEPDescribeQuery)
    protocol: str = SDEP_PROTOCOL
    message_id: str = field(default_factory=lambda: f"sdep-msg-{uuid4().hex}")
    timestamp: datetime = field(default_factory=utc_now)
    sdep_version: str = SDEP_VERSION
    message_type: str = SDEP_AGENT_DESCRIBE_REQUEST
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _validate_envelope(
            context="agent.describe.request",
            protocol=self.protocol,
            sdep_version=self.sdep_version,
            message_type=self.message_type,
            expected_message_type=SDEP_AGENT_DESCRIBE_REQUEST,
            message_id=self.message_id,
        )
        _require_non_empty_string(
            self.request_id,
            field_name="request_id",
            context="agent.describe.request",
        )
        self.sender.validate(
            context="agent.describe.request.sender",
            require_core=True,
            require_role=True,
            expected_role=SDEP_ROLE_BRAIN,
        )
        self.query.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "protocol": self.protocol,
            "sdep_version": self.sdep_version,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "sender": self.sender.to_dict(),
            "query": self.query.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPDescribeRequest":
        sender_payload = payload.get("sender")
        if not isinstance(sender_payload, dict):
            raise ValueError("agent.describe.request.sender is required and must be an object.")

        query_payload = payload.get("query")
        if query_payload is not None and not isinstance(query_payload, dict):
            raise ValueError("agent.describe.request.query must be an object when provided.")

        request = cls(
            request_id=str(payload.get("request_id", "")),
            sender=SDEPEndpointIdentity.from_dict(
                sender_payload,
                context="agent.describe.request.sender",
                require_core=True,
            ),
            query=SDEPDescribeQuery.from_dict(query_payload) if isinstance(query_payload, dict) else SDEPDescribeQuery(),
            protocol=str(payload.get("protocol", "")),
            message_id=str(payload.get("message_id", "")),
            timestamp=_parse_timestamp(payload.get("timestamp")),
            sdep_version=str(payload.get("sdep_version", "")),
            message_type=str(payload.get("message_type", "")),
            metadata=_coerce_dict(payload.get("metadata")),
        )
        request.validate()
        return request


@dataclass(slots=True)
class SDEPDescribeResponse:
    request_id: str
    status: str
    responder: SDEPEndpointIdentity
    description: SDEPAgentDescription = field(default_factory=_default_agent_description)
    error: SDEPError | None = None
    protocol: str = SDEP_PROTOCOL
    message_id: str = field(default_factory=lambda: f"sdep-msg-{uuid4().hex}")
    timestamp: datetime = field(default_factory=utc_now)
    sdep_version: str = SDEP_VERSION
    message_type: str = SDEP_AGENT_DESCRIBE_RESPONSE
    traceability: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _validate_envelope(
            context="agent.describe.response",
            protocol=self.protocol,
            sdep_version=self.sdep_version,
            message_type=self.message_type,
            expected_message_type=SDEP_AGENT_DESCRIBE_RESPONSE,
            message_id=self.message_id,
        )
        _require_non_empty_string(
            self.request_id,
            field_name="request_id",
            context="agent.describe.response",
        )
        _require_non_empty_string(
            self.status,
            field_name="status",
            context="agent.describe.response",
        )
        self.responder.validate(
            context="agent.describe.response.responder",
            require_core=True,
            require_role=True,
            require_implementation=True,
            expected_role=SDEP_ROLE_EXECUTOR,
        )
        self.description.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        payload: dict[str, Any] = {
            "protocol": self.protocol,
            "sdep_version": self.sdep_version,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "responder": self.responder.to_dict(),
            "status": self.status,
            "description": self.description.to_dict(),
            "metadata": dict(self.metadata),
        }
        if self.traceability:
            payload["traceability"] = dict(self.traceability)
        if self.error is not None:
            payload["error"] = self.error.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPDescribeResponse":
        description_payload = payload.get("description")
        if not isinstance(description_payload, dict):
            raise ValueError("agent.describe.response.description is required and must be an object.")

        responder_payload = payload.get("responder")
        if not isinstance(responder_payload, dict):
            raise ValueError("agent.describe.response.responder is required and must be an object.")

        error_payload = payload.get("error")
        error = None
        if isinstance(error_payload, dict):
            error = SDEPError.from_dict(error_payload)

        response = cls(
            request_id=str(payload.get("request_id", "")),
            status=str(payload.get("status", "")),
            responder=SDEPEndpointIdentity.from_dict(
                responder_payload,
                context="agent.describe.response.responder",
                require_core=True,
            ),
            description=SDEPAgentDescription.from_dict(description_payload),
            error=error,
            protocol=str(payload.get("protocol", "")),
            message_id=str(payload.get("message_id", "")),
            timestamp=_parse_timestamp(payload.get("timestamp")),
            sdep_version=str(payload.get("sdep_version", "")),
            message_type=str(payload.get("message_type", "")),
            traceability=_coerce_dict(payload.get("traceability")),
            metadata=_coerce_dict(payload.get("metadata")),
        )
        response.validate()
        return response


@dataclass(slots=True)
class SDEPExecuteRequest:
    request_id: str
    execution: SDEPExecutionPayload
    sender: SDEPEndpointIdentity
    protocol: str = SDEP_PROTOCOL
    message_id: str = field(default_factory=lambda: f"sdep-msg-{uuid4().hex}")
    timestamp: datetime = field(default_factory=utc_now)
    sdep_version: str = SDEP_VERSION
    message_type: str = SDEP_EXECUTE_REQUEST
    idempotency_key: str = ""
    traceability: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _validate_envelope(
            context="execute.request",
            protocol=self.protocol,
            sdep_version=self.sdep_version,
            message_type=self.message_type,
            expected_message_type=SDEP_EXECUTE_REQUEST,
            message_id=self.message_id,
        )
        _require_non_empty_string(self.request_id, field_name="request_id", context="execute.request")
        self.sender.validate(
            context="execute.request.sender",
            require_core=True,
            require_role=True,
            expected_role=SDEP_ROLE_BRAIN,
        )
        self.execution.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        payload: dict[str, Any] = {
            "protocol": self.protocol,
            "sdep_version": self.sdep_version,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "sender": self.sender.to_dict(),
            "idempotency_key": self.idempotency_key,
            "execution": self.execution.to_dict(),
            "metadata": dict(self.metadata),
        }
        if self.traceability:
            payload["traceability"] = dict(self.traceability)

        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPExecuteRequest":
        execution_payload = payload.get("execution")
        if not isinstance(execution_payload, dict):
            raise ValueError("execute.request.execution is required and must be an object.")

        sender_payload = payload.get("sender")
        if not isinstance(sender_payload, dict):
            raise ValueError("execute.request.sender is required and must be an object.")

        # Deprecated legacy field "intent" is intentionally ignored at the protocol boundary.

        request = cls(
            request_id=str(payload.get("request_id", "")),
            execution=SDEPExecutionPayload.from_dict(execution_payload),
            sender=SDEPEndpointIdentity.from_dict(
                sender_payload,
                context="execute.request.sender",
                require_core=True,
            ),
            protocol=str(payload.get("protocol", "")),
            message_id=str(payload.get("message_id", "")),
            timestamp=_parse_timestamp(payload.get("timestamp")),
            sdep_version=str(payload.get("sdep_version", "")),
            message_type=str(payload.get("message_type", "")),
            idempotency_key=str(payload.get("idempotency_key", "")),
            traceability=_coerce_dict(payload.get("traceability")),
            metadata=_coerce_dict(payload.get("metadata")),
        )
        request.validate()
        return request


@dataclass(slots=True)
class SDEPExecuteResponse:
    request_id: str
    status: str
    responder: SDEPEndpointIdentity
    outcome: SDEPExecutionOutcome = field(default_factory=SDEPExecutionOutcome)
    execution_result: dict[str, Any] = field(default_factory=dict)
    error: SDEPError | None = None
    protocol: str = SDEP_PROTOCOL
    message_id: str = field(default_factory=lambda: f"sdep-msg-{uuid4().hex}")
    timestamp: datetime = field(default_factory=utc_now)
    sdep_version: str = SDEP_VERSION
    message_type: str = SDEP_EXECUTE_RESPONSE
    traceability: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _validate_envelope(
            context="execute.response",
            protocol=self.protocol,
            sdep_version=self.sdep_version,
            message_type=self.message_type,
            expected_message_type=SDEP_EXECUTE_RESPONSE,
            message_id=self.message_id,
        )
        _require_non_empty_string(self.request_id, field_name="request_id", context="execute.response")
        _require_non_empty_string(self.status, field_name="status", context="execute.response")
        self.responder.validate(
            context="execute.response.responder",
            require_core=True,
            require_role=True,
            require_implementation=True,
            expected_role=SDEP_ROLE_EXECUTOR,
        )

    def to_dict(self, *, include_legacy_execution_result: bool = False) -> dict[str, Any]:
        self.validate()
        payload: dict[str, Any] = {
            "protocol": self.protocol,
            "sdep_version": self.sdep_version,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "responder": self.responder.to_dict(),
            "status": self.status,
            "outcome": self.outcome.to_dict(),
            "metadata": dict(self.metadata),
        }
        if self.traceability:
            payload["traceability"] = dict(self.traceability)
        if self.error is not None:
            payload["error"] = self.error.to_dict()

        # Deprecated compatibility path for legacy integrations.
        if include_legacy_execution_result:
            payload["execution_result"] = (
                dict(self.execution_result)
                if self.execution_result
                else _outcome_to_legacy_execution_result(self.outcome)
            )

        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SDEPExecuteResponse":
        request_id = _require_non_empty_string(
            payload.get("request_id", ""),
            field_name="request_id",
            context="execute.response",
        )
        status = _require_non_empty_string(
            payload.get("status", ""),
            field_name="status",
            context="execute.response",
        )

        error_payload = payload.get("error")
        error = None
        if isinstance(error_payload, dict):
            error = SDEPError.from_dict(error_payload)

        outcome_payload = payload.get("outcome")
        legacy_payload = payload.get("execution_result")
        legacy_result = _coerce_dict(legacy_payload)
        has_canonical_outcome = isinstance(outcome_payload, dict)
        if has_canonical_outcome:
            outcome = SDEPExecutionOutcome.from_dict(outcome_payload)
        elif legacy_result:
            outcome = _legacy_execution_result_to_outcome(
                legacy_result,
                status=status,
            )
        else:
            raise ValueError(
                "execute.response must include outcome (canonical) or execution_result (legacy)."
            )

        responder_payload = payload.get("responder")
        if not isinstance(responder_payload, dict):
            raise ValueError("execute.response.responder is required and must be an object.")
        responder = SDEPEndpointIdentity.from_dict(
            responder_payload,
            context="execute.response.responder",
            require_core=True,
        )

        response = cls(
            request_id=request_id,
            status=status,
            responder=responder,
            outcome=outcome,
            # Deprecated compatibility path: legacy execution_result may still be present.
            execution_result=legacy_result
            if legacy_result
            else _outcome_to_legacy_execution_result(outcome),
            error=error,
            protocol=str(payload.get("protocol", "")),
            message_id=str(payload.get("message_id", "")),
            timestamp=_parse_timestamp(payload.get("timestamp")),
            sdep_version=str(payload.get("sdep_version", "")),
            message_type=str(payload.get("message_type", "")),
            traceability=_coerce_dict(payload.get("traceability")),
            metadata=_coerce_dict(payload.get("metadata")),
        )
        response.validate()
        return response


def _outcome_to_legacy_execution_result(outcome: SDEPExecutionOutcome) -> dict[str, Any]:
    result_type = str(
        outcome.outcome_type
        or outcome.metadata.get("result_type")
        or "sdep.execute_result"
    )
    executor = str(outcome.metadata.get("executor", "sdep-agent"))
    return {
        "id": outcome.execution_id or f"result-{uuid4().hex}",
        "result_type": result_type,
        "executor": executor,
        "output": dict(outcome.output),
        "artifacts": list(outcome.artifacts),
        "metrics": dict(outcome.metrics),
    }


def _legacy_execution_result_to_outcome(
    payload: dict[str, Any],
    *,
    status: str,
) -> SDEPExecutionOutcome:
    legacy_result_type = str(payload.get("result_type", "sdep.execute_result"))
    return SDEPExecutionOutcome(
        execution_id=str(payload.get("id", "")),
        status=str(status or "unknown"),
        outcome_type=legacy_result_type,
        output=dict(payload.get("output", {})),
        artifacts=list(payload.get("artifacts", [])),
        metrics=dict(payload.get("metrics", {})),
        metadata={
            "result_type": legacy_result_type,
            "executor": str(payload.get("executor", "")),
        },
    )


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return utc_now()
    return utc_now()
