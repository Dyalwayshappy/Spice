# SDEP Wrapper Template (Minimal v1)

This template is a thin bridge for non-SDEP external agents.

It exists for this use case:

`SDEP request -> wrapper -> native agent call -> wrapper -> SDEP response`

## Why This Exists

`SDEPExecutor` expects an agent that speaks SDEP request/response JSON.
Many real external agents do not speak SDEP natively (CLI JSON, SDK/API, custom payloads).

This wrapper translates between:

- canonical SDEP wire shape (`execute.request`, `agent.describe.request`)
- a simple native JSON subprocess contract

## What This Is Not

- not a runtime redesign
- not a protocol redesign
- not multi-agent routing
- not a connector platform

## Files

- `wrapper_main.py`: SDEP-facing wrapper process
- `adapter_contract.py`: tiny internal adapter interface
- `adapters/subprocess_json_adapter.py`: built-in subprocess JSON adapter
- `adapters/example_non_sdep_agent.py`: example native agent (non-SDEP)
- `run_wrapper_demo.py`: end-to-end demo using `SDEPExecutor`

## Native Agent Contract (Example)

Input JSON (stdin):

```json
{
  "request_id": "...",
  "action_type": "personal.gather_evidence",
  "target": {},
  "input_payload": {},
  "parameters": {}
}
```

Output JSON (stdout):

```json
{
  "status": "success|failed",
  "output": {},
  "error": "...",
  "error_code": "..."
}
```

This native contract is intentionally not SDEP.

## Run the Demo

```bash
python3 examples/sdep_wrapper_template/run_wrapper_demo.py
```

## Point `spice_personal` to the Wrapper

Example shape:

```bash
spice-personal ask "Should I take one low-risk next step?" \
  --executor sdep \
  --sdep-command "python3 examples/sdep_wrapper_template/wrapper_main.py --adapter subprocess-json --agent-command 'python3 examples/sdep_wrapper_template/adapters/example_non_sdep_agent.py'"
```

The wrapper then bridges SDEP calls to the non-SDEP native agent command.

