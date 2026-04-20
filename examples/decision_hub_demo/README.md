# Decision Hub Demo

This example demonstrates a minimal simulation-driven Spice decision loop while
keeping the implementation out of Spice core.

Flow:

```text
Observation
-> WorldState reducer
-> ActiveDecisionContext builder
-> deterministic conflict detection
-> fixed candidate registry
-> structured consequence estimation
-> GuidedDecisionPolicy / decision.md selection
-> recommendation + trace
-> optional confirmation
-> execution request
-> execution_result_observed
-> WorldState reducer update
```

Boundary:

- The reducer updates facts only.
- `ActiveDecisionContext` is a derived slice for one decision, not source of truth.
- Candidate actions are fixed by the demo registry.
- The optional LLM simulation model may estimate structured consequences only.
- The LLM may not create candidates or choose the recommendation.
- Final selection is performed by `GuidedDecisionPolicy` using `decision.md`.
- Execution results never mutate state directly; they return as
  `execution_result_observed` observations and pass through the reducer.

Implemented candidate actions:

- `handle_now`
- `quick_triage_then_defer`
- `ignore_temporarily`
- `delegate_to_executor`
- `ask_user`

`delegate_to_executor` is enabled only when Spice has ingested an
`executor_capability_observed` observation and that capability is available for
the required scope. The demo does not use a boolean flag to pretend an executor
exists. Capability must enter `WorldState` first, then `ActiveDecisionContext`
derives whether delegation is runtime-real.

Minimal capability observation shape:

```json
{
  "observation_type": "executor_capability_observed",
  "source": "hermes",
  "observed_at": "2026-04-17T08:00:00+00:00",
  "confidence": 1.0,
  "attributes": {
    "capability_id": "cap.external_executor.codex",
    "action_type": "delegate_to_executor",
    "executor": "codex",
    "supported_scopes": ["triage", "review_summary"],
    "requires_confirmation": true,
    "reversible": true,
    "default_time_budget_minutes": 10,
    "availability": "available"
  }
}
```

In the demo code, `observed_at` is represented by the shared
`Observation.timestamp` field.

The current demo only models `codex` via Hermes as a `delegate_to_executor`
capability. Unsupported scopes or unavailable executors disable the delegate
candidate and record the reason in the trace. `ask_user` is enabled only when
the active context has missing critical information or low-confidence facts.

## Confirmation loop

Recommendations include `requires_confirmation`. The value comes from action
metadata and capability facts, not from LLM output.

When `delegate_to_executor` is selected with `requires_confirmation: true`, the
demo returns a stable confirmation request:

```json
{
  "confirmation_id": "confirm.2026-04-17T08:00:00Z.delegate_to_executor.ab12cd34",
  "decision_id": "decision.2026-04-17T08:00:00Z.workitem.github_pr_123.ab12cd34",
  "selected_action": "delegate_to_executor",
  "acted_on": "workitem.github.dyalwayshappy_spice.123",
  "options": [
    {"key": "1", "value": "confirm"},
    {"key": "2", "value": "reject"},
    {"key": "3", "value": "details"}
  ]
}
```

This is intentionally shaped for WhatsApp mapping:

```text
1 同意执行
2 拒绝
3 查看详情
```

`confirm` creates an execution request and applies the structured outcome back
through `execution_result_observed`. `reject` does not execute and does not
pretend work was handled. `details` returns the decision trace explanation and
keeps the confirmation pending.

`ask_user` does not enter the execution path. It returns a structured prompt for
missing information. `ignore_temporarily` is a no-op in this demo and does not
create an execution outcome.

Minimal delegate execution request params:

```json
{
  "scope": "triage",
  "time_budget_minutes": 10,
  "target_title": "Fix decision guidance validation",
  "target_url": "https://github.com/Dyalwayshappy/Spice/pull/123",
  "success_criteria": "Return status, blocker, risk_change, followup_needed, and a concise summary."
}
```

This demo intentionally does not implement persistent storage, real GitHub
polling, or WhatsApp ingress. Its default execution path is SDEP-backed:
confirmations produce SDEP `execute.request` messages, Hermes/Codex execution
stays behind the SDEP wrapper, and outcomes return as `execution_result_observed`.
Mock or direct Hermes executors are explicit test/debug overrides, not the
public default.
