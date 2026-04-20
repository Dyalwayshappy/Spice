from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from spice.decision.guidance import parse_decision_guidance
from spice.llm.core import LLMResponse
from spice.protocols.observation import Observation

from examples.decision_hub_demo.candidates import CANDIDATE_REGISTRY, generate_candidates
from examples.decision_hub_demo.confirmation import (
    DecisionControlLoop,
    InMemoryConfirmationStore,
    create_confirmation_request,
    format_confirmation_for_whatsapp,
)
from examples.decision_hub_demo.context import build_active_context
from examples.decision_hub_demo.execution_adapter import (
    ExecutionFeedbackAdapter,
    ExecutionOutcome,
    ExecutionRequest,
    build_execution_request,
    execution_outcome_to_observation,
)
from examples.decision_hub_demo.llm_simulation import (
    DecisionHubLLMSimulationModel,
    OPENROUTER_API_KEY_ENV,
    SIMULATION_ENABLED_ENV,
    SIMULATION_MODEL_ENV,
    build_simulation_runner_from_env,
)
from examples.decision_hub_demo.policy import (
    DEMO_DECISION_MD,
    DecisionHubCandidatePolicy,
    DecisionHubRecommendationRunner,
)
from examples.decision_hub_demo.reducer import ingest_observation
from examples.decision_hub_demo.simulation import StructuredSimulationRunner
from examples.decision_hub_demo.sdep_executor import (
    SDEPBackedExecutor,
    SDEP_DELEGATE_ACTION_TYPE,
    sdep_response_to_execution_outcome,
)
from examples.decision_hub_demo.state import DOMAIN_KEY, new_world_state
from examples.decision_hub_demo.trace import get_trace


NOW = datetime(2026, 4, 17, 6, 0, tzinfo=timezone.utc)


class FakeSimulationModel:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses

    def simulate(self, state: Any, decision: Any = None, intent: Any = None, context: Any = None) -> dict[str, Any]:
        del state, intent, context
        return self.responses[decision.selected_action]


class FakeLLMClient:
    def __init__(self, output: Any) -> None:
        self.output = output
        self.requests: list[Any] = []

    def generate(self, request: Any, *, model_override: Any = None) -> LLMResponse:
        self.requests.append((request, model_override))
        output_text = self.output(request) if callable(self.output) else self.output
        return LLMResponse(
            provider_id="openrouter",
            model_id="test-model",
            output_text=str(output_text),
            raw_payload={},
            finish_reason="stop",
            usage={},
            latency_ms=1,
            request_id="fake-request",
        )


