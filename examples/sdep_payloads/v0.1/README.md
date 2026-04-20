# SDEP v0.1 Example Payloads

These files are human-readable examples of the SDEP v0.1 wire contract.

Files:

- `execute.request.json`: a Spice decision handoff to an external executor.
- `execute.response.success.json`: protocol success and task success.
- `execute.response.task_failed.json`: protocol success and task failure.
- `execute.response.protocol_error.json`: protocol / wrapper error.
- `agent.describe.request.json`: capability discovery request.
- `agent.describe.response.json`: capability declaration response.
- `execute.response.task_failed.json` = protocol success, task failed
- `execute.response.protocol_error.json` = protocol/wrapper failure

The task-failure example intentionally uses:

```json
{
  "status": "success",
  "outcome": {
    "status": "failed"
  }
}
```

This means the SDEP exchange succeeded, but the delegated task failed.
