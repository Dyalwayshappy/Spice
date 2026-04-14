# decision.md

Status: Draft
Schema Version: 0.1
Artifact Type: Decision Guidance Specification

`decision.md` is a human-readable decision guidance artifact for Spice.

It defines explicit objectives, preferences, constraints, trade-offs, risk budgets, evaluation criteria, and reflection guidance used to shape decision quality.

`decision.md` is intended to be stable enough for future structured parsing while remaining readable and reviewable by humans.

## Role In Spice

`decision.md` belongs to the decision layer.

It provides decision guidance that can later map into structured runtime artifacts such as objectives, scoring dimensions, constraints, policy guidance, traces, replay evaluation, and reflection questions.

It does not execute actions.
It does not store memory.
It does not mutate runtime state.
It does not replace domain logic or execution adapters.

Expected architectural position:

```md
decision.md
-> structured decision guidance
-> decision context / objective / constraints / scoring guidance
-> decision policy
-> decision trace
-> replay / evaluation / reflection
```

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

## Architectural Boundaries

`decision.md` must remain bounded to decision guidance.

Allowed:

- decision objectives
- scoring dimensions
- preference weights
- hard constraints
- soft constraints
- decision principles
- trade-off rules
- risk thresholds
- evaluation criteria
- reflection questions
- version and provenance metadata

Not allowed:

- raw logs
- unbounded memory
- event history
- user biography
- agent instructions
- tool-specific execution steps
- workflow automation plans
- model fine-tuning data
- direct policy mutation
- direct world-state mutation

Any runtime use of `decision.md` must pass through explicit structured mapping, validation, and deterministic decision-layer control.

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

Content that belongs here:

- decision domain
- decision class
- applicable situations
- excluded situations
- authority level
- scope boundaries

Content that must not be included:

- raw history
- prior outcomes
- execution steps
- tool instructions
- user biography
- unrelated domain context

Relation to decision-making:

Decision scope determines when the guidance is eligible to influence candidate generation, scoring, selection, replay, and evaluation.

Recommended structure:

```md
Domain: <domain_name>
Decision Class: <decision_class>
Applies To: <applicable_conditions>
Does Not Apply To: <excluded_conditions>
Authority: <advisory | default_policy_guidance | mandatory_policy_guidance>
```

## Primary Objective

Purpose: define the dominant optimization target for decision selection.

Content that belongs here:

- one primary objective
- optimization-oriented phrasing
- measurable or comparable outcome target
- decision-relevant success direction

Content that must not be included:

- multiple unrelated objectives
- execution method
- tool choice
- historical justification
- narrative explanation
- memory or user profile data

Relation to decision-making:

The primary objective is the top-level comparison target for eligible candidate decisions.
It should support scoring, ranking, selection, and post-outcome evaluation.

Guidelines:

- Use one primary objective.
- Prefer verbs such as maximize, minimize, reduce, preserve, or constrain.
- Ensure candidate decisions can be compared against the objective.
- Move supporting goals into Secondary Objectives.
- Do not encode execution instructions.

Recommended structure:

```md
Primary Objective:
<maximize_or_minimize_single_dominant_outcome>
```

## Secondary Objectives

Purpose: define supporting objectives that influence candidate scoring.

Content that belongs here:

- supporting decision goals
- measurable or comparable decision-quality dimensions
- objectives that clarify trade-offs
- objectives that may map to scoring dimensions

Content that must not be included:

- duplicate primary objectives
- raw history
- execution steps
- tool instructions
- generic aspirations unrelated to selection

Relation to decision-making:

Secondary objectives shape candidate scoring and trade-off evaluation.
They must remain subordinate to hard constraints, risk budget, and the primary objective.

Recommended structure:

```md
Secondary Objectives:
- <supporting_objective>
- <supporting_objective>
- <supporting_objective>
```

## Preferences / Weights

Purpose: define relative importance among candidate scoring dimensions.

Content that belongs here:

- scoring dimension names
- numeric weights
- priority order when numeric weights are not used
- short descriptions of scoring dimensions
- scoring rule that explains how weights influence ranking

Content that must not be included:

- private memory
- historical anecdotes
- execution plans
- tool-specific instructions
- unbounded narrative preference data

Relation to decision-making:

Preferences and weights apply during candidate evaluation.
Each weighted dimension should map to a candidate score dimension.
Higher-weighted dimensions should have greater influence on candidate ranking than lower-weighted dimensions.

Guidelines:

- Weights should be numeric when possible.
- Normalized weights should sum to 1.0.
- Each weight should correspond to a candidate score dimension.
- Weights should influence scoring only after hard constraints and eligibility checks.
- Non-numeric preferences must state ordering clearly.

Recommended structure:

```md
Preferences:
- <scoring_dimension>: <weight>
- <scoring_dimension>: <weight>
- <scoring_dimension>: <weight>
```

Optional scoring dimension descriptions:

```md
<scoring_dimension>:
  <short_description_of_what_this_dimension_measures>
```

Recommended scoring rule:

```md
Candidate score should reflect the weighted contribution of declared scoring dimensions.
A higher-weighted dimension should have greater influence on candidate ranking than a lower-weighted dimension.
Candidates that violate hard constraints are ineligible regardless of weighted score.
```

## Hard Constraints

Purpose: define conditions that must not be violated.

Content that belongs here:

- veto rules
- mandatory eligibility checks
- constraint identifiers
- constraint condition
- severity
- expected check result shape

Content that must not be included:

- soft preferences
- vague guidance without checkable criteria
- execution instructions
- tool steps
- raw event history

Relation to decision-making:

Hard constraints determine candidate eligibility.
A candidate that fails a hard constraint should be rejected unless an explicit override process exists outside Spice core.

Guidelines:

- Each hard constraint should have a stable identifier.
- Each hard constraint should be testable.
- Each hard constraint should produce pass, fail, or unknown.
- Failed hard constraints should produce a veto record.
- Unknown constraint status should reduce confidence or require explicit handling.

Recommended structure:

```md
Hard Constraints:
- id: <constraint_id>
  rule: <checkable_constraint_rule>
  severity: veto
```

## Soft Constraints

Purpose: define preferences that influence scoring but do not automatically veto candidates.

Content that belongs here:

- non-veto preferences
- ranking modifiers
- confidence modifiers
- scoring effects
- stable identifiers

Content that must not be included:

- hard veto rules
- execution instructions
- tool-specific behavior
- memory records
- historical examples

Relation to decision-making:

Soft constraints influence candidate scoring, ranking, confidence, or tie-breaking.
They must not override hard constraints.

Guidelines:

- Each soft constraint should have a stable identifier.
- Each soft constraint should describe its scoring or ranking effect.
- Soft constraints should remain bounded to candidate evaluation.

Recommended structure:

```md
Soft Constraints:
- id: <constraint_id>
  rule: <preference_rule>
  scoring_effect: <effect_on_scoring_or_ranking>
```

## Decision Principles

Purpose: define stable high-level decision philosophy.

Content that belongs here:

- concise decision principles
- stable policy philosophy
- general decision preferences
- principles that may inform future constraints, scores, or trade-off rules

Content that must not be included:

- operational steps
- tool instructions
- historical events
- memory records
- scenario-specific procedures

Relation to decision-making:

Decision principles guide interpretation of objectives, preferences, constraints, and trade-offs.
They are more general than trade-off rules and less operational than constraints.

Guidelines:

- Keep principles short.
- Keep principles stable.
- Do not encode execution behavior.
- Do not use principles as a substitute for enforceable constraints.

Recommended structure:

```md
Decision Principles:
- <principle>
- <principle>
- <principle>
```

## Trade-off Rules

Purpose: define enforceable selection rules for competing objectives.

Content that belongs here:

- stable rule identifiers
- triggering conditions
- enforceable selection preference
- explicit exceptions
- conflict resolution or priority ordering

Content that must not be included:

- vague descriptions
- non-actionable advice
- execution steps
- tool-specific behavior
- memory records
- raw historical examples

Relation to decision-making:

Trade-off rules guide candidate selection when candidates differ across scoring dimensions, risk, confidence, or constraint status.
Each trade-off rule must be actionable at decision selection time.

Guidelines:

- Each rule should define `when`, `enforce`, and `unless`.
- Each rule should be usable during ranking, veto, or tie-breaking.
- Conflicts between rules should be resolved by explicit priority ordering.
- Trade-off rules must not describe agent behavior or tool usage.

Recommended conflict resolution structure:

```md
Rule Priority:
1. hard constraints
2. <tradeoff_rule_id>
3. <tradeoff_rule_id>
4. <tradeoff_rule_id>
```

Recommended rule structure:

```md
Trade-off Rules:
- id: <tradeoff_rule_id>
  when: <trigger_condition>
  enforce: <selection_preference>
  unless: <explicit_exception>
```

## Risk Budget

Purpose: define acceptable risk exposure for selected decisions.

Content that belongs here:

