from __future__ import annotations

import unittest
from pathlib import Path

from spice.core import SpiceRuntime
from spice.decision import (
    CandidateDecision,
    DecisionGuidanceSupport,
    GuidedDecisionPolicy,
    PolicyIdentity,
    load_decision_guidance,
    parse_decision_guidance,
)


EXAMPLE_DECISION_MD = Path(__file__).resolve().parents[1] / "examples" / "decision.md"


class FlightPrCandidatePolicy:
    identity = PolicyIdentity.create(
        policy_name="tests.flight_pr_candidates",
        policy_version="0.1",
        implementation_fingerprint="flight-pr-candidates-v1",
    )
    decision_guidance_support = DecisionGuidanceSupport(
        score_dimensions={
            "flight_readiness",
            "pr_risk_reduction",
            "reversibility",
            "time_efficiency",
            "communication_clarity",
            "implementation_confidence",
        },
        constraint_ids={
            "no_action_that_endangers_departure",
            "no_rushed_high_risk_code_change",
            "no_silent_blocker_ignore",
            "no_irreversible_merge_under_uncertainty",
        },
        tradeoff_rule_ids={"delegate_blocking_pr_under_time_pressure"},
    )

    def propose(self, state, context):
        return [
            CandidateDecision(
                id="candidate.handle_pr_now",
                action="handle_pr_now",
                params={
                    "constraint_checks": {
                        "no_rushed_high_risk_code_change": "fail",
                    },
                },
                score_total=0.98,
                score_breakdown={
                    "flight_readiness": 0.10,
                    "pr_risk_reduction": 1.00,
                    "reversibility": 0.20,
                    "time_efficiency": 0.10,
                    "communication_clarity": 0.20,
                    "implementation_confidence": 0.40,
                },
                risk=0.78,
                confidence=0.40,
            ),
            CandidateDecision(
                id="candidate.delegate_pr",
                action="delegate_pr",
                params={
                    "constraint_checks": {
                        "no_action_that_endangers_departure": "pass",
                        "no_rushed_high_risk_code_change": "pass",
                        "no_silent_blocker_ignore": "pass",
                        "no_irreversible_merge_under_uncertainty": "pass",
                    },
                    "tradeoff_rule_results": {
                        "delegate_blocking_pr_under_time_pressure": "preferred",
                    },
                },
                score_total=0.50,
                score_breakdown={
                    "flight_readiness": 0.82,
                    "pr_risk_reduction": 0.70,
                    "reversibility": 0.85,
                    "time_efficiency": 0.70,
                    "communication_clarity": 0.95,
                    "implementation_confidence": 0.85,
                },
                risk=0.30,
                confidence=0.86,
            ),
            CandidateDecision(
                id="candidate.send_status_and_defer",
                action="send_status_and_defer",
                params={
                    "constraint_checks": {
                        "no_action_that_endangers_departure": "pass",
                        "no_rushed_high_risk_code_change": "pass",
                        "no_silent_blocker_ignore": "pass",
                        "no_irreversible_merge_under_uncertainty": "pass",
                    },
                    "tradeoff_rule_results": {
                        "delegate_blocking_pr_under_time_pressure": "disfavored",
                    },
                },
                score_total=0.40,
                score_breakdown={
                    "flight_readiness": 0.95,
                    "pr_risk_reduction": 0.55,
                    "reversibility": 0.95,
                    "time_efficiency": 0.95,
                    "communication_clarity": 0.85,
                    "implementation_confidence": 0.95,
                },
                risk=0.18,
                confidence=0.91,
            ),
            CandidateDecision(
                id="candidate.ignore_temporarily",
                action="ignore_temporarily",
                params={
                    "constraint_checks": {
                        "no_silent_blocker_ignore": "fail",
                    },
                },
                score_total=0.10,
                score_breakdown={
                    "flight_readiness": 0.95,
                    "pr_risk_reduction": 0.00,
                    "reversibility": 0.80,
                    "time_efficiency": 1.00,
                    "communication_clarity": 0.00,
                    "implementation_confidence": 1.00,
                },
                risk=0.35,
                confidence=0.80,
            ),
        ]

    def select(self, candidates, objective, constraints):
        selected = max(candidates, key=lambda candidate: candidate.score_total)
        raise AssertionError(f"GuidedDecisionPolicy should own selection, got {selected.id}")