class CapturingSDEPTransport:
    def __init__(self, *, outcome_status: str = "success", response_status: str = "success") -> None:
        self.outcome_status = outcome_status
        self.response_status = response_status
        self.requests: list[Any] = []

    def execute(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return sdep_response_for_request(
            request,
            outcome_status=self.outcome_status,
            response_status=self.response_status,
        )


def sdep_response_for_request(
    request: Any,
    *,
    outcome_status: str = "success",
    response_status: str = "success",
) -> dict[str, Any]:
    output_status = outcome_status if response_status == "success" else "failed"
    risk_change = "reduced" if output_status in {"success", "partial"} else "increased"
    return {
        "protocol": "sdep",
        "sdep_version": "0.1",
        "message_type": "execute.response",
        "message_id": "sdep-msg-test",
        "request_id": request.request_id,
        "timestamp": "2026-04-17T06:00:01+00:00",
        "responder": {
            "id": "agent.hermes",
            "name": "Hermes SDEP Executor",
            "version": "0.1",
            "vendor": "Spice",
            "implementation": "hermes-codex",
            "role": "executor",
        },
        "status": response_status,
        "outcome": {
            "execution_id": "hermes.exec.001",
            "status": output_status,
            "outcome_type": "observation",
            "output": {
                "decision_id": request.traceability["spice_decision_id"],
                "selected_action": request.execution.action_type,
                "acted_on": request.execution.target.get("id"),
                "status": output_status,
                "elapsed_minutes": 6,
                "risk_change": risk_change,
                "followup_needed": output_status in {"success", "failed", "partial", "abandoned"},
                "summary": f"SDEP execution ended with status {output_status}.",
                "execution_ref": "hermes.exec.001",
                "blocking_issue": "sdep_test_failure" if output_status == "failed" else None,
            },
            "artifacts": [],
            "metrics": {"elapsed_minutes": 6},
            "metadata": {"executor": "codex"},
        },
        "error": None
        if response_status == "success"
        else {
            "code": "hermes.test_error",
            "message": "SDEP test protocol error.",
            "retryable": True,
            "details": {"stderr_excerpt": "test"},
        },
        "traceability": dict(request.traceability),
        "metadata": {"wrapper": "test_sdep_transport"},
    }


def llm_consequence_json(request: Any) -> str:
    action = str(request.metadata["action_type"])
    payload = consequence_payload(action)
    payload["candidate_id"] = str(request.metadata["candidate_id"])
    payload["metadata"] = {"from_fake_llm": True}
    return json.dumps(payload)


class DecisionHubDemoTests(unittest.TestCase):
    def test_default_execution_adapter_uses_sdep_backed_executor(self) -> None:
        adapter = ExecutionFeedbackAdapter()

        self.assertIsInstance(adapter.executor, SDEPBackedExecutor)

    def test_expired_commitment_not_in_active_context(self) -> None:
        state = new_world_state()
        ingest_observation(
            state,
            commitment_obs(
                "commitment.expired",
                start=NOW - timedelta(hours=3),
                end=NOW - timedelta(hours=2),
            ),
        )

        context = build_active_context(state, now=NOW)

        self.assertEqual(context.relevant_commitments, [])

    def test_current_commitment_and_work_item_form_conflict_fact(self) -> None:
        state = state_with_commitment_and_work_item()

        context = build_active_context(state, now=NOW)

        self.assertEqual(len(context.relevant_commitments), 1)
        self.assertEqual(len(context.open_work_items), 1)
        self.assertTrue(any(item.type == "time_conflict" for item in context.conflict_facts))
        conflict = next(item for item in context.conflict_facts if item.type == "time_conflict")
        self.assertEqual(conflict.facts["available_window_minutes"], 12)
        self.assertEqual(conflict.facts["estimated_work_minutes"], 30)

    def test_executor_capability_observation_updates_world_state(self) -> None:
        state = new_world_state()

        ingest_observation(state, executor_capability_obs())

        capabilities = state.domain_state[DOMAIN_KEY]["capabilities"]
        capability = capabilities["cap.external_executor.codex"]
        self.assertEqual(capability["action_type"], "delegate_to_executor")
        self.assertEqual(capability["executor"], "codex")
        self.assertEqual(capability["supported_scopes"], ["triage", "review_summary"])
        self.assertEqual(capability["availability"], "available")
        self.assertEqual(capability["default_time_budget_minutes"], 10)

    def test_active_context_reads_executor_capability_state(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)

        context = build_active_context(state, now=NOW)

        self.assertTrue(context.executor_available)
        self.assertEqual(context.available_capabilities[0]["capability_id"], "cap.external_executor.codex")
        self.assertEqual(context.available_capabilities[0]["executor"], "codex")

    def test_execution_result_updates_work_item_risk_and_followup(self) -> None:
        state = state_with_commitment_and_work_item()
        work_item_id = next(iter(state.domain_state[DOMAIN_KEY]["work_items"]))

        ingest_observation(
            state,
            Observation(
                id="obs.execution.1",
                timestamp=NOW + timedelta(minutes=5),
                observation_type="execution_result_observed",
                source="hermes",
                attributes={
                    "decision_id": "decision.demo.test",
                    "execution_ref": "exec.codex.1",
                    "status": "partial",
                    "acted_on": work_item_id,
                    "elapsed_minutes": 5,
                    "blocking_issue": "tests still failing",
                    "risk_change": "reduced",
                    "followup_needed": True,
                    "summary": "Left a triage note.",
                },
            ),
        )

        demo = state.domain_state[DOMAIN_KEY]
        updated = demo["work_items"][work_item_id]
        self.assertEqual(updated["last_execution_ref"], "exec.codex.1")
        self.assertTrue(updated["followup_needed"])
        self.assertEqual(demo["recent_outcomes"][-1]["status"], "partial")
        self.assertTrue(state.recent_outcomes)

    def test_candidate_registry_and_generation_guards(self) -> None:
        self.assertEqual(
            set(CANDIDATE_REGISTRY),
            {
                "handle_now",
                "quick_triage_then_defer",
                "ignore_temporarily",
                "delegate_to_executor",
                "ask_user",
            },
        )
        state = state_with_commitment_and_work_item()
        context = build_active_context(state, now=NOW)

        report = generate_candidates(context)

        enabled_actions = {item.action_type for item in report.enabled}
        disabled_actions = {item.action_type for item in report.disabled}
        self.assertIn("handle_now", enabled_actions)
        self.assertIn("quick_triage_then_defer", enabled_actions)
        self.assertIn("ignore_temporarily", enabled_actions)
        self.assertIn("delegate_to_executor", disabled_actions)
        self.assertIn("ask_user", disabled_actions)
        delegate = next(item for item in report.disabled if item.action_type == "delegate_to_executor")
        self.assertIn("capability observation", delegate.disabled_reason)

    def test_delegate_enabled_only_with_executor_capability(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        context = build_active_context(state, now=NOW)

        report = generate_candidates(context)

        delegate = next(item for item in report.enabled if item.action_type == "delegate_to_executor")
        self.assertIn("capability observation", delegate.enabled_reason)
        self.assertEqual(delegate.params["executor_capability"]["executor"], "codex")
        self.assertEqual(delegate.params["required_scope"], "triage")

    def test_delegate_disabled_for_unsupported_executor_scope(self) -> None:
        state = state_with_commitment_and_work_item(
            executor_available=True,
            executor_supported_scopes=["review_summary"],
        )
        context = build_active_context(state, now=NOW)

        report = generate_candidates(context)

        delegate = next(item for item in report.disabled if item.action_type == "delegate_to_executor")
        self.assertIn("does not support required scope: triage", delegate.disabled_reason)

    def test_ask_user_enabled_only_for_missing_or_uncertain_context(self) -> None:
        state = state_with_commitment_and_work_item(commitment_confidence=0.4)
        context = build_active_context(state, now=NOW)

        report = generate_candidates(context)

        ask_user = next(item for item in report.enabled if item.action_type == "ask_user")
        self.assertIn("low-confidence", ask_user.enabled_reason)

    def test_simulation_outputs_structured_consequences_for_enabled_candidates(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        policy = DecisionHubCandidatePolicy()

        candidates = policy.propose(state, {"now": NOW})

        self.assertGreaterEqual(len(candidates), 4)
        self.assertEqual(set(policy.latest_consequences), {item.id for item in candidates})
        for consequence in policy.latest_consequences.values():
            payload = consequence.to_payload()
            self.assertIn("expected_time_cost_minutes", payload)
            self.assertIn("commitment_risk", payload)
            self.assertNotIn("recommendation", payload)

    def test_invalid_llm_schema_falls_back_without_recommendation(self) -> None:
        state = state_with_commitment_and_work_item()
        model = FakeSimulationModel(
            {
                "handle_now": {"recommendation": "handle_now"},
                "quick_triage_then_defer": consequence_payload("quick_triage_then_defer"),
                "ignore_temporarily": consequence_payload("ignore_temporarily"),
            }
        )
        policy = DecisionHubCandidatePolicy(StructuredSimulationRunner(model))

        candidates = policy.propose(state, {"now": NOW})
        handle = policy.latest_consequences["cand.handle_now"]

        self.assertEqual(handle.metadata["simulation_source"], "deterministic_fallback")
        self.assertEqual(handle.metadata["fallback_reason"], "invalid_simulation_proposal")
        self.assertNotIn("recommendation", handle.to_payload())
        self.assertEqual({item.action for item in candidates}, {"handle_now", "quick_triage_then_defer", "ignore_temporarily"})

    def test_llm_simulation_env_unconfigured_uses_fallback_runner(self) -> None:
        disabled = build_simulation_runner_from_env(env={SIMULATION_ENABLED_ENV: "0"})
        missing_key = build_simulation_runner_from_env(
            env={
                SIMULATION_ENABLED_ENV: "1",
                SIMULATION_MODEL_ENV: "openrouter:test-model",
            }
        )

        self.assertIsNone(disabled.model)
        self.assertIsNone(missing_key.model)

    def test_llm_simulation_env_configured_builds_demo_adapter(self) -> None:
        runner = build_simulation_runner_from_env(
            env={
                SIMULATION_ENABLED_ENV: "1",
                SIMULATION_MODEL_ENV: "openrouter:test-model",
                OPENROUTER_API_KEY_ENV: "test-key",
            }
        )

        self.assertIsInstance(runner.model, DecisionHubLLMSimulationModel)

    def test_llm_simulation_success_parses_demo_schema(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        context = build_active_context(state, now=NOW)
        candidate = next(
            item
            for item in generate_candidates(context).enabled
            if item.action_type == "quick_triage_then_defer"
        )
        client = FakeLLMClient(llm_consequence_json)
        runner = StructuredSimulationRunner(
            DecisionHubLLMSimulationModel(
                client=client,
                model_override=None,
                model_name="openrouter:test-model",
            )
        )

        consequence = runner.simulate(context, candidate)

        self.assertEqual(consequence.candidate_id, candidate.candidate_id)
        self.assertEqual(consequence.action_type, "quick_triage_then_defer")
        self.assertEqual(consequence.metadata["simulation_source"], "llm")
        self.assertEqual(consequence.metadata["simulation_model"], "test-model")
        self.assertEqual(consequence.metadata["simulation_provider"], "openrouter")
        self.assertFalse(consequence.metadata["llm_recommendation_allowed"])
        self.assertEqual(client.requests[0][0].response_format_hint, "json_object")
        self.assertNotIn("recommendation", consequence.to_payload())

    def test_non_json_llm_output_falls_back(self) -> None:
        state = state_with_commitment_and_work_item()
        context = build_active_context(state, now=NOW)
        candidate = generate_candidates(context).enabled[0]
        runner = StructuredSimulationRunner(
            DecisionHubLLMSimulationModel(
                client=FakeLLMClient("not json"),
                model_override=None,
                model_name="openrouter:test-model",
            )
        )

        consequence = runner.simulate(context, candidate)

        self.assertEqual(consequence.metadata["simulation_source"], "deterministic_fallback")
        self.assertEqual(consequence.metadata["fallback_reason"], "simulation_model_failed")

    def test_forbidden_nested_llm_output_falls_back(self) -> None:
        state = state_with_commitment_and_work_item()
        context = build_active_context(state, now=NOW)
        candidate = generate_candidates(context).enabled[0]
        payload = consequence_payload(candidate.action_type)
        payload["candidate_id"] = candidate.candidate_id
        payload["selected_action"] = candidate.action_type
        runner = StructuredSimulationRunner(
            DecisionHubLLMSimulationModel(
                client=FakeLLMClient(json.dumps({"consequence": payload})),
                model_override=None,
                model_name="openrouter:test-model",
            )
        )

        consequence = runner.simulate(context, candidate)

        self.assertEqual(consequence.metadata["simulation_source"], "deterministic_fallback")
        self.assertEqual(consequence.metadata["fallback_reason"], "invalid_simulation_proposal")

    def test_forbidden_llm_output_inside_metadata_falls_back(self) -> None:
        state = state_with_commitment_and_work_item()
        context = build_active_context(state, now=NOW)
        candidate = generate_candidates(context).enabled[0]
        payload = consequence_payload(candidate.action_type)
        payload["candidate_id"] = candidate.candidate_id
        payload["metadata"] = {"recommendation": "choose this candidate"}
        runner = StructuredSimulationRunner(
            DecisionHubLLMSimulationModel(
                client=FakeLLMClient(json.dumps(payload)),
                model_override=None,
                model_name="openrouter:test-model",
            )
        )

        consequence = runner.simulate(context, candidate)

        self.assertEqual(consequence.metadata["simulation_source"], "deterministic_fallback")
        self.assertEqual(consequence.metadata["fallback_reason"], "invalid_simulation_proposal")

    def test_candidate_mismatch_llm_output_falls_back(self) -> None:
        state = state_with_commitment_and_work_item()
        context = build_active_context(state, now=NOW)
        candidate = generate_candidates(context).enabled[0]
        payload = consequence_payload(candidate.action_type)
        payload["candidate_id"] = "cand.wrong"
        runner = StructuredSimulationRunner(
            DecisionHubLLMSimulationModel(
                client=FakeLLMClient(json.dumps(payload)),
                model_override=None,
                model_name="openrouter:test-model",
            )
        )

        consequence = runner.simulate(context, candidate)

        self.assertEqual(consequence.metadata["simulation_source"], "deterministic_fallback")
        self.assertEqual(consequence.metadata["fallback_reason"], "invalid_simulation_proposal")

    def test_llm_trace_marks_source_and_guided_policy_still_selects(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        runner = DecisionHubRecommendationRunner(
            simulation_runner=StructuredSimulationRunner(
                DecisionHubLLMSimulationModel(
                    client=FakeLLMClient(llm_consequence_json),
                    model_override=None,
                    model_name="openrouter:test-model",
                )
            )
        )

        result = runner.recommend(state, {"now": NOW})

        sources = {
            item["metadata"]["simulation_source"]
            for item in result["trace"]["candidate_consequences"].values()
        }
        self.assertEqual(sources, {"llm"})
        self.assertEqual(result["recommendation_source"], "GuidedDecisionPolicy")
        self.assertFalse(result["llm_direct_recommendation"])

    def test_run_demo_uses_env_aware_simulation_runner(self) -> None:
        from examples.decision_hub_demo.run_demo import run_path

        env = {
            SIMULATION_ENABLED_ENV: "1",
            SIMULATION_MODEL_ENV: "openrouter:test-model",
            OPENROUTER_API_KEY_ENV: "test-key",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "examples.decision_hub_demo.llm_simulation._build_llm_client",
            return_value=FakeLLMClient(llm_consequence_json),
        ):
            result = run_path("details", now=NOW)

        recommendation = result["control"]["recommendation"]
        sources = {
            item["metadata"]["simulation_source"]
            for item in recommendation["trace"]["candidate_consequences"].values()
        }
        self.assertEqual(sources, {"llm"})

    def test_delegate_and_ask_user_consequences_are_comparable(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True, commitment_confidence=0.4)
        policy = DecisionHubCandidatePolicy()

        policy.propose(state, {"now": NOW})

        delegate = policy.latest_consequences["cand.delegate_to_executor"]
        ask_user = policy.latest_consequences["cand.ask_user"]
        self.assertEqual(delegate.metadata["executor_available"], True)
        self.assertEqual(delegate.metadata["executor"], "codex")
        self.assertEqual(delegate.metadata["capability_id"], "cap.external_executor.codex")
        self.assertEqual(delegate.metadata["supported_scopes"], ["triage", "review_summary"])
        self.assertEqual(delegate.metadata["default_time_budget_minutes"], 10)
        self.assertEqual(delegate.executor_load, "medium")
        self.assertTrue(delegate.followup_needed)
        self.assertEqual(ask_user.work_item_risk_change, "unchanged")
        self.assertEqual(ask_user.metadata["uncertainty_reduction"], "high")

    def test_guided_selection_uses_decision_md_trace_and_not_llm_recommendation(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        runner = DecisionHubRecommendationRunner()

        result = runner.recommend(state, {"now": NOW})

        self.assertRegex(
            result["decision_id"],
            r"^decision\.2026-04-17T06:00:00Z\.workitem_.*\.[0-9a-f]{8}$",
        )
        self.assertTrue(result["trace_ref"].startswith("trace."))
        self.assertEqual(get_trace(result["trace_ref"])["decision_id"], result["decision_id"])
        self.assertEqual(result["selected_action"], "delegate_to_executor")
        self.assertIn("human_summary", result)
        self.assertTrue(result["requires_confirmation"])
        self.assertIn("executor available", result["reason_summary"])
        self.assertEqual(result["recommendation_source"], "GuidedDecisionPolicy")
        self.assertFalse(result["llm_direct_recommendation"])
        self.assertIn("prefer_delegate_when_executor_available_and_time_pressure", result["tradeoff_rules_applied"])
        self.assertTrue(result["simulation_refs"])
        self.assertIn("cand.handle_now", result["trace"]["candidate_scores"])
        vetoed = {
            item["candidate_id"]
            for item in result["veto_reasons"]
        }
        self.assertIn("cand.handle_now", vetoed)
        self.assertIn("cand.ignore_temporarily", vetoed)

    def test_execution_request_schema_binds_decision_id_and_action(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        recommendation = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})

        request = build_execution_request(recommendation, executor="codex", now=NOW)

        payload = request.to_payload()
        self.assertTrue(payload["execution_id"].startswith("exec.2026-04-17T06:00:00Z."))
        self.assertEqual(payload["decision_id"], recommendation["decision_id"])
        self.assertEqual(payload["action_type"], "delegate_to_executor")
        self.assertEqual(payload["acted_on"], recommendation["acted_on"])
        self.assertEqual(payload["executor"], "codex")
        self.assertEqual(payload["params"]["scope"], "triage")
        self.assertEqual(payload["params"]["time_budget_minutes"], 10)
        self.assertEqual(payload["params"]["target_title"], "Fix decision guidance validation")
        self.assertEqual(payload["params"]["target_url"], "https://github.com/Dyalwayshappy/Spice/pull/123")
        self.assertIn("status", payload["params"]["success_criteria"])
        self.assertEqual(payload["params"]["trace_ref"], recommendation["trace_ref"])

    def test_execution_outcome_maps_to_execution_result_observation(self) -> None:
        request = demo_execution_request()

        for status in ("success", "failed", "partial", "abandoned"):
            outcome = demo_execution_outcome(status=status)
            observation = execution_outcome_to_observation(
                request=request,
                outcome=outcome,
                selected_action="delegate_to_executor",
                now=NOW,
            )

            self.assertEqual(observation.observation_type, "execution_result_observed")
            self.assertEqual(observation.source, "codex")
            self.assertEqual(observation.attributes["execution_id"], request.execution_id)
            self.assertEqual(observation.attributes["decision_id"], request.decision_id)
            self.assertEqual(observation.attributes["trace_ref"], request.params["trace_ref"])
            self.assertEqual(observation.attributes["acted_on"], request.acted_on)
            self.assertEqual(observation.attributes["selected_action"], "delegate_to_executor")
            self.assertEqual(observation.attributes["status"], status)
            self.assertEqual(observation.attributes["execution_ref"], outcome.execution_ref)
            self.assertEqual(observation.metadata["provenance"]["execution_id"], request.execution_id)
            self.assertEqual(observation.metadata["provenance"]["outcome_status"], status)
            self.assertEqual(observation.metadata["outcome_metadata"]["executor"], "codex")

    def test_protocol_error_execution_outcome_maps_to_failed_observation(self) -> None:
        request = demo_execution_request()
        outcome = sdep_response_to_execution_outcome(
            request,
            protocol_error_sdep_response(request),
        )

        observation = execution_outcome_to_observation(
            request=request,
            outcome=outcome,
            selected_action="delegate_to_executor",
            now=NOW,
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(observation.attributes["status"], "failed")
        self.assertEqual(observation.attributes["blocking_issue"], "hermes.timeout")
        self.assertEqual(observation.metadata["provenance"]["sdep_response_status"], "error")
        self.assertEqual(
            observation.metadata["provenance"]["protocol_error"]["details"]["timeout_seconds"],
            30,
        )
        self.assertEqual(
            observation.metadata["outcome_metadata"]["sdep_error"]["code"],
            "hermes.timeout",
        )

    def test_reducer_consumes_execution_outcome_observations_without_sdep_awareness(self) -> None:
        success_state = state_with_commitment_and_work_item()
        success_work_item_id = next(iter(success_state.domain_state[DOMAIN_KEY]["work_items"]))
        success_request = demo_execution_request(acted_on=success_work_item_id)
        ingest_observation(
            success_state,
            execution_outcome_to_observation(
                request=success_request,
                outcome=demo_execution_outcome(status="success", followup_needed=False),
                selected_action="handle_now",
                now=NOW,
            ),
        )
        success_item = success_state.domain_state[DOMAIN_KEY]["work_items"][success_work_item_id]
        self.assertEqual(success_item["last_execution_status"], "success")
        self.assertEqual(success_item["status"], "closed")

        partial_state = state_with_commitment_and_work_item()
        partial_work_item_id = next(iter(partial_state.domain_state[DOMAIN_KEY]["work_items"]))
        partial_request = demo_execution_request(acted_on=partial_work_item_id)
        ingest_observation(
            partial_state,
            execution_outcome_to_observation(
                request=partial_request,
                outcome=demo_execution_outcome(status="partial", followup_needed=True),
                selected_action="quick_triage_then_defer",
                now=NOW,
            ),
        )
        partial_item = partial_state.domain_state[DOMAIN_KEY]["work_items"][partial_work_item_id]
        self.assertEqual(partial_item["last_execution_status"], "partial")
        self.assertEqual(partial_item["status"], "open")

        failed_state = state_with_commitment_and_work_item()
        failed_work_item_id = next(iter(failed_state.domain_state[DOMAIN_KEY]["work_items"]))
        failed_request = demo_execution_request(acted_on=failed_work_item_id)
        ingest_observation(
            failed_state,
            execution_outcome_to_observation(
                request=failed_request,
                outcome=demo_execution_outcome(status="failed", followup_needed=True),
                selected_action="delegate_to_executor",
                now=NOW,
            ),
        )
        failed_item = failed_state.domain_state[DOMAIN_KEY]["work_items"][failed_work_item_id]
        self.assertEqual(failed_item["last_execution_status"], "failed")
        self.assertEqual(failed_item["status"], "open")

        abandoned_state = state_with_commitment_and_work_item()
        abandoned_work_item_id = next(iter(abandoned_state.domain_state[DOMAIN_KEY]["work_items"]))
        abandoned_request = demo_execution_request(acted_on=abandoned_work_item_id)
        ingest_observation(
            abandoned_state,
            execution_outcome_to_observation(
                request=abandoned_request,
                outcome=demo_execution_outcome(status="abandoned", followup_needed=True),
                selected_action="ignore_temporarily",
                now=NOW,
            ),
        )
        abandoned_item = abandoned_state.domain_state[DOMAIN_KEY]["work_items"][abandoned_work_item_id]
        self.assertEqual(abandoned_item["last_execution_status"], "abandoned")
        self.assertEqual(abandoned_item["status"], "open")

    def test_execution_feedback_loop_updates_world_state_through_observation(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        recommendation = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})
        acted_on = recommendation["acted_on"]
        transport = CapturingSDEPTransport()

        feedback = ExecutionFeedbackAdapter(executor=SDEPBackedExecutor(transport)).execute_and_apply(
            state,
            recommendation,
            now=NOW + timedelta(minutes=6),
            confirmed=True,
        )

        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.requests[0].execution.action_type, SDEP_DELEGATE_ACTION_TYPE)
        self.assertEqual(feedback.status, "applied")
        self.assertTrue(feedback.state_updated)
        self.assertIsNotNone(feedback.execution_request)
        self.assertIsNotNone(feedback.outcome)
        self.assertIsNotNone(feedback.observation)
        assert feedback.observation is not None
        self.assertEqual(feedback.observation["observation_type"], "execution_result_observed")
        self.assertEqual(feedback.observation["attributes"]["decision_id"], recommendation["decision_id"])
        self.assertEqual(feedback.observation["attributes"]["selected_action"], "delegate_to_executor")

        demo = state.domain_state[DOMAIN_KEY]
        updated = demo["work_items"][acted_on]
        self.assertEqual(updated["last_decision_id"], recommendation["decision_id"])
        self.assertEqual(updated["last_selected_action"], "delegate_to_executor")
        self.assertEqual(updated["last_execution_status"], "success")
        self.assertEqual(updated["status"], "open")
        self.assertTrue(updated["followup_needed"])
        self.assertEqual(demo["recent_outcomes"][-1]["decision_id"], recommendation["decision_id"])
        self.assertEqual(demo["recent_outcomes"][-1]["selected_action"], "delegate_to_executor")

    def test_sdep_execution_feedback_handles_failed_and_partial_without_crashing(self) -> None:
        for outcome_status in ("failed", "partial"):
            with self.subTest(outcome_status=outcome_status):
                state = state_with_commitment_and_work_item(executor_available=True)
                recommendation = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})
                acted_on = recommendation["acted_on"]
                transport = CapturingSDEPTransport(outcome_status=outcome_status)

                feedback = ExecutionFeedbackAdapter(executor=SDEPBackedExecutor(transport)).execute_and_apply(
                    state,
                    recommendation,
                    now=NOW + timedelta(minutes=6),
                    confirmed=True,
                )

                self.assertEqual(feedback.status, "applied")
                self.assertEqual(len(transport.requests), 1)
                self.assertIsNotNone(feedback.outcome)
                assert feedback.outcome is not None
                self.assertEqual(feedback.outcome["status"], outcome_status)
                demo = state.domain_state[DOMAIN_KEY]
                updated = demo["work_items"][acted_on]
                self.assertEqual(updated["last_execution_status"], outcome_status)
                self.assertEqual(updated["status"], "open")

    def test_requires_confirmation_blocks_direct_execution(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        recommendation = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})

        feedback = ExecutionFeedbackAdapter().execute_and_apply(
            state,
            recommendation,
            now=NOW + timedelta(minutes=6),
        )

        self.assertEqual(feedback.status, "confirmation_required")
        self.assertFalse(feedback.state_updated)
        self.assertIsNone(feedback.execution_request)

    def test_delegate_recommendation_generates_confirmation_request(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        recommendation = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})
        loop = DecisionControlLoop()

        result = loop.handle_recommendation(state, recommendation, now=NOW)

        self.assertEqual(result.status, "confirmation_required")
        self.assertIsNotNone(result.confirmation_request)
        assert result.confirmation_request is not None
        self.assertTrue(result.confirmation_request["confirmation_id"].startswith("confirm."))
        self.assertEqual(result.confirmation_request["decision_id"], recommendation["decision_id"])
        self.assertEqual(result.confirmation_request["selected_action"], "delegate_to_executor")
        self.assertEqual(result.confirmation_request["options"][0]["value"], "confirm")
        self.assertFalse(result.state_updated)

    def test_confirmation_confirm_executes_and_updates_state(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        recommendation = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})
        transport = CapturingSDEPTransport()
        with patch(
            "examples.decision_hub_demo.sdep_executor.create_default_sdep_executor",
            return_value=SDEPBackedExecutor(transport),
        ):
            loop = DecisionControlLoop()
        pending = loop.handle_recommendation(state, recommendation, now=NOW)
        assert pending.confirmation_request is not None

        resolution = loop.resolve_confirmation(
            state,
            pending.confirmation_request["confirmation_id"],
            choice="confirm",
            now=NOW + timedelta(minutes=6),
        )

        self.assertEqual(resolution.status, "executed")
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.requests[0].execution.action_type, SDEP_DELEGATE_ACTION_TYPE)
        self.assertTrue(resolution.state_updated)
        self.assertIsNotNone(resolution.execution)
        record = loop.confirmation_store.get(pending.confirmation_request["confirmation_id"])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "confirmed")
        demo = state.domain_state[DOMAIN_KEY]
        self.assertEqual(demo["recent_outcomes"][-1]["decision_id"], recommendation["decision_id"])

    def test_confirmation_reject_does_not_execute(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        recommendation = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})
        loop = DecisionControlLoop()
        pending = loop.handle_recommendation(state, recommendation, now=NOW)
        assert pending.confirmation_request is not None

        resolution = loop.resolve_confirmation(
            state,
            pending.confirmation_request["confirmation_id"],
            choice="reject",
            now=NOW + timedelta(minutes=1),
        )

        self.assertEqual(resolution.status, "rejected")
        self.assertFalse(resolution.state_updated)
        self.assertIsNone(resolution.execution)
        self.assertEqual(state.domain_state[DOMAIN_KEY]["recent_outcomes"], [])
        record = loop.confirmation_store.get(pending.confirmation_request["confirmation_id"])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "rejected")

    def test_confirmation_details_does_not_execute_and_returns_explanation(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        recommendation = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})
        loop = DecisionControlLoop()
        pending = loop.handle_recommendation(state, recommendation, now=NOW)
        assert pending.confirmation_request is not None

        resolution = loop.resolve_confirmation(
            state,
            pending.confirmation_request["confirmation_id"],
            choice="details",
            now=NOW + timedelta(minutes=1),
        )

        self.assertEqual(resolution.status, "details")
        self.assertFalse(resolution.state_updated)
        self.assertIsNone(resolution.execution)
        self.assertIsNotNone(resolution.details)
        assert resolution.details is not None
        self.assertEqual(resolution.details["decision_id"], recommendation["decision_id"])
        self.assertTrue(resolution.details["trace_available"])
        self.assertEqual(state.domain_state[DOMAIN_KEY]["recent_outcomes"], [])
        record = loop.confirmation_store.get(pending.confirmation_request["confirmation_id"])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "pending")

    def test_confirmation_formatter_is_whatsapp_friendly(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=True)
        recommendation = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})
        request = create_confirmation_request(recommendation, now=NOW)

        message = format_confirmation_for_whatsapp(request)

        self.assertIn("我建议执行", message)
        self.assertIn("delegate_to_executor", message)
        self.assertIn("1 同意执行", message)
        self.assertIn("2 拒绝", message)
        self.assertIn("3 查看详情", message)

    def test_ask_user_does_not_trigger_execution(self) -> None:
        feedback = ExecutionFeedbackAdapter().execute_and_apply(
            new_world_state(),
            {
                "decision_id": "decision.2026-04-17T06:00:00Z.none.askuser01",
                "selected_action": "ask_user",
                "acted_on": None,
                "recommendation": "ask_user",
                "trace_ref": "trace.ask_user",
            },
            now=NOW,
        )

        self.assertEqual(feedback.status, "skipped")
        self.assertFalse(feedback.state_updated)
        self.assertIsNone(feedback.execution_request)
        self.assertIsNone(feedback.observation)

    def test_ask_user_control_loop_returns_prompt_without_execution(self) -> None:
        result = DecisionControlLoop().handle_recommendation(
            new_world_state(),
            {
                "decision_id": "decision.2026-04-17T06:00:00Z.none.askuser01",
                "selected_action": "ask_user",
                "acted_on": None,
                "recommendation": "ask_user",
                "trace_ref": "trace.ask_user",
                "human_summary": "Ask the user for missing information before acting.",
                "reason_summary": ["reduces uncertainty before execution"],
                "requires_confirmation": False,
            },
            now=NOW,
        )

        self.assertEqual(result.status, "ask_user")
        self.assertIsNotNone(result.ask_user)
        self.assertIsNone(result.execution)
        self.assertFalse(result.state_updated)

    def test_delegate_does_not_participate_without_executor_capability(self) -> None:
        state = state_with_commitment_and_work_item(executor_available=False)

        result = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})

        self.assertNotEqual(result["selected_action"], "delegate_to_executor")
        enabled_actions = {
            item["action_type"]
            for item in result["trace"]["candidate_generation"]["enabled"]
        }
        disabled = {
            item["action_type"]: item["disabled_reason"]
            for item in result["trace"]["candidate_generation"]["disabled"]
        }
        self.assertNotIn("delegate_to_executor", enabled_actions)
        self.assertIn("capability observation", disabled["delegate_to_executor"])

    def test_selection_does_not_pick_delegate_when_scope_unsupported(self) -> None:
        state = state_with_commitment_and_work_item(
            executor_available=True,
            executor_supported_scopes=["review_summary"],
        )

        result = DecisionHubRecommendationRunner().recommend(state, {"now": NOW})

        self.assertNotEqual(result["selected_action"], "delegate_to_executor")
        disabled = {
            item["action_type"]: item["disabled_reason"]
            for item in result["trace"]["candidate_generation"]["disabled"]
        }
        self.assertIn("does not support required scope", disabled["delegate_to_executor"])

    def test_run_demo_uses_capability_observation_not_manual_flag(self) -> None:
        source = Path("examples/decision_hub_demo/run_demo.py").read_text()

        self.assertIn("executor_capability_observed", source)
        self.assertNotIn("external_executor_available", source)

    def test_decision_md_weights_affect_candidate_ranking(self) -> None:
        state = state_with_commitment_and_work_item()
        work_guidance = parse_decision_guidance(weight_guidance(work_item_weight=0.80, attention_weight=0.05))
        attention_guidance = parse_decision_guidance(weight_guidance(work_item_weight=0.05, attention_weight=0.80))

        work_result = DecisionHubRecommendationRunner(guidance=work_guidance).recommend(state, {"now": NOW})
        attention_result = DecisionHubRecommendationRunner(guidance=attention_guidance).recommend(state, {"now": NOW})

        self.assertEqual(work_result["selected_action"], "quick_triage_then_defer")
        self.assertEqual(attention_result["selected_action"], "ignore_temporarily")
        self.assertFalse(work_result["requires_confirmation"])
        self.assertFalse(attention_result["requires_confirmation"])
        self.assertNotEqual(work_result["selected_action"], attention_result["selected_action"])

    def test_ignore_temporarily_control_loop_is_noop(self) -> None:
        state = state_with_commitment_and_work_item()
        attention_guidance = parse_decision_guidance(weight_guidance(work_item_weight=0.05, attention_weight=0.80))
        recommendation = DecisionHubRecommendationRunner(guidance=attention_guidance).recommend(state, {"now": NOW})

        result = DecisionControlLoop().handle_recommendation(state, recommendation, now=NOW)

        self.assertEqual(recommendation["selected_action"], "ignore_temporarily")
        self.assertFalse(recommendation["requires_confirmation"])
        self.assertEqual(result.status, "no_execution")
        self.assertFalse(result.state_updated)
        self.assertIsNone(result.execution)

    def test_demo_decision_md_loads_with_supported_contract(self) -> None:
        self.assertTrue(Path(DEMO_DECISION_MD).exists())
        result = DecisionHubRecommendationRunner().recommend(
            state_with_commitment_and_work_item(executor_available=True),
            {"now": NOW},
        )

        guidance_artifact = result["trace"]["guidance_artifact"]
        self.assertEqual(
            guidance_artifact["artifact_id"],
            "decision.decision_hub_demo.commitment_work_item_conflict",
        )


