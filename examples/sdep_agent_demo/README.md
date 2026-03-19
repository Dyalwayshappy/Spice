# SDEP Agent Demo

This example shows how Spice can route `ExecutionIntent` to an external execution-layer agent using SDEP v0.1.

Note: SDEP now defines an optional capability declaration path (`agent.describe.request` / `agent.describe.response`). This demo currently focuses on execute flow.

Files:

- `echo_agent.py`: external agent process that speaks SDEP JSON on stdin/stdout.
- `run_sdep_adapter_demo.py`: Spice-side adapter demo using `SDEPExecutor` + `SubprocessSDEPTransport`.

Run:

```bash
python3 examples/sdep_agent_demo/run_sdep_adapter_demo.py
```

Expected behavior:

- first intent succeeds (`status=success`)
- second intent intentionally fails (`status=failed`)
- agent consumes canonical `execution` payload and returns canonical `outcome` payload
- demo outcomes include explicit `outcome_type` semantic hints
- every response includes canonical `responder` identity (`id`, `name`, `version`, `role`, `implementation`)
- both results include raw SDEP request/response under `ExecutionResult.attributes["sdep"]`

Protocol spec:

- `docs/sdep_v0_1.md`
