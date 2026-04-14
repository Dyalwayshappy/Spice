# decision.md

Status: Example
Schema Version: 0.1
Artifact Type: Decision Guidance
Intended Location: `examples/decision.md`

`decision.md` is a human-readable decision guidance artifact for Spice.

It defines explicit objectives, preferences, constraints, trade-offs, risk budgets, evaluation criteria, and reflection guidance used to shape decision quality.

This example governs a time-sensitive decision where a user must choose how to handle a GitHub PR shortly before leaving for a flight.

## What This File Is NOT

`decision.md` is not:

- a memory store
- a raw event log
- an autobiographical profile
- a conversation history
- a user journal
- a skill registry
- an execution runbook
- an agent capability file
- a prompt dump
- a tool orchestration plan
- a model training dataset
- an autonomous self-modification mechanism

This file must describe how decisions should be evaluated and selected.
It must not describe everything that happened in the past.

## Format Principles

`decision.md` should be:

- human-readable
- concise
- versioned
- auditable
- stable across runtime cycles
- bounded to decision guidance
- structured enough to map later into typed artifacts

Each section should use explicit labels and short declarative statements.

Avoid free-form narrative unless it clarifies decision intent.

## Decision Scope

Purpose: define the class of decisions governed by this artifact.

Required content:

```md
Domain: personal_work_coordination
Decision Class: time_sensitive_pr_attention
Applies To: situations where a user has less than 45 minutes before a fixed physical commitment and a GitHub PR requires attention
Does Not Apply To: emergency security fixes, production outages, or PRs already assigned to another owner
Authority: default_policy_guidance
```

## Primary Objective

Purpose: define the dominant optimization target for decision selection.

```md
Primary Objective:
Maximize probability of leaving for the flight on time.
```

Guidelines:

- Candidate decisions should be comparable by expected impact on flight departure readiness.
- The selected decision should preserve the physical commitment unless an explicit external override is required.
- PR-related risk reduction should be handled as a secondary objective and scoring dimension.
- The objective should be evaluated after the flight departure window.
- The primary objective must be comparable across all candidate decisions.

## Secondary Objectives

Purpose: define supporting objectives that influence candidate scoring.

```md
Secondary Objectives:
- minimize probability of missing or delaying the flight
- reduce PR blocker impact before departure
- preserve ability to recover or revise the PR response later
- minimize cognitive load during travel preparation
- maintain clear ownership and accountability for the PR
- avoid rushed changes with high regression risk
```

## Preferences / Weights

Purpose: define relative importance among candidate scoring dimensions.

Preferences and weights guide candidate evaluation when multiple valid candidates exist.

Each weighted dimension maps to a candidate score dimension.

```md
Preferences:
- flight_readiness: 0.35
- pr_risk_reduction: 0.25
- reversibility: 0.15
- time_efficiency: 0.10
- communication_clarity: 0.10
- implementation_confidence: 0.05
- Each scoring dimension must be computable from candidate state and context.
```

Scoring dimension descriptions:

```md
flight_readiness:
  Measures how well the candidate preserves departure readiness and reduces missed-flight risk.

pr_risk_reduction:
  Measures how much the candidate reduces expected PR-related blocker, review, or merge risk.

reversibility:
  Measures whether the action can be corrected, delayed, delegated, or amended later.

time_efficiency:
  Measures whether the candidate can be completed within the available time window.

communication_clarity:
  Measures whether stakeholders receive clear status, ownership, and next-step expectations.

implementation_confidence:
  Measures confidence that any PR action can be completed correctly without rushed mistakes.
```

Scoring rule:

```md
Candidate score should reflect the weighted contribution of declared scoring dimensions.
A higher-weighted dimension should have greater influence on candidate ranking than a lower-weighted dimension.
Candidates that violate hard constraints are ineligible regardless of weighted score.
```

Optional priority form:

```md
Priority Order:
1. hard constraints
2. missed-flight risk
3. risk budget
4. primary objective
5. flight_readiness
6. pr_risk_reduction
7. reversibility
8. communication_clarity
```

## Hard Constraints

Purpose: define conditions that must not be violated.

Hard constraints are veto rules.
A candidate that violates a hard constraint should be rejected unless an explicit override process exists outside Spice core.

```md
Hard Constraints:
- id: no_action_that_endangers_departure
  rule: do not select a candidate expected to prevent leaving for the airport on time
  severity: veto

- id: no_rushed_high_risk_code_change
  rule: do not select direct PR code changes when available focused work time is below 20 minutes and implementation confidence is below 0.80
  severity: veto

- id: no_silent_blocker_ignore
  rule: do not ignore a PR temporarily when the PR is blocking another person and no status update or delegation is provided
  severity: veto

- id: no_irreversible_merge_under_uncertainty
  rule: do not merge or approve irreversible PR changes when confidence is below 0.90
  severity: veto
```

