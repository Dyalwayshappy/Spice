# Spice Decision Execution Agent Protocol (SDEP) v0.1

## 1. Purpose
SDEP defines a transport-agnostic brain-to-agent execution protocol between Spice and external execution-layer agents.

Why SDEP exists:

- Spice already has a stable decision lifecycle, but execution integrations were adapter-specific.
- SDEP provides one wire contract so external agents can integrate once and run behind Spice without custom per-agent glue.
- The same payload shape can be carried across stdin/stdout, HTTP, queue, or RPC transports.

Who implements SDEP:

- Spice-side adapters implement mapping at the runtime boundary.
- External execution-layer agents implement the protocol contract on their side.

Spice remains the decision runtime:

`Decision -> ExecutionIntent -> SDEP -> External Agent -> ExecutionResult -> Outcome`

SDEP is intended to make Spice executor integrations pluggable and ecosystem-friendly.

SDEP is **protocol-first**:

- SDEP defines the wire contract.
- Spice maps internal records (`ExecutionIntent`, `ExecutionResult`) to/from SDEP.
- External agents are not required to understand Spice internals.

SDEP is not "just another adapter":

- an adapter is a Spice-internal implementation detail.
- SDEP is an interoperability contract external agents can target directly.
- multiple adapters/transports can carry the same SDEP payload without changing agent logic.

## 2. Scope
v0.1 is intentionally narrow:

- one-shot execute request/response
- optional agent describe discovery path (`agent.describe.request` / `agent.describe.response`)
- protocol envelope with sender/responder identity
- deterministic request identity and idempotency key
- explicit success/failure signaling
- protocol-native execution payload (`execution` / `outcome`)
- JSON payload contract that works over stdin/stdout, HTTP, queue, or RPC transports

Out of scope for v0.1:

- streaming partial outputs
- async job polling protocol
- capability negotiation handshake (declaration is in scope; negotiation is reserved for future version)
- online autonomous policy mutation

## 3. Message Contract

### 3.0 Canonical Envelope (Required)
Every SDEP message uses this top-level protocol envelope:

```json
{
  "protocol": "sdep",
  "sdep_version": "0.1",
  "message_type": "execute.request|execute.response|agent.describe.request|agent.describe.response",
  "message_id": "sdep-msg-...",
  "request_id": "sdep-req-...",
  "timestamp": "2026-03-12T12:00:00+00:00",
  "metadata": {}
}
```

Envelope semantics:

1. `protocol` MUST be `sdep`.
2. `sdep_version` MUST be present and supported by the parser.
3. `message_type` MUST match the message body shape.
4. `message_id` MUST be present and uniquely identify this message.
5. `request_id` identifies the execute transaction.
6. `timestamp` SHOULD be RFC3339/ISO8601.

### 3.0.1 Identity Semantics
`sender` and `responder` use the same endpoint identity shape:

- `id`: stable logical agent identifier.
- `name`: human-readable label.
- `version`: agent release/build version.
- `vendor`: organization/publisher (recommended).
- `implementation`: concrete software implementation family.
- `role`: constrained protocol role.

Canonical identity source:

- Envelope `sender` and `responder` are the canonical identity source for SDEP messages.
- `responder` is the executor-of-record for the returned `outcome`.
- `outcome.metadata.executor` is a deprecated non-canonical fallback for transitional compatibility only.

### 3.0.2 Action Semantics
`action_type` is the canonical semantic identifier for execution actions.

Recommended naming convention:

- `domain.verb.object[.qualifier]`
- `domain` and `object` are domain-defined taxonomy terms.
- `verb` is a protocol-level semantic primitive.

Protocol verb primitive set:

- `observe`
- `create`
- `update`
- `delete`
- `notify`
- `run`
- `request`
- `approve`

`side_effect_class` vocabulary:

- `read_only`
- `state_change`
- `external_effect`

`outcome_type` base vocabulary:

- `ack`
- `state_delta`
- `artifact_bundle`
- `observation`
- `request_state`
- `approval_state`
- `error`

Domain-specific outcome types MAY be expressed as namespaced strings (for example `incident.custom_outcome`).

SDEP does not define a payload schema system. `input`, `parameters`, and `constraints` remain lightweight transport payloads.
Semantic contract fields describe intended world effect and outcome meaning, not shape validation rules.

