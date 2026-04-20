# SDEP Quick Start

SDEP is the execution boundary between Spice and external agents.

```text
Spice decides.
Executors execute.
SDEP carries the execution request and the structured outcome.
```

SDEP is not an agent framework, memory system, or workflow engine. It is the
wire contract for handing a selected decision to an executor and receiving the
result back.

## Minimal Executor Contract

A minimal SDEP executor must:

1. Read one `execute.request`.
2. Execute the requested action, or reject it with a structured error.
3. Return one `execute.response`.
4. Preserve the original `request_id`.
5. Keep protocol status separate from task status.
6. Optionally support `agent.describe.request` for capability discovery.

For stdin/stdout executors, the shape is:

```text
stdin:  SDEP execute.request JSON
stdout: SDEP execute.response JSON
```

## Status Semantics

SDEP has two status layers.

```json
{
  "status": "success",
  "outcome": {
    "status": "failed"
  }
}
```

This means:

```text
The SDEP exchange succeeded.
The delegated task failed.
```

Use `response.status = "error"` for protocol, wrapper, transport, or validation
failures:

```json
{
  "status": "error",
  "outcome": {
    "status": "failed",
    "outcome_type": "error"
  },
  "error": {
    "code": "executor.timeout",
    "message": "Executor timed out.",
    "retryable": true,
    "details": {}
  }
}
```

## Protocol Assets

Read the protocol:

```text
docs/sdep_v0_1.md
```

Use the JSON Schemas:

```text
schemas/sdep/v0.1/
```

Start from example payloads:

```text
examples/sdep_payloads/v0.1/
```

Important examples:

- `execute.request.json`
- `execute.response.success.json`
- `execute.response.task_failed.json`
- `execute.response.protocol_error.json`
- `agent.describe.request.json`
- `agent.describe.response.json`

## Capability Discovery

Executors may implement `agent.describe.request`.

The response declares what the executor supports:

- `action_type`
- `target_kinds`
- `mode_support`
- `side_effect_class`
- `outcome_type`
- input / parameter expectations

This is declaration, not negotiation. An executor can still reject unsupported
requests at execution time.

## Hermes Wrapper Reference

The Hermes SDEP wrapper is a working reference implementation:

```text
spice-hermes-bridge/spice_hermes_bridge/integrations/hermes_sdep_agent.py
spice-hermes-bridge/spice_hermes_bridge/integrations/hermes_sdep_native.py
```

It exposes Hermes/Codex through SDEP:

```text
SDEP execute.request
-> Hermes SDEP wrapper
-> Hermes/Codex native execution
-> SDEP execute.response
```

SDEP is not bound to Hermes. Any executor can implement the same boundary.

## Implementation Checklist

For a first SDEP-compatible executor:

- accept JSON input
- validate `protocol`, `sdep_version`, and `message_type`
- preserve `request_id`
- read `execution.action_type`
- read `execution.target`
- execute or reject the request
- return canonical `outcome`
- return structured `error` on protocol failure
- do not return free-form prose as the response

If your executor is not SDEP-native, wrap it:

```text
SDEP request -> wrapper -> native executor -> wrapper -> SDEP response
```