Guidelines:

- Each hard constraint should produce a pass, fail, or unknown result during candidate evaluation.
- Failed hard constraints should produce a veto record.
- Unknown constraint status should reduce candidate confidence.

## Soft Constraints

Purpose: define preferences that influence scoring but do not automatically veto candidates.

Soft constraints should affect ranking, confidence, or trade-off evaluation.

```md
Soft Constraints:
- id: prefer_delegation_when_time_box_is_short
  rule: prefer delegation when available focused work time is below 30 minutes
  scoring_effect: increase communication_clarity and flight_readiness scores for delegation candidates

- id: prefer_brief_status_over_silent_delay
  rule: prefer sending a concise PR status update over taking no visible action
  scoring_effect: increase communication_clarity score

- id: prefer_review_over_code_change
  rule: prefer review, triage, or comment-only action over direct code modification under time pressure
  scoring_effect: increase reversibility and implementation_confidence scores

- id: prefer_time_boxed_action
  rule: prefer candidates that can be completed within a declared time box
  scoring_effect: increase time_efficiency score
```

Guidelines:

- Soft constraints should influence candidate scoring or ranking.
- Soft constraints should not override hard constraints.
- Soft constraints should remain bounded to candidate evaluation.

## Decision Principles

Purpose: define stable high-level decision philosophy.

Decision principles guide interpretation of objectives, preferences, constraints, and trade-offs.

```md
Decision Principles:
- preserve fixed physical commitments under ordinary digital-task pressure
- prefer reversible actions under uncertainty
- avoid irreversible PR actions under low confidence
- favor explicit handoff over silent delay
- prefer bounded-scope action before deep work when departure time is near
- favor safety over speed when rushed work could create downstream regressions
```

Guidelines:

- Principles should shape decision policy but should not describe execution steps.
- Principles should not include tool instructions.
- Principles should not record historical events.
- Principles may inform future scoring dimensions, constraints, or trade-off rules.

## Trade-off Rules

Purpose: define enforceable selection rules for competing objectives.

Trade-off rules guide candidate selection when candidates differ across scoring dimensions, risk, confidence, or constraint status.

Each trade-off rule must be actionable at decision selection time.

Conflict resolution:

```md
Rule Priority:
1. hard constraints
2. flight_preservation_over_pr_progress
3. delegate_blocking_pr_under_time_pressure
4. reversible_status_over_rushed_change
5. quick_review_if_low_risk
6. defer_non_blocking_pr
```

```md
Trade-off Rules:
- id: flight_preservation_over_pr_progress
  when: estimated time before departure is below 45 minutes
  enforce: prefer the eligible candidate with higher flight_readiness over the candidate with higher pr_risk_reduction
  unless: PR risk is critical and delegation or status update cannot reduce blocker impact

- id: delegate_blocking_pr_under_time_pressure
  when: PR is blocking another person and available focused work time is below 30 minutes
  enforce: prefer delegation or explicit handoff over direct implementation
  unless: direct action is low-risk, reversible, and completable within 10 minutes

- id: reversible_status_over_rushed_change
  when: implementation_confidence is below 0.80 or available focused work time is below 20 minutes
  enforce: prefer comment, status update, review note, or delegation over code change, approval, or merge
  unless: all reversible candidates violate hard constraints

- id: quick_review_if_low_risk
  when: PR requires attention but is not blocking and estimated review time is below 10 minutes
  enforce: prefer a time-boxed review or status response over full delegation
  unless: review would reduce flight_readiness below acceptable threshold

- id: defer_non_blocking_pr
  when: PR is non-blocking and expected impact of delay is low
  enforce: prefer temporary deferment with clear follow-up time over rushed action
  unless: a concise response can materially reduce stakeholder uncertainty within 5 minutes
```

Guidelines:

- Each rule should have a stable identifier.
- Each rule should define a triggering condition.
- Each rule should state an enforceable selection preference.
- Each rule should define any exception explicitly.
- Each rule should be usable during candidate ranking, veto, or tie-breaking.
- Trade-off rules should not describe tool usage or agent behavior.

## Risk Budget

Purpose: define acceptable risk exposure for selected decisions.

Risk budget provides a boundary for candidate eligibility and evaluation.

```md
Risk Budget:
- max_candidate_risk: 0.65
- max_missed_flight_risk: 0.20
- max_irreversible_pr_action_risk: 0.25
- minimum_confidence_for_direct_code_change: 0.80
- minimum_confidence_for_merge_or_approval: 0.90
- escalation_required_above_pr_blocker_risk: 0.75
- maximum_uncommunicated_delay_minutes: 60
```