def state_with_commitment_and_work_item(
    *,
    executor_available: bool = False,
    executor_supported_scopes: list[str] | None = None,
    executor_availability: str = "available",
    commitment_confidence: float = 1.0,
) -> Any:
    state = new_world_state()
    if executor_available:
        ingest_observation(
            state,
            executor_capability_obs(
                supported_scopes=executor_supported_scopes,
                availability=executor_availability,
            ),
        )
    ingest_observation(
        state,
        commitment_obs(
            "commitment.flight",
            start=NOW + timedelta(minutes=42),
            end=NOW + timedelta(minutes=102),
            prep=NOW + timedelta(minutes=12),
            confidence=commitment_confidence,
        ),
    )
    ingest_observation(state, work_item_obs())
    return state


def demo_execution_request(
    *,
    acted_on: str = "workitem.github.pr_123",
) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id="exec.2026-04-17T06:00:00Z.delegate.ab12",
        decision_id="decision.2026-04-17T06:00:00Z.workitem.github_pr_123.ab12",
        action_type="delegate_to_executor",
        acted_on=acted_on,
        params={
            "scope": "triage",
            "time_budget_minutes": 10,
            "target_title": "Fix decision guidance validation",
            "target_url": "https://github.com/Dyalwayshappy/Spice/pull/123",
            "success_criteria": "Return status, blocker, risk_change, followup_needed",
            "trace_ref": "trace.decision.ab12",
        },
        executor="codex",
        created_at="2026-04-17T06:00:00Z",
    )


