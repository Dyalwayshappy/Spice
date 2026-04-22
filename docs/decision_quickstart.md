# decision.md Quickstart

This quickstart shows how to initialize, validate, explain, and explicitly attach a `decision.md` profile.

## Files

- `docs/decision.md`: canonical specification
- `spice/decision/profiles/default.decision.md`: bundled read-only starter profile
- `spice/decision/profiles/default_support.json`: reference support contract for explain/demo/debug flows
- `.spice/decision/decision.md`: default user-local profile path after initialization
- `examples/decision.md`: concrete example artifact
- `examples/decision_support.json`: example policy/domain support contract
- `examples/decision_quickstart.py`: minimal Python explain flow

## Initialize A Local Profile

Copy the bundled default profile into a project-local config path:

```sh
python -m spice.entry decision init
```

This writes:

```text
.spice/
  decision/
    decision.md
    support/
      default_support.json
```

The support JSON is copied as a reference for explain/demo/debug flows. Runtime support should come from the active policy or domain adapter.

Use `--force` to overwrite existing local files:

```sh
python -m spice.entry decision init --force
```

## Validate And Explain

Validate the initialized profile:

```sh
python -m spice.entry decision explain .spice/decision/decision.md --support-json .spice/decision/support/default_support.json
```

Run the example profile:

```sh
python -m spice.entry decision explain examples/decision.md --support-json examples/decision_support.json
```

For structured output:

```sh
python -m spice.entry decision explain examples/decision.md --support-json examples/decision_support.json --json
```

The report includes:

- loaded artifact id and version
- validation status
- runtime-active sections
- runtime-inactive sections
- parse-only sections
- supported score dimensions
- supported hard constraint ids
- supported trade-off rule ids
- unsupported runtime semantics
- how the active `decision.md` sections can influence selection

## Compare A Decision Object

Once a runtime or demo has exported a decision comparison artifact, you can
inspect it directly:

```sh
python -m spice.entry decision compare \
  --input examples/decision_hub_demo/compare_artifacts/meeting_vs_pr_conflict.json
```

This renders:

- Decision-Relevant State
- candidate decisions
- score / contribution breakdown
- vetoes and constraint status
- trade-off rule effects
- selected recommendation
- why not the other candidates

Use `--show-execution` to include the downstream execution boundary and `--json`
to print the normalized comparison payload.

## Inspect The Support Contract

`examples/decision_support.json` declares what an active policy or domain adapter supports:

```json
{
  "score_dimensions": ["flight_readiness"],
  "constraint_ids": ["no_action_that_endangers_departure"],
  "tradeoff_rule_ids": ["delegate_blocking_pr_under_time_pressure"]
}
```

The actual example file contains a larger contract. Keep support ids aligned with the candidate policy; otherwise validation should report unsupported dimensions, constraints, or trade-off rules.

For runtime execution, the active policy/domain adapter is authoritative. Editing support JSON alone does not create runtime capability.

## Python API

Validate and explain:

```python
import json
from pathlib import Path

from spice.decision import (
    DecisionGuidanceSupport,
    explain_decision_guidance,
    format_decision_guidance_explanation,
)

support = DecisionGuidanceSupport.from_dict(
    json.loads(Path("examples/decision_support.json").read_text())
)
report = explain_decision_guidance("examples/decision.md", support=support)
print(format_decision_guidance_explanation(report))
```

Explicitly attach a local decision profile to runtime:

```python
from spice.core import SpiceRuntime
from spice.decision import guided_policy_from_profile

base_policy = build_your_policy()
guided_policy = guided_policy_from_profile(
    base_policy,
    ".spice/decision/decision.md",
)
runtime = SpiceRuntime(decision_policy=guided_policy)
decision = runtime.decide()
```

`guided_policy_from_profile` loads the selected profile explicitly. It uses support declared by the active policy/domain adapter unless a support object is deliberately passed.

The same path is available as a runnable example:

```sh
python examples/decision_quickstart.py
```

## Runtime Boundary

Runtime-active in v1:

- Primary Objective
- Preferences / Weights
- Hard Constraints
- Trade-off Rules

Not runtime-active in v1:

- Decision Principles
- Evaluation Criteria
- Reflection Guidance

Parse-only in v1:

- Version / Metadata

Primary Objective has lightweight semantics in v1. It influences comparison direction. Concrete decision behavior mainly comes from weights, hard constraint checks, and supported trade-off rules.

Hard Constraints require matching policy/domain support and candidate check results. Writing a constraint in `decision.md` does not make Spice know how to evaluate it.

Only a constrained subset of Trade-off Rules is executable. Other rule forms are parseable and auditable, but non-executable unless a policy/domain adapter supports their ids through candidate rule results.
