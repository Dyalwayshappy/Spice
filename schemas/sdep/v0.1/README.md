# SDEP v0.1 JSON Schemas

These schemas define the public wire contract for the Spice Decision Execution
Protocol (SDEP) v0.1.

Files:

- `execute.request.schema.json`
- `execute.response.schema.json`
- `agent.describe.request.schema.json`
- `agent.describe.response.schema.json`
- `common.schema.json`

The schemas intentionally validate the protocol envelope, identity, execution
handoff, outcome, error, and capability declaration shape. Domain-specific
payloads such as `execution.parameters`, `execution.input`, `metadata`, and
`traceability` remain open objects.

Important status split:

- `response.status` describes protocol / wrapper transaction status.
- `outcome.status` describes task execution status.

For example, `response.status = "success"` with `outcome.status = "failed"`
means the SDEP exchange succeeded but the delegated task failed.