### 3.1 Execute Request
`message_type = "execute.request"`

```json
{
  "protocol": "sdep",
  "sdep_version": "0.1",
  "message_type": "execute.request",
  "message_id": "sdep-msg-...",
  "request_id": "sdep-req-...",
  "timestamp": "2026-03-12T12:00:00+00:00",
  "sender": {
    "id": "spice.runtime",
    "name": "Spice Runtime",
    "version": "0.1",
    "vendor": "Spice",
    "implementation": "spice-runtime",
    "role": "brain"
  },
  "idempotency_key": "intent-...",
  "execution": {
    "action_type": "incident.update.feature_flag",
    "target": {
      "kind": "service",
      "id": "checkout-api"
    },
    "parameters": {},
    "input": {},
    "constraints": [],
    "success_criteria": [],
    "failure_policy": {},
    "mode": "sync",
    "dry_run": false,
    "metadata": {}
  },
  "traceability": {},
  "metadata": {}
}
```

Canonical request payload is `execution`, not Spice internal `ExecutionIntent`.

`execution.success_criteria` and `execution.failure_policy` are optional advisory hints from the decision layer.
Execution agents MAY use them, partially use them, or ignore them.

### 3.2 Execute Response
`message_type = "execute.response"`

```json
{
  "protocol": "sdep",
  "sdep_version": "0.1",
  "message_type": "execute.response",
  "message_id": "sdep-msg-...",
  "request_id": "sdep-req-...",
  "timestamp": "2026-03-12T12:00:01+00:00",
  "responder": {
    "id": "agent.echo",
    "name": "Echo Agent",
    "version": "0.1",
    "vendor": "ExampleVendor",
    "implementation": "echo-agent",
    "role": "executor"
  },
  "status": "success",
  "outcome": {
    "execution_id": "exec-...",
    "status": "success",
    "outcome_type": "state_delta",
    "output": {},
    "artifacts": [],
    "metrics": {},
    "metadata": {}
  },
  "traceability": {},
  "metadata": {}
}
```

Error response:

```json
{
  "protocol": "sdep",
  "sdep_version": "0.1",
  "message_type": "execute.response",
  "message_id": "sdep-msg-...",
  "request_id": "sdep-req-...",
  "timestamp": "2026-03-12T12:00:01+00:00",
  "responder": {
    "id": "agent.echo",
    "name": "Echo Agent",
    "version": "0.1",
    "vendor": "ExampleVendor",
    "implementation": "echo-agent",
    "role": "executor"
  },
  "status": "error",
  "outcome": {
    "execution_id": "",
    "status": "failed",
    "outcome_type": "error",
    "output": {},
    "artifacts": [],
    "metrics": {},
    "metadata": {}
  },
  "error": {
    "code": "agent.failure",
    "message": "Invalid operation",
    "retryable": false,
    "details": {}
  },
  "metadata": {}
}
```

### 3.3 Agent Describe (Capability Declaration)
Capability declaration uses a separate message family:

- `message_type = "agent.describe.request"`
- `message_type = "agent.describe.response"`

Describe is a protocol-defined discovery path. It is optional in runtime flow and is not required before every execute call.

Describe request:

```json
{
  "protocol": "sdep",
  "sdep_version": "0.1",
  "message_type": "agent.describe.request",
  "message_id": "sdep-msg-...",
  "request_id": "sdep-req-...",
  "timestamp": "2026-03-12T12:00:00+00:00",
  "sender": {
    "id": "spice.runtime",
    "name": "Spice Runtime",
    "version": "0.1",
    "vendor": "Spice",
    "implementation": "spice-runtime",
    "role": "brain"
  },
  "query": {
    "include_capabilities": true,
    "action_types": [],
    "metadata": {}
  },
  "metadata": {}
}
```

Describe response:

