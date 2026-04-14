# decision.md

Status: Default Starter
Schema Version: 0.1
Artifact Type: Decision Guidance
Intended Location: `.spice/decision/decision.md`

This is a conservative starter profile for Spice decision selection.

It is not universal domain logic. It only becomes runtime-effective when the active policy or domain adapter emits matching score dimensions, constraint checks, and supported trade-off semantics.

## What This File Is NOT

`decision.md` is not:

- a memory store
- an execution runbook
- a tool orchestration plan
- a prompt dump
- an automatic natural-language rule executor
- a self-modification mechanism

## Decision Scope

Purpose: define the class of decisions governed by this artifact.

```md
Domain: general_decision_runtime
Decision Class: bounded_candidate_selection
Applies To: candidate decisions with declared scores, risks, confidence, and constraint checks
Does Not Apply To: domains without candidate score dimensions or constraint checks
Authority: default_policy_guidance
```

## Primary Objective

Purpose: define the dominant optimization target for decision selection.

```md
Primary Objective:
Maximize expected decision quality under declared constraints.
```

## Secondary Objectives

Purpose: define supporting objectives that influence candidate scoring.

```md
Secondary Objectives:
- reduce avoidable decision risk
- preserve reversibility when outcome uncertainty is high
- prefer candidates with clear confidence signals
```

## Preferences / Weights

Purpose: define relative importance among candidate scoring dimensions.

Each weighted dimension must be emitted by the active policy or domain adapter to affect runtime scoring.

```md
Preferences:
- outcome_value: 0.40
- risk_reduction: 0.25
- reversibility: 0.20
- confidence_alignment: 0.15
```

Scoring dimension descriptions:

```md
outcome_value:
  Measures expected usefulness of the candidate outcome.

risk_reduction:
  Measures how much the candidate reduces avoidable decision risk.

reversibility:
  Measures whether the decision can be corrected, delayed, or amended later.

confidence_alignment:
  Measures whether the candidate's confidence is appropriate for its risk.
```

## Hard Constraints

Purpose: define conditions that must not be violated.

Hard constraints require matching policy or domain adapter checks.

```md
Hard Constraints:
- id: no_declared_veto_violation
  rule: do not select a candidate that fails a declared veto check from the active policy or domain adapter
  severity: veto
```

## Soft Constraints

Purpose: define preferences that influence scoring but do not automatically veto candidates.

```md
Soft Constraints:
- id: prefer_reversible_when_uncertain
  rule: prefer reversible candidates when confidence is low
  scoring_effect: increase reversibility importance during candidate scoring
```

## Decision Principles

Purpose: define stable high-level decision philosophy.

This section is documentation-only in runtime v1.

```md
Decision Principles:
- honor hard constraints before score optimization
- prefer reversible actions under uncertainty
- prefer explicit uncertainty over hidden assumptions
- avoid irreversible choices when confidence is low
```

## Trade-off Rules

Purpose: define enforceable selection rules for competing objectives.

Only the constrained v1 subset is runtime-executable.

```md
Rule Priority:
1. hard constraints
2. prefer_lower_risk_when_candidates_differ
3. prefer_higher_confidence_when_candidates_differ
```

```md
Trade-off Rules:
- id: prefer_lower_risk_when_candidates_differ
  when: candidates differ on risk
  enforce: prefer lower risk
  unless: never

- id: prefer_higher_confidence_when_candidates_differ
  when: candidates differ on confidence
  enforce: prefer higher confidence
  unless: never
```

## Risk Budget

Purpose: define acceptable risk exposure for selected decisions.

```md
Risk Budget:
- default_high_risk_threshold: unset
- default_low_confidence_threshold: unset
```

## Evaluation Criteria

Purpose: define how decision quality should be assessed after outcomes are known.

This section is not runtime-active in v1.

```md
Evaluation Criteria:
- id: objective_alignment
  question: did the selected candidate align with the primary objective?
  signal: decision trace, candidate score breakdown, constraint checks, and outcome comparison
```

## Reflection Guidance

Purpose: define bounded questions for post-outcome reflection.

This section is not runtime-active in v1.

```md
Reflection Guidance:
- which scoring dimension was most misestimated?
- did any hard constraint produce an unexpected pass, fail, or unknown result?
- should any weight or trade-off rule be reviewed?
```

## Version / Metadata

Purpose: identify the artifact, its scope, and its revision state.

```md
Version:
- artifact_id: decision.default.general
- schema_version: 0.1
- artifact_version: 0.1.0
- domain: general_decision_runtime
- decision_class: bounded_candidate_selection
- owner: spice
- status: default
- effective_from: unset
- supersedes: none
- reviewed_by: []
```