def demo_execution_outcome(
    *,
    status: str,
    followup_needed: bool | None = None,
) -> ExecutionOutcome:
    default_followup = status in {"failed", "partial", "abandoned"}
    return ExecutionOutcome(
        status=status,
        elapsed_minutes=6 if status != "abandoned" else 0,
        risk_change="reduced" if status in {"success", "partial"} else "increased",
        followup_needed=default_followup if followup_needed is None else followup_needed,
        summary=f"Demo execution ended with status {status}.",
        execution_ref=f"codex.exec.{status}",
        blocking_issue="demo_blocker" if status == "failed" else None,
        metadata={
            "executor": "codex",
            "adapter": "test",
        },
    )


def protocol_error_sdep_response(request: ExecutionRequest) -> dict[str, Any]:
    return {
        "protocol": "sdep",
        "sdep_version": "0.1",
        "message_type": "execute.response",
        "message_id": "sdep-msg-test",
        "request_id": "sdep-req-test",
        "timestamp": "2026-04-17T06:00:01+00:00",
        "responder": {
            "id": "agent.hermes",
            "name": "Hermes SDEP Executor",
            "version": "0.1",
            "implementation": "hermes-codex",
            "role": "executor",
        },
        "status": "error",
        "outcome": {
            "execution_id": "hermes.exec.failed",
            "status": "failed",
            "outcome_type": "observation",
            "output": {
                "status": "failed",
                "summary": "Hermes timed out before producing an outcome.",
            },
            "artifacts": [],
            "metrics": {},
            "metadata": {},
        },
        "error": {
            "code": "hermes.timeout",
            "message": "Hermes timed out after 30 seconds.",
            "retryable": True,
            "details": {"timeout_seconds": 30},
        },
        "traceability": {
            "execution_id": request.execution_id,
            "spice_decision_id": request.decision_id,
            "trace_ref": request.params["trace_ref"],
            "acted_on": request.acted_on,
        },
        "metadata": {"wrapper": "hermes_sdep_agent"},
    }