```json
{
  "protocol": "sdep",
  "sdep_version": "0.1",
  "message_type": "agent.describe.response",
  "message_id": "sdep-msg-...",
  "request_id": "sdep-req-...",
  "timestamp": "2026-03-12T12:00:01+00:00",
  "responder": {
    "id": "agent.echo",
    "name": "Echo Agent",
    "version": "0.1",
    "vendor": "ExampleVendor",
    "implementation": "echo-agent",
    "role": "executor"
  },
  "status": "success",
  "description": {
    "protocol_support": {
      "protocol": "sdep",
      "versions": ["0.1"],
      "metadata": {}
    },
    "capabilities": [
      {
        "action_type": "incident.update.feature_flag",
        "target_kinds": ["service"],
        "mode_support": ["sync"],
        "dry_run_supported": true,
        "side_effect_class": "state_change",
        "outcome_type": "state_delta",
        "semantic_inputs": ["target_ref", "change_reason"],
        "input_expectation": "object payload with incident context",
        "parameter_expectation": "object payload with execution knobs",
        "metadata": {}
      }
    ],
    "capability_version": "2026-03-12",
    "summary": "Example execution-layer capability declaration.",
    "metadata": {}
  },
  "metadata": {}
}
```

Capability object field levels:

- required: `action_type`, `target_kinds`, `mode_support`, `dry_run_supported`, `input_expectation`, `parameter_expectation`
- recommended: `side_effect_class`, `outcome_type`, `semantic_inputs`, capability-level `metadata` for domain hints; description-level `capability_version` and `summary`
- optional: additional agent-defined metadata keys (must not change required field semantics)

`semantic_inputs` semantics:

- semantic concept identifiers that describe what meaning-bearing inputs the action expects
- not payload schema keys, not structural validation rules

## 4. Normative Rules
1. Agent MUST echo `request_id` in the response.
2. Agent SHOULD treat `idempotency_key` as a dedupe key.
3. Request MUST include `sender.id`, `sender.name`, `sender.version`, and `sender.role`.
4. Canonical request payload is `execution`; canonical response payload is `outcome`.
5. Canonical request target MUST include `execution.target.kind` and `execution.target.id` as non-empty strings.
6. Canonical responses MUST include `responder.id`, `responder.name`, `responder.version`, `responder.role`, and `responder.implementation`.
7. Role constraints are strict: request `sender.role` MUST be `brain`, and response `responder.role` MUST be `executor`.
8. `vendor` is recommended identity metadata but not required.
9. `responder` is the executor-of-record for the returned `outcome`.
10. `action_type` is the canonical semantic action identifier; protocol semantics SHOULD follow `domain.verb.object[.qualifier]`.
11. Protocol verb semantics SHOULD use the primitive verb set; domain packs define object taxonomy.
12. `agent.describe.request` / `agent.describe.response` define a capability declaration path and are optional in runtime flow (not mandatory before each execute).
13. If an agent implements describe, response payload MUST include `description.protocol_support` and `description.capabilities`.
14. Each capability declaration MUST include: `action_type`, `target_kinds`, `mode_support`, `dry_run_supported`, `input_expectation`, and `parameter_expectation`.
15. Capability declarations SHOULD include semantic contract fields: `side_effect_class`, `outcome_type`, and `semantic_inputs`.
16. Outcome semantics SHOULD include explicit `outcome.outcome_type`; metadata fallback remains transitional compatibility behavior.
17. Capability declaration is declarative, not negotiative, in this version.
18. `execution.success_criteria` and `execution.failure_policy` are optional advisory hints; agents are not required to implement them as strict semantics.
19. `traceability` is optional and non-normative. It MAY contain Spice-specific metadata.
20. Spice adapter MUST preserve raw SDEP request/response in `ExecutionResult.attributes["sdep"]`.
21. Unsupported/invalid requests SHOULD return `status="error"` with a structured `error`.
22. Transport failures (timeout, non-JSON, empty payload) are mapped by the Spice adapter to failed `ExecutionResult`.
23. Canonical message envelope validation is strict: `protocol=sdep`, supported `sdep_version`, expected `message_type`, and non-empty `message_id`.

## 5. Minimal Conformance
An implementation can claim SDEP v0.1 conformance when it satisfies:

1. Envelope fields are present and valid (`protocol=sdep`, `sdep_version`, `message_type`, `message_id`, `request_id`).
2. Execute requests use canonical `execution` payload with required target fields (`target.kind`, `target.id`).
3. Execute requests include sender identity with required core fields and role (`brain`).
4. Execute responses use canonical `outcome` payload and include required responder identity fields, including role (`executor`) and `implementation`.
5. Envelope identity (`sender`/`responder`) is treated as canonical identity source.
6. Error responses include a structured `error` object.
7. Legacy fields (`intent`, `execution_result`) are optional compatibility additions only, not canonical contract requirements.
8. `outcome.metadata.executor` is a deprecated non-canonical fallback and MUST NOT be treated as the primary identity source.
9. If describe is implemented, the agent returns canonical `description` payload with protocol support declaration and capability entries containing required fields.
10. Action semantics are conveyed by canonical `action_type`; semantic fields (`side_effect_class`, `outcome_type`, `semantic_inputs`) provide orthogonal declarative meaning without schema enforcement.

