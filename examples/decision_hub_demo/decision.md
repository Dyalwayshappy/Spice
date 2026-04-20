# decision.md

Status: Example
Schema Version: 0.1
Artifact Type: Decision Guidance
Intended Location: `examples/decision_hub_demo/decision.md`

This file guides the decision hub demo domain. It is a decision guidance
artifact, not memory, state, execution configuration, or an agent runbook.

## What This File Is NOT

`decision.md` is not:

- a memory store
- a raw event log
- an execution plan
- an agent capability registry
- a tool orchestration file
- a prompt dump
- an autonomous self-modification mechanism

## Decision Scope

Purpose: define the demo decision class governed by this artifact.

```md
Domain: decision_hub_demo
Decision Class: commitment_work_item_conflict
Applies To: short-horizon conflicts between fixed commitments and open work items
Does Not Apply To: emergencies, medical decisions, financial trading, or irreversible legal commitments
Authority: demo_policy_guidance
```

## Primary Objective

Purpose: define the dominant optimization target for decision selection.

```md
Primary Objective:
Maximize safe progress on open work items while preserving fixed commitments.
```

## Secondary Objectives

Purpose: define supporting objectives that influence candidate scoring.

```md
Secondary Objectives:
- reduce unresolved work-item risk
- preserve commitment readiness
- prefer reversible action under time pressure
- minimize attention cost before fixed commitments
- maintain clear follow-up when work cannot be completed now
```

## Preferences / Weights

Purpose: define relative importance among candidate scoring dimensions.

Each weighted dimension maps to a candidate score dimension produced by the demo
candidate policy.

```md
Preferences:
- commitment_safety: 0.30
- work_item_risk_reduction: 0.25
- reversibility: 0.15
- time_efficiency: 0.10
- attention_preservation: 0.10
- confidence_alignment: 0.10
```

Scoring rule:

```md
Candidate score should reflect the weighted contribution of declared scoring dimensions.
Candidates that violate hard constraints are ineligible regardless of weighted score.
```

## Hard Constraints

Purpose: define veto boundaries for candidate selection.

```md
Hard Constraints:
- id: no_commitment_endangerment
  rule: do not select a candidate expected to create high risk to a fixed commitment
  severity: veto

- id: no_silent_blocker_ignore
  rule: do not silently ignore an attention-requiring work item when no status, delegation, or follow-up exists
  severity: veto

- id: no_executor_delegation_without_capability
  rule: do not select executor delegation unless an executor capability is explicitly available
  severity: veto

- id: no_low_confidence_irreversible_action
  rule: do not select a low-confidence irreversible action
  severity: veto
```

## Soft Constraints

Purpose: define non-veto preferences.

```md
Soft Constraints:
- id: prefer_short_reversible_action_under_time_pressure
  rule: prefer short reversible actions when available time is less than estimated work time
  scoring_effect: increase reversibility and time_efficiency
```

## Decision Principles

Purpose: define stable decision philosophy.

```md
Decision Principles:
- preserve fixed commitments under ordinary work-item pressure
- prefer reversible actions under uncertainty
- prefer explicit delegation or follow-up over silent delay
- keep execution details outside decision selection
```

## Trade-off Rules

Purpose: define enforceable or policy-annotated selection rules.

Conflict resolution:

```md
Rule Priority:
1. hard constraints
2. prefer_delegate_when_executor_available_and_time_pressure
3. prefer_reversible_under_time_pressure
```

```md
Trade-off Rules:
- id: prefer_delegate_when_executor_available_and_time_pressure
  when: executor is available and available work window is shorter than estimated work
  enforce: prefer delegation over direct handling
  unless: delegation would violate a hard constraint

- id: prefer_reversible_under_time_pressure
  when: candidates differ on reversibility
  enforce: prefer the eligible candidate with higher reversibility
  unless: the reversible candidate does not reduce work item risk
```

## Risk Budget

Purpose: define acceptable risk exposure for selected decisions.

```md
Risk Budget:
- max_commitment_risk: medium
- max_uncommunicated_work_item_risk: medium
- minimum_confidence_for_irreversible_action: 0.80
```

## Evaluation Criteria

Purpose: define observable signals for replay and evaluation.

```md
Evaluation Criteria:
- id: commitment_preservation
  signal: decision trace, commitment risk, outcome comparison

- id: work_item_progress
  signal: work item risk change, execution result outcome

- id: guidance_alignment
  signal: candidate score breakdown, constraint checks, trade-off rule records
```

## Reflection Guidance

Purpose: define bounded post-outcome review questions.

```md
Reflection Guidance:
- did the selected action preserve fixed commitments?
- did the selected action reduce work-item risk enough for the available time?
- which consequence estimate was most inaccurate?
- should any scoring weight or veto rule be reviewed?
```

## Version / Metadata

Purpose: identify the artifact and revision.

```md
Version:
- artifact_id: decision.decision_hub_demo.commitment_work_item_conflict
- schema_version: 0.1
- artifact_version: 0.1.0
- domain: decision_hub_demo
- decision_class: commitment_work_item_conflict
- owner: spice
- status: example
- effective_from: unset
- supersedes: none
- reviewed_by: []
```

## Future Structured Mapping

Purpose: document likely future mappings without requiring implementation now.

```md
Primary Objective -> DecisionObjective
Preferences / Weights -> candidate score dimensions
Hard Constraints -> veto checks emitted by the candidate policy
Trade-off Rules -> executable subset or policy-provided candidate annotations
Version / Metadata -> provenance in decision trace
```
