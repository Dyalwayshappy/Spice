from __future__ import annotations

import unittest

from spice.llm.adapters.simulation import _build_prompt
from spice.protocols import WorldState


class LLMSimulationAdapterContractTests(unittest.TestCase):
    def test_simulation_prompt_includes_required_json_contract(self) -> None:
        prompt = _build_prompt(
            state=WorldState(id="state-sim-contract"),
            decision=None,
            intent=None,
            context={"domain": "demo.domain"},
        )

        self.assertIn("You are a SPICE simulation advisor.", prompt)
        self.assertIn(
            "Task: using the JSON input below, provide simulation advice for candidate evaluation before execution.",
            prompt,
        )
        self.assertIn("JSON object only.", prompt)
        self.assertIn("Required top-level fields: suggestion_text (string), score (number), confidence (number), urgency (string).", prompt)
        self.assertIn(
            "suggestion_text must be concrete, concise (1-2 sentences), and aligned with decision.selected_action.",
            prompt,
        )
        self.assertIn(
            "Domain-specific contracts may be provided in context and should be followed when present.",
            prompt,
        )
        self.assertIn("No markdown.", prompt)
        self.assertIn("No prose outside the JSON object.", prompt)
        self.assertIn("Non-JSON output is invalid.", prompt)
        self.assertIn("Missing required fields means the response is invalid.", prompt)
        self.assertNotIn("personal.assistant.suggest", prompt)

    def test_simulation_prompt_forbids_meta_process_language(self) -> None:
        prompt = _build_prompt(
            state=WorldState(id="state-sim-guardrails"),
            decision=None,
            intent=None,
            context={"domain": "demo.domain"},
        )

        self.assertIn(
            "Forbidden in suggestion_text: response/system/model/prompt/instruction/policy/process commentary.",
            prompt,
        )
        self.assertIn(
            "Forbidden in suggestion_text: generic template advice with no concrete action.",
            prompt,
        )
        self.assertNotIn("SPICE Personal Advisor", prompt)


if __name__ == "__main__":
    unittest.main()
