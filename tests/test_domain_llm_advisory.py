from __future__ import annotations

import unittest

from spice.decision import CandidateDecision, DecisionObjective
from spice.llm.services.domain_advisory import (
    DOMAIN_ADVISORY_ATTRIBUTE_KEYS,
    _resolve_domain_model_override,
    build_domain_llm_decision_policy,
)
from spice.protocols import WorldState


class DomainLLMAdvisoryPolicyTests(unittest.TestCase):
    def test_policy_select_normalizes_advisory_contract_fields(self) -> None:
        policy = build_domain_llm_decision_policy(
            model=None,
            domain="demo.domain",
            allowed_actions=("demo.domain.monitor", "demo.domain.notify"),
        )
        self.assertIsNotNone(policy)
        assert policy is not None

        state = WorldState(id="worldstate-demo")
        candidates = policy.propose(state, context=None)
        self.assertGreaterEqual(len(candidates), 1)

        decision = policy.select(candidates, DecisionObjective(), [])
        self.assertIn(decision.selected_action, {"demo.domain.monitor", "demo.domain.notify"})
        for key in DOMAIN_ADVISORY_ATTRIBUTE_KEYS:
            self.assertIn(key, decision.attributes)

    def test_policy_degraded_fallback_is_explicit_when_candidates_are_runtime_fallback(self) -> None:
        policy = build_domain_llm_decision_policy(
            model="missing_command_that_should_fail",
            domain="demo.domain",
            allowed_actions=("demo.domain.monitor",),
        )
        self.assertIsNotNone(policy)
        assert policy is not None

        state = WorldState(id="worldstate-demo")
        candidates = policy.propose(state, context=None)
        self.assertEqual(candidates, [])

        degraded = policy.select(
            [
                CandidateDecision(
                    id="fallback-1",
                    action="demo.domain.monitor",
                    score_total=1.0,
                    risk=0.0,
                    confidence=1.0,
                )
            ],
            DecisionObjective(),
            [],
        )
        self.assertTrue(bool(degraded.attributes.get("advisory_degraded")))
        self.assertEqual(
            degraded.attributes.get("degraded_reason"),
            "runtime_domain_fallback_candidates",
        )
        for key in DOMAIN_ADVISORY_ATTRIBUTE_KEYS:
            self.assertIn(key, degraded.attributes)

    def test_domain_model_override_supports_openrouter_prefix(self) -> None:
        override = _resolve_domain_model_override("openrouter:anthropic/claude-3.5-sonnet")
        self.assertIsNotNone(override)
        assert override is not None
        self.assertEqual(override.provider_id, "openrouter")
        self.assertEqual(override.model_id, "anthropic/claude-3.5-sonnet")

    def test_domain_model_override_preserves_subprocess_default(self) -> None:
        override = _resolve_domain_model_override("ollama run qwen2.5")
        self.assertIsNotNone(override)
        assert override is not None
        self.assertEqual(override.provider_id, "subprocess")
        self.assertEqual(override.model_id, "ollama run qwen2.5")


if __name__ == "__main__":
    unittest.main()
