from __future__ import annotations

import json
import unittest

from spice.core import SpiceRuntime
from spice.domain import SoftwareDomainPack
from spice.executors import MockExecutor
from spice.llm.adapters import (
    LLMDecisionAdapter,
    LLMPerceptionAdapter,
    LLMReflectionAdapter,
    LLMSimulationAdapter,
)
from spice.llm.core import LLMClient, LLMModelConfig, LLMRouter, LLMTaskHook, ProviderRegistry
from spice.llm.providers import DeterministicLLMProvider


class RuntimeAdapterFallbackTests(unittest.TestCase):
    def test_runtime_deterministic_semantics_without_adapters(self) -> None:
        runtime = SpiceRuntime(domain_pack=SoftwareDomainPack(), executor=MockExecutor())
        result = runtime.run_cycle(
            observation_type="software.build_failure",
            source="tests.no_adapters",
            attributes={"build_id": "b1"},
        )
        self.assertEqual(result["decision"].selected_action, "noop_software_action")
        self.assertEqual(runtime.state_store.get_state().resources.get("observation_count"), 1)

    def test_invalid_adapter_outputs_fall_back_to_deterministic_domain_logic(self) -> None:
        client = _build_client(
            responses={
                LLMTaskHook.PERCEPTION_INTERPRET: "not-json",
                LLMTaskHook.DECISION_PROPOSE: "not-json",
                LLMTaskHook.SIMULATION_ADVISE: "not-json",
                LLMTaskHook.REFLECTION_SYNTHESIZE: "not-json",
            }
        )
        domain_pack = SoftwareDomainPack(
            perception_model=LLMPerceptionAdapter(client=client),
            decision_model=LLMDecisionAdapter(client=client),
            simulation_model=LLMSimulationAdapter(client=client),
            reflection_model=LLMReflectionAdapter(client=client),
        )
        runtime = SpiceRuntime(domain_pack=domain_pack, executor=MockExecutor())

        result = runtime.run_cycle(
            observation_type="software.build_failure",
            source="tests.invalid_adapter",
            attributes={"build_id": "b2"},
        )

        self.assertEqual(result["decision"].selected_action, "noop_software_action")
        self.assertIn("placeholder", result["reflection"].insights.get("summary", ""))
        self.assertEqual(runtime.state_store.get_state().resources.get("observation_count"), 1)

    def test_simulation_failure_does_not_break_decision_selection(self) -> None:
        decision_payload = [
            {
                "id": "dec-candidate",
                "decision_type": "software.model",
                "status": "proposed",
                "selected_action": "model_action",
                "refs": [],
                "metadata": {},
                "attributes": {},
            }
        ]
        client = _build_client(
            responses={
                LLMTaskHook.DECISION_PROPOSE: json.dumps(decision_payload),
                LLMTaskHook.SIMULATION_ADVISE: "not-json",
            }
        )
        domain_pack = SoftwareDomainPack(
            decision_model=LLMDecisionAdapter(client=client),
            simulation_model=LLMSimulationAdapter(client=client),
        )
        runtime = SpiceRuntime(domain_pack=domain_pack, executor=MockExecutor())

        result = runtime.run_cycle(
            observation_type="software.build_failure",
            source="tests.simulation_failure",
            attributes={"build_id": "b3"},
        )
        self.assertEqual(result["decision"].selected_action, "model_action")
        self.assertEqual(runtime.state_store.get_state().resources.get("observation_count"), 1)


def _build_client(*, responses: dict[LLMTaskHook, str]) -> LLMClient:
    provider = DeterministicLLMProvider(responses=responses)
    registry = ProviderRegistry.empty().register(provider)
    default_cfg = LLMModelConfig(provider_id="deterministic", model_id="deterministic.v1")
    router = LLMRouter(
        global_default=default_cfg,
        hook_defaults={
            LLMTaskHook.PERCEPTION_INTERPRET: default_cfg,
            LLMTaskHook.DECISION_PROPOSE: default_cfg,
            LLMTaskHook.SIMULATION_ADVISE: default_cfg,
            LLMTaskHook.REFLECTION_SYNTHESIZE: default_cfg,
        },
    )
    return LLMClient(registry=registry, router=router)


if __name__ == "__main__":
    unittest.main()