## 5.1 Deprecation Note
- Legacy `intent` and `execution_result` are transitional compatibility paths.
- Canonical SDEP v0.1 contract is `execution` / `outcome`.
- New integrations MUST NOT depend on legacy fields.
- `outcome.metadata.executor` is transitional compatibility metadata and non-canonical.
- Spice may remove legacy compatibility paths in a future version once migration is complete.

## 6. Status Mapping Into Spice
SDEP status -> `ExecutionResult.status`:

- `success|applied|ok|completed` -> `success`
- `failed|rejected|error|timeout` -> `failed`
- anything else -> `unknown`

## 7. Reference Adapter (v0.1)
Spice ships:

- `SDEPExecutor` (Executor adapter)
- `SubprocessSDEPTransport` (stdin/stdout JSON transport)
- optional `agent.describe` call path via `SDEPExecutor.describe(...)`

Code:

- `spice/executors/sdep.py`

This lets any external agent integrate by speaking SDEP JSON.

## 8. Example Agent
Example execution-layer agent implementation:

- `examples/sdep_agent_demo/echo_agent.py`

It reads one SDEP request from stdin and writes one SDEP response to stdout.

## 9. Spice Mapping Appendix (Informative)
Spice internal records are mapped into SDEP; they are not equivalent schemas.

### 9.1 `ExecutionIntent -> execute.request.execution`
Suggested mapping:

- `intent.operation.name` -> `execution.action_type`
- `execution.action_type` SHOULD follow `domain.verb.object[.qualifier]` convention
- `intent.target` -> `execution.target`
- `intent.parameters` -> `execution.parameters`
- `intent.input_payload` -> `execution.input`
- `intent.constraints` -> `execution.constraints`
- `intent.success_criteria` -> `execution.success_criteria`
- `intent.failure_policy` -> `execution.failure_policy`
- `intent.operation.mode` -> `execution.mode`
- `intent.operation.dry_run` -> `execution.dry_run`

Spice-specific references (intent id, provenance, refs, objective) SHOULD go under optional `traceability.spice`.

### 9.2 `execute.response.outcome -> ExecutionResult`
Suggested mapping:

- `outcome.execution_id` -> `ExecutionResult.id` (or fallback id generation)
- `status`/`outcome.status` -> `ExecutionResult.status` mapping
- `outcome.outcome_type` -> `ExecutionResult.result_type` preferred semantic hint
- `outcome.output` -> `ExecutionResult.output`
- `responder.implementation` (or `responder.name`) -> `ExecutionResult.executor` (canonical source)
- `outcome.metadata.result_type` / `outcome.metadata.executor` -> deprecated fallback only when canonical fields are unavailable
- protocol errors -> `ExecutionResult.error`
- raw wire request/response -> `ExecutionResult.attributes["sdep"]`

### 9.3 `agent.describe.response.description` (Discovery / Routing)
Suggested usage:

- `description.protocol_support` -> protocol compatibility checks
- `description.capabilities[].action_type` -> action routing/matching
- `description.capabilities[].target_kinds` -> target compatibility filtering
- `description.capabilities[].side_effect_class` -> policy/risk class of world effect
- `description.capabilities[].outcome_type` -> expected semantic outcome type
- `description.capabilities[].semantic_inputs` -> expected semantic input concepts
- `description.capabilities[].mode_support` / `dry_run_supported` -> execution-shape compatibility
- `description.capabilities[].input_expectation` / `parameter_expectation` -> payload contract guidance

## 10. Legacy Compatibility (Deprecated)
`intent` and `execution_result` payloads may appear in transitional integrations.

- They are **legacy/deprecated**.
- They are **not canonical SDEP v0.1 shape**.
- New integrations SHOULD use `execution` and `outcome`.

## 11. Versioning
`sdep_version` is required in every message.

v0.1 compatibility expectation:

- additive fields are allowed
- existing required fields remain stable
- breaking changes require a new protocol version