- risk thresholds
- confidence thresholds
- eligibility limits
- escalation thresholds
- risk dimensions relevant to decision selection

Content that must not be included:

- raw incident history
- execution steps
- tool instructions
- memory summaries
- unbounded risk narratives

Relation to decision-making:

Risk budget constrains candidate eligibility, veto, ranking, and evaluation.
Risk budget should be observable through candidate risk, confidence, constraint checks, and outcome comparison.

Guidelines:

- Risk thresholds should be numeric when possible.
- Risk dimensions should be named explicitly.
- Risk budget should influence candidate eligibility, veto, or ranking.
- High-risk exceptions should require external approval.
- Risk budget must not be used as a memory mechanism.

Recommended structure:

```md
Risk Budget:
- <risk_threshold_name>: <value>
- <confidence_threshold_name>: <value>
- <escalation_threshold_name>: <value>
```

## Evaluation Criteria

Purpose: define how decision quality should be assessed after outcomes are known.

Content that belongs here:

- evaluation identifiers
- evaluation questions
- observable signals
- expected evidence sources
- criteria for comparing policy versions

Content that must not be included:

- raw logs
- full event history
- subjective diary entries
- execution instructions
- tool output dumps

Relation to decision-making:

Evaluation criteria determine how selected decisions are judged using runtime evidence.
They should support replay, shadow comparison, policy evaluation, and reflection.

Observable signals should come from:

- decision trace
- candidate score breakdown
- constraint checks
- veto records
- selected candidate risk and confidence
- outcome comparison
- reflection records
- replay and evaluation reports

Guidelines:

- Criteria should evaluate decision quality, not broad agent performance.
- Criteria should be observable from structured artifacts.
- Criteria should support comparison across policy versions.
- Criteria should not require storing raw logs in this file.

Recommended structure:

```md
Evaluation Criteria:
- id: <criterion_id>
  question: <decision_quality_question>
  signal: <observable_structured_signal>
```

## Reflection Guidance

Purpose: define bounded questions for post-outcome reflection.

Content that belongs here:

- concise reflection questions
- questions about objective satisfaction
- questions about score accuracy
- questions about constraint behavior
- questions about trade-off compliance
- questions about possible guidance revisions

Content that must not be included:

- raw history
- memory appendices
- execution instructions
- agent behavior rules
- automatic policy mutation
- accumulated event logs

Relation to decision-making:

Reflection guidance supports feedback-driven decision refinement.
Reflection may propose revisions to decision guidance, but must not automatically mutate this artifact.

Guidelines:

- Reflection should produce bounded decision-quality insights.
- Reflection may identify candidate revisions.
- Reflection must not append raw history to this file.
- Reflection must not directly change runtime policy.
- Reflection must not add execution instructions.

Recommended structure:

```md
Reflection Guidance:
- <bounded_reflection_question>
- <bounded_reflection_question>
- <bounded_reflection_question>
```

## Version / Metadata

Purpose: identify the artifact, its scope, and its revision state.

Content that belongs here:

- artifact identifier
- schema version
- artifact version
- domain
- decision class
- owner
- status
- effective date
- supersession reference
- review metadata

Content that must not be included:

- runtime logs
- raw history
- personal profile data
- execution output
- unbounded revision narrative

Relation to decision-making:

Version and metadata support auditability, provenance, trace linkage, and future structured parsing.
Runtime policy changes derived from this file should be evaluated separately.

Guidelines:

- Every `decision.md` should have a stable artifact identifier.
- Version changes should correspond to meaningful decision-guidance changes.
- Metadata should be concise and structured.
- This file should remain a guidance artifact, not a runtime execution log.

Recommended structure:

```md
Version:
- artifact_id: <stable_artifact_id>
- schema_version: 0.1
- artifact_version: <artifact_version>
- domain: <domain_name>
- decision_class: <decision_class>
- owner: <owner>
- status: <draft | example | active | deprecated>
- effective_from: <date_or_unset>
- supersedes: <artifact_id_or_none>
- reviewed_by: []
```

## Future Structured Mapping

Purpose: document likely future mappings without requiring implementation now.

Content that belongs here:

- conceptual mapping from document sections to structured Spice artifacts
- parser-neutral guidance
- non-authoritative implementation notes

Content that must not be included:

- parser implementation
- runtime loading logic
- policy mutation logic
- execution behavior
- tool orchestration details

Relation to decision-making:

Future structured mapping describes how this human-readable artifact may later become typed decision guidance for candidate evaluation, policy selection, tracing, replay, evaluation, and reflection.

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
