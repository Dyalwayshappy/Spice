from __future__ import annotations

import json
import unittest

from spice.llm.adapters.decision import _build_prompt
from spice.llm.adapters import LLMDecisionAdapter
from spice.llm.core import LLMClient, LLMModelConfig, LLMRouter, LLMTaskHook, ProviderRegistry
from spice.llm.providers import DeterministicLLMProvider
from spice.protocols import WorldState


class LLMDecisionAdapterCompatTests(unittest.TestCase):
    def test_decision_adapter_parses_action_type_fallback_fields(self) -> None:
        payload = [
            {
                "id": "dec-compat-1",
                "type": "compat.decision",
                "status": "proposed",
                "action": "compat.action",
            }
        ]
        adapter = LLMDecisionAdapter(client=_build_client(json.dumps(payload, ensure_ascii=True)))
        proposals = adapter.propose(WorldState(id="state-compat-1"))

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].decision_type, "compat.decision")
        self.assertEqual(proposals[0].selected_action, "compat.action")
        self.assertTrue(adapter._last_field_fallback_used)
        self.assertEqual(len(adapter._last_field_fallback_events), 1)
        self.assertTrue(adapter._last_field_fallback_events[0]["selected_action_fallback_used"])
        self.assertTrue(adapter._last_field_fallback_events[0]["decision_type_fallback_used"])

    def test_decision_prompt_contract_includes_allowed_actions(self) -> None:
        prompt = _build_prompt(
            WorldState(id="state-compat-2"),
            context={
                "domain": "personal.assistant",
                "allowed_actions": [
                    "personal.assistant.suggest",
                    "personal.assistant.ask_clarify",
                ],
            },
            max_candidates=3,
        )
        self.assertIn("Each candidate must include selected_action, decision_type, and status.", prompt)
        self.assertIn("selected_action must be one of payload.allowed_actions.", prompt)
        self.assertIn("Do not use action or type as primary fields.", prompt)
        self.assertIn(
            '"allowed_actions": ["personal.assistant.suggest", "personal.assistant.ask_clarify"]',
            prompt,
        )


def _build_client(response_text: str) -> LLMClient:
    provider = DeterministicLLMProvider(
        responses={LLMTaskHook.DECISION_PROPOSE: response_text}
    )
    registry = ProviderRegistry.empty().register(provider)
    cfg = LLMModelConfig(provider_id="deterministic", model_id="deterministic.compat")
    router = LLMRouter(
        hook_defaults={LLMTaskHook.DECISION_PROPOSE: cfg}
    )
    return LLMClient(registry=registry, router=router)


if __name__ == "__main__":
    unittest.main()