Guidelines:

- Risk thresholds should be numeric when possible.
- Risk thresholds should be interpretable by replay and evaluation.
- Risk budget should influence candidate eligibility, veto, or ranking.
- High-risk exceptions should require external approval.
- Risk budget must not be used as a memory mechanism.

## Evaluation Criteria

Purpose: define how decision quality should be assessed after outcomes are known.

Evaluation criteria should connect selected decisions to observable runtime evidence.

Observable signals should come from:

- decision trace
- candidate score breakdown
- constraint checks
- veto records
- selected candidate risk and confidence
- outcome comparison
- reflection records
- replay and evaluation reports

```md
Evaluation Criteria:
- id: objective_alignment
  question: did the selected decision preserve flight readiness relative to eligible alternatives?
  signal: decision trace, selected candidate score, candidate score breakdown, and outcome comparison

- id: constraint_compliance
  question: did the selected decision pass all hard constraint checks?
  signal: constraint check results and veto records

- id: scoring_alignment
  question: did the selected candidate's score breakdown reflect declared weights for flight_readiness, pr_risk_reduction, reversibility, time_efficiency, communication_clarity, and implementation_confidence?
  signal: candidate score breakdown and selected candidate score

- id: tradeoff_compliance
  question: were applicable trade-off rules followed in priority order?
  signal: decision trace, rule trigger records, veto records, and selected candidate rationale

- id: risk_accuracy
  question: were missed-flight risk, PR blocker risk, and irreversible-action risk consistent with observed outcomes?
  signal: selected candidate risk, confidence, and outcome comparison

- id: communication_effectiveness
  question: did the decision reduce stakeholder uncertainty when direct PR completion was not selected?
  signal: outcome comparison, reflection record, and follow-up status result
```

Guidelines:

- Criteria should be observable from traces, candidate scores, constraints, outcomes, reflection, or replay.
- Criteria should evaluate decision quality, not broad agent performance.
- Criteria should support comparison across policy versions.
- Criteria should avoid raw historical accumulation.
- Criteria should not require storing raw logs in this file.

## Reflection Guidance

Purpose: define bounded questions for post-outcome reflection.

Reflection guidance should improve future decision quality without turning this file into memory.

```md
Reflection Guidance:
- did the selected candidate preserve the flight commitment?
- did the selected candidate reduce PR risk enough for the available time window?
- which score dimension was most misestimated?
- did any hard constraint produce an unexpected pass, fail, or unknown result?
- did the risk budget match observed travel and PR outcomes?
- should any preference weight be reviewed?
- should any trade-off rule be added, removed, reprioritized, or narrowed?
```

Guidelines:

- Reflection should produce bounded decision-quality insights.
- Reflection may propose revisions to this artifact.
- Reflection must not automatically mutate this artifact.
- Reflection must not append raw history to this file.
- Reflection must not add execution instructions or agent behavior rules.

## Version / Metadata

Purpose: identify the artifact, its scope, and its revision state.

Metadata should support auditability and future structured parsing.

```md
Version:
- artifact_id: decision.personal_work_coordination.flight_pr_conflict
- schema_version: 0.1
- artifact_version: 0.1.0
- domain: personal_work_coordination
- decision_class: time_sensitive_pr_attention
- owner: spice
- status: example
- effective_from: unset
- supersedes: none
- reviewed_by: []
```

Guidelines:

- Every `decision.md` should have a stable artifact identifier.
- Version changes should correspond to meaningful decision-guidance changes.
- Runtime policy changes derived from this file should be evaluated separately.
- This file should remain a guidance artifact, not a runtime execution log.

## Future Structured Mapping

Purpose: document likely future mappings without requiring implementation now.

Potential mappings:

```md
Primary Objective -> DecisionObjective
Secondary Objectives -> objective dimensions
Preferences / Weights -> candidate scoring dimensions and scoring weights
Hard Constraints -> SafetyConstraint with veto semantics
Soft Constraints -> scoring modifiers
Decision Principles -> policy guidance and scoring interpretation
Trade-off Rules -> enforceable selection, ranking, or tie-breaking rules
Risk Budget -> eligibility thresholds and evaluation gates
Evaluation Criteria -> replay and policy evaluation metrics
Reflection Guidance -> ReflectionContext prompts or review questions
Version / Metadata -> policy provenance and trace metadata
```

This mapping is informational in this draft.

No parser, runtime loader, policy mutation, or execution behavior is defined by this document.