def executor_capability_obs(
    *,
    supported_scopes: list[str] | None = None,
    availability: str = "available",
) -> Observation:
    return Observation(
        id="obs.capability.codex",
        timestamp=NOW,
        observation_type="executor_capability_observed",
        source="hermes",
        metadata={
            "adapter": "hermes_capability.v1",
            "reported_by": "hermes",
            "notes": "Codex available via Hermes terminal/codex skill.",
        },
        attributes={
            "capability_id": "cap.external_executor.codex",
            "action_type": "delegate_to_executor",
            "executor": "codex",
            "supported_scopes": supported_scopes or ["triage", "review_summary"],
            "requires_confirmation": True,
            "reversible": True,
            "default_time_budget_minutes": 10,
            "availability": availability,
        },
    )


def commitment_obs(
    commitment_id: str,
    *,
    start: datetime,
    end: datetime,
    prep: datetime | None = None,
    confidence: float = 1.0,
) -> Observation:
    return Observation(
        id=f"obs.{commitment_id}",
        timestamp=NOW,
        observation_type="commitment_declared",
        source="whatsapp",
        metadata={"confidence": confidence},
        attributes={
            "commitment_id": commitment_id,
            "summary": "Airport departure",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "duration_minutes": int((end - start).total_seconds() // 60),
            "prep_start_time": prep.isoformat() if prep else None,
            "priority_hint": "high",
            "flexibility_hint": "fixed",
            "constraint_hints": ["do_not_be_late"],
        },
    )


def work_item_obs() -> Observation:
    return Observation(
        id="obs.github.pr.123.opened",
        timestamp=NOW,
        observation_type="work_item_opened",
        source="github",
        attributes={
            "kind": "pull_request",
            "repo": "Dyalwayshappy/Spice",
            "item_id": "123",
            "title": "Fix decision guidance validation",
            "url": "https://github.com/Dyalwayshappy/Spice/pull/123",
            "action": "opened",
            "urgency_hint": "medium",
            "estimated_minutes_hint": 30,
            "requires_attention": True,
            "event_key": "github:Dyalwayshappy/Spice:pull_request:123:opened",
        },
    )


def consequence_payload(action: str) -> dict[str, Any]:
    return {
        "candidate_id": f"cand.{action}",
        "action_type": action,
        "expected_time_cost_minutes": 5,
        "commitment_risk": "low",
        "work_item_risk_change": "reduced",
        "reversibility": "high",
        "attention_cost": "low",
        "followup_needed": True,
        "followup_summary": "Synthetic consequence.",
        "executor_load": "none",
        "requires_confirmation": False,
        "confidence": 0.8,
        "assumptions": [],
    }


def weight_guidance(*, work_item_weight: float, attention_weight: float) -> str:
    return f"""# decision.md

## Primary Objective

```md
Primary Objective:
Maximize guided candidate utility.
```

## Preferences / Weights

```md
Preferences:
- work_item_risk_reduction: {work_item_weight}
- attention_preservation: {attention_weight}
```

## Hard Constraints

```md
Hard Constraints:
```

## Trade-off Rules

```md
Rule Priority:
1. hard constraints
```

```md
Trade-off Rules:
```

## Version / Metadata

```md
Version:
- artifact_id: decision.test.weights
- schema_version: 0.1
- artifact_version: 0.1.0
- status: test
```
"""


if __name__ == "__main__":
    unittest.main()