class DecisionGuidanceTests(unittest.TestCase):
    def test_decision_md_guidance_affects_runtime_selection(self) -> None:
        guidance = load_decision_guidance(EXAMPLE_DECISION_MD)
        policy = GuidedDecisionPolicy(FlightPrCandidatePolicy(), guidance)
        runtime = SpiceRuntime(decision_policy=policy)

        decision = runtime.decide()
        trace = runtime.latest_decision_trace

        self.assertIsNotNone(trace)
        self.assertEqual(decision.selected_action, "delegate_pr")
        self.assertEqual(trace.selected_candidate.id, "candidate.delegate_pr")

        candidates = {candidate.id: candidate for candidate in trace.all_candidates}
        self.assertLess(
            candidates["candidate.handle_pr_now"].score_total,
            candidates["candidate.send_status_and_defer"].score_total,
        )
        self.assertGreater(
            candidates["candidate.send_status_and_defer"].score_total,
            candidates["candidate.delegate_pr"].score_total,
        )

        vetoed_ids = {event["constraint_id"] for event in trace.veto_events}
        self.assertIn("no_rushed_high_risk_code_change", vetoed_ids)
        self.assertIn("no_silent_blocker_ignore", vetoed_ids)

        metadata = trace.metadata
        guidance_metadata = metadata["decision_guidance"]
        self.assertEqual(
            guidance_metadata["artifact_id"],
            "decision.personal_work_coordination.flight_pr_conflict",
        )
        self.assertEqual(guidance_metadata["schema_version"], "0.1")
        self.assertIn(
            "delegate_blocking_pr_under_time_pressure",
            metadata["applied_tradeoff_rules"],
        )
        self.assertIn(
            "flight_preservation_over_pr_progress",
            metadata["unsupported_tradeoff_rules"],
        )
        validation = metadata["decision_guidance_validation"]
        self.assertEqual(validation["status"], "partially_supported")
        issue_codes = {issue["code"] for issue in validation["issues"]}
        self.assertIn("unsupported_tradeoff_rule", issue_codes)

        explanation = metadata["decision_guidance_explanation"]
        self.assertEqual(explanation["selected_candidate_id"], "candidate.delegate_pr")
        delegate_score = explanation["candidate_scores"]["candidate.delegate_pr"]
        self.assertIn("weighted_contributions", delegate_score)
        self.assertIn("flight_readiness", delegate_score["weighted_contributions"])
        self.assertIn("veto_events", explanation)
        self.assertIn("unsupported_tradeoff_rules", explanation)

    def test_validation_reports_unsupported_score_dimensions(self) -> None:
        guidance = parse_decision_guidance(
            """
# decision.md

## Primary Objective

```md
Primary Objective:
Maximize useful outcome.
```

## Preferences / Weights

```md
Preferences:
- supported: 0.5
- unknown: 0.5
```

## Hard Constraints

```md
Hard Constraints:
- id: supported_constraint
  rule: must be checked
  severity: veto
```

## Trade-off Rules

```md
Rule Priority:
1. hard constraints
2. prefer_supported
```

```md
Trade-off Rules:
- id: prefer_supported
  when: candidates differ on supported
  enforce: prefer higher supported
  unless: never
```

## Version / Metadata

```md
Version:
- artifact_id: decision.test.unsupported_dimension
- schema_version: 0.1
- artifact_version: 0.1.0
- status: test
```
"""
        )
        policy = GuidedDecisionPolicy(
            _ExecutableTradeoffPolicy(),
            guidance,
            support=DecisionGuidanceSupport(
                score_dimensions={"supported"},
                constraint_ids={"supported_constraint"},
            ),
        )
        runtime = SpiceRuntime(decision_policy=policy)

        runtime.decide()
        trace = runtime.latest_decision_trace

        self.assertIsNotNone(trace)
        validation = trace.metadata["decision_guidance_validation"]
        issue_codes = {issue["code"] for issue in validation["issues"]}
        self.assertEqual(validation["status"], "partially_supported")
        self.assertIn("unsupported_score_dimension", issue_codes)
        self.assertIn("candidate_missing_score_dimension", issue_codes)

    def test_parser_reports_malformed_weights_as_structured_feedback(self) -> None:
        guidance = parse_decision_guidance(
            """
# decision.md

## Primary Objective

```md
Primary Objective:
Maximize useful outcome.
```

## Preferences / Weights

```md
Preferences:
- supported: not-a-number
malformed line
```

## Hard Constraints

```md
Hard Constraints:
- id: supported_constraint
  rule: must be checked
  severity: veto
```

## Trade-off Rules

```md
Trade-off Rules:
- id: prefer_supported
  when: candidates differ on supported
  enforce: prefer higher supported
  unless: never
```

## Version / Metadata

```md
Version:
- artifact_id: decision.test.malformed
- schema_version: 0.1
```
"""
        )

        issue_codes = {issue.code for issue in guidance.validation_issues}
        self.assertIn("malformed_weight_value", issue_codes)
        self.assertIn("malformed_weight", issue_codes)
        self.assertIn("preferences_weights_missing", issue_codes)

    def test_executable_tradeoff_rule_narrows_selection_without_annotations(self) -> None:
        guidance = parse_decision_guidance(
            """
# decision.md

## Primary Objective

```md
Primary Objective:
Maximize useful outcome.
```

## Preferences / Weights

```md
Preferences:
- speed: 0.8
- safety: 0.2
```

## Hard Constraints

```md
Hard Constraints:
- id: supported_constraint
  rule: must be checked
  severity: veto
```

## Trade-off Rules

```md
Rule Priority:
1. hard constraints
2. unsupported_prose_rule
3. prefer_safety_when_different
```

```md
Trade-off Rules:
- id: prefer_safety_when_different
  when: candidates differ on safety
  enforce: prefer higher safety
  unless: never

- id: unsupported_prose_rule
  when: situation is ambiguous
  enforce: use judgment
  unless: something else applies
```

## Version / Metadata

```md
Version:
- artifact_id: decision.test.executable_tradeoff
- schema_version: 0.1
- artifact_version: 0.1.0
- status: test
```
"""
        )
        policy = GuidedDecisionPolicy(
            _ExecutableTradeoffPolicy(),
            guidance,
            support=DecisionGuidanceSupport(
                score_dimensions={"speed", "safety"},
                constraint_ids={"supported_constraint"},
            ),
        )
        runtime = SpiceRuntime(decision_policy=policy)

        decision = runtime.decide()
        trace = runtime.latest_decision_trace

        self.assertIsNotNone(trace)
        self.assertEqual(decision.selected_action, "safe_action")

        metadata = trace.metadata
        self.assertIn(
            "prefer_safety_when_different",
            metadata["applied_tradeoff_rules"],
        )
        applied_detail = metadata["applied_tradeoff_rule_details"][0]
        self.assertEqual(applied_detail["mode"], "executable_subset")
        self.assertEqual(
            applied_detail["selected_candidate_ids"],
            ["candidate.safe"],
        )
        self.assertIn(
            "unsupported_prose_rule",
            metadata["unsupported_tradeoff_rules"],
        )


class _ExecutableTradeoffPolicy:
    identity = PolicyIdentity.create(
        policy_name="tests.executable_tradeoff",
        policy_version="0.1",
        implementation_fingerprint="executable-tradeoff-v1",
    )

    def propose(self, state, context):
        return [
            CandidateDecision(
                id="candidate.fast",
                action="fast_action",
                params={
                    "constraint_checks": {
                        "supported_constraint": "pass",
                    },
                },
                score_total=0.0,
                score_breakdown={
                    "speed": 1.0,
                    "safety": 0.1,
                    "supported": 0.7,
                },
                risk=0.5,
                confidence=0.7,
            ),
            CandidateDecision(
                id="candidate.safe",
                action="safe_action",
                params={
                    "constraint_checks": {
                        "supported_constraint": "pass",
                    },
                },
                score_total=0.0,
                score_breakdown={
                    "speed": 0.1,
                    "safety": 1.0,
                    "supported": 0.8,
                },
                risk=0.1,
                confidence=0.9,
            ),
        ]

    def select(self, candidates, objective, constraints):
        raise AssertionError("GuidedDecisionPolicy should own selection")


if __name__ == "__main__":
    unittest.main()
