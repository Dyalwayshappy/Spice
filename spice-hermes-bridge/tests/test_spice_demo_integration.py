from __future__ import annotations

import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from typing import Any
from unittest.mock import patch

from spice.llm.core import LLMResponse

from examples.decision_hub_demo.llm_simulation import (
    OPENROUTER_API_KEY_ENV,
    SIMULATION_ENABLED_ENV,
    SIMULATION_MODEL_ENV,
)
from examples.decision_hub_demo.execution_adapter import (
    ExecutionOutcome,
    ExecutionRequest,
    build_execution_request,
)
from examples.decision_hub_demo.sdep_executor import SDEPBackedExecutor, SDEP_DELEGATE_ACTION_TYPE
from examples.decision_hub_demo.state import DOMAIN_KEY

from spice_hermes_bridge.integrations.hermes_executor import (
    build_hermes_codex_prompt,
    normalize_hermes_output,
)
from spice_hermes_bridge.integrations.spice_demo import (
    SpiceDemoSession,
    bridge_observation_to_spice,
    run_sample_flow,
    sample_bridge_observations,
)
from spice_hermes_bridge.integrations.whatsapp_reply import (
    format_confirmation_resolution_for_whatsapp,
    format_control_result_for_whatsapp,
)
from spice_hermes_bridge.observations import build_observation
from spice_hermes_bridge.cli import main as bridge_main


NOW = datetime(2026, 4, 17, 6, 0, tzinfo=timezone.utc)


class CapturingExecutor:
    name = "codex"

    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        self.requests.append(request)
        return ExecutionOutcome(
            status="success",
            elapsed_minutes=6,
            risk_change="reduced",
            followup_needed=True,
            summary="PR triaged, no blocking issue.",
            execution_ref=f"capture.{request.execution_id}",
            metadata={"executor": self.name, "mode": "test"},
        )


class CapturingSDEPTransport:
    def __init__(
        self,
        *,
        outcome_status: str = "success",
        response_status: str = "success",
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        outcome_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.outcome_status = outcome_status
        self.response_status = response_status
        self.output = output
        self.error = error
        self.outcome_metadata = outcome_metadata
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return sdep_response_for_request(
            request,
            outcome_status=self.outcome_status,
            response_status=self.response_status,
            output=self.output,
            error=self.error,
            outcome_metadata=self.outcome_metadata,
        )


def sdep_response_for_request(
    request,
    *,
    outcome_status: str = "success",
    response_status: str = "success",
    output: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    outcome_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_status = outcome_status if response_status == "success" else "failed"
    risk_change = "reduced" if output_status in {"success", "partial"} else "increased"
    default_output = {
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
    }
    if output is not None:
        default_output.update(output)
    default_error = None
    if response_status != "success":
        default_error = {
            "code": "sdep.protocol_error",
            "message": "SDEP transport failed.",
            "retryable": True,
            "details": {},
        }
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
            "output": default_output,
            "artifacts": [],
            "metrics": {"elapsed_minutes": 6},
            "metadata": outcome_metadata or {"executor": "codex"},
        },
        "error": None if response_status == "success" else (error or default_error),
        "traceability": dict(request.traceability),
        "metadata": {"wrapper": "test_sdep_transport"},
    }


class FakeLLMClient:
    def __init__(self) -> None:
        self.requests = []

    def generate(self, request, *, model_override=None) -> LLMResponse:
        self.requests.append((request, model_override))
        action = str(request.metadata["action_type"])
        candidate_id = str(request.metadata["candidate_id"])
        payload = {
            "candidate_id": candidate_id,
            "action_type": action,
            "expected_time_cost_minutes": 10 if action == "delegate_to_executor" else 5,
            "commitment_risk": "low",
            "work_item_risk_change": "reduced" if action != "ignore_temporarily" else "increased",
            "reversibility": "high",
            "attention_cost": "low",
            "followup_needed": True,
            "followup_summary": "Fake LLM consequence for integration test.",
            "executor_load": "medium" if action == "delegate_to_executor" else "none",
            "requires_confirmation": action == "delegate_to_executor",
            "confidence": 0.81,
            "assumptions": ["fake llm integration test"],
            "metadata": {"from_fake_llm": True},
        }
        return LLMResponse(
            provider_id="openrouter",
            model_id="test-model",
            output_text=json.dumps(payload),
            raw_payload={},
            finish_reason="stop",
            usage={},
            latency_ms=1,
            request_id="fake-request",
        )


class SpiceDemoIntegrationTest(unittest.TestCase):
    def test_bridge_observation_ingests_into_spice_demo_reducer(self) -> None:
        session = SpiceDemoSession(executor=CapturingExecutor())

        spice_observations = session.ingest_many(sample_bridge_observations(now=NOW))

        self.assertEqual(len(spice_observations), 3)
        demo = session.state.domain_state[DOMAIN_KEY]
        self.assertEqual(len(demo["capabilities"]), 1)
        self.assertEqual(len(demo["commitments"]), 1)
        self.assertEqual(len(demo["work_items"]), 1)

    def test_bridge_observation_conversion_validates_schema(self) -> None:
        observation = build_observation(
            observation_type="executor_capability_observed",
            source="hermes",
            observed_at=NOW.isoformat(),
            attributes={
                "capability_id": "cap.external_executor.codex",
                "action_type": "delegate_to_executor",
                "executor": "codex",
                "supported_scopes": ["triage"],
                "requires_confirmation": True,
                "reversible": True,
                "default_time_budget_minutes": 10,
                "availability": "available",
            },
            provenance={"adapter": "hermes_capability.v1"},
        )

        spice_observation = bridge_observation_to_spice(observation)

        self.assertEqual(spice_observation.observation_type, "executor_capability_observed")
        self.assertEqual(spice_observation.metadata["bridge_observation_id"], observation.observation_id)

    def test_spice_recommendation_generates_confirmation_request(self) -> None:
        session = SpiceDemoSession(executor=CapturingExecutor())
        session.ingest_many(sample_bridge_observations(now=NOW))

        recommendation = session.recommend(now=NOW)
        control = session.handle_recommendation(recommendation, now=NOW)
        text = format_control_result_for_whatsapp(control)

        self.assertEqual(recommendation["selected_action"], "delegate_to_executor")
        self.assertTrue(recommendation["requires_confirmation"])
        self.assertEqual(control.status, "confirmation_required")
        self.assertIn("1 同意执行", text)
        self.assertIn("3 查看详情", text)

    def test_confirm_enters_execution_and_updates_state(self) -> None:
        executor = CapturingExecutor()
        session = SpiceDemoSession(executor=executor)
        session.ingest_many(sample_bridge_observations(now=NOW))
        recommendation = session.recommend(now=NOW)
        control = session.handle_recommendation(recommendation, now=NOW)

        resolution = session.resolve_confirmation(
            str(control.confirmation_request["confirmation_id"]),
            choice="confirm",
            now=NOW,
        )

        self.assertEqual(resolution.status, "executed")
        self.assertEqual(len(executor.requests), 1)
        self.assertEqual(executor.requests[0].decision_id, recommendation["decision_id"])
        self.assertEqual(executor.requests[0].params["scope"], "triage")
        updated = session.latest_work_item(recommendation)
        self.assertEqual(updated["last_decision_id"], recommendation["decision_id"])
        self.assertEqual(updated["last_selected_action"], "delegate_to_executor")
        self.assertTrue(updated["followup_needed"])
        self.assertEqual(session.latest_outcome()["selected_action"], "delegate_to_executor")

    def test_reject_and_details_do_not_execute(self) -> None:
        for choice in ("reject", "details"):
            with self.subTest(choice=choice):
                executor = CapturingExecutor()
                session = SpiceDemoSession(executor=executor)
                session.ingest_many(sample_bridge_observations(now=NOW))
                recommendation = session.recommend(now=NOW)
                control = session.handle_recommendation(recommendation, now=NOW)

                resolution = session.resolve_confirmation(
                    str(control.confirmation_request["confirmation_id"]),
                    choice=choice,
                    now=NOW,
                )

                self.assertEqual(len(executor.requests), 0)
                self.assertFalse(resolution.state_updated)
                self.assertIsNone(session.latest_outcome())

    def test_hermes_executor_prompt_and_output_normalization(self) -> None:
        session = SpiceDemoSession(executor=CapturingExecutor())
        session.ingest_many(sample_bridge_observations(now=NOW))
        recommendation = session.recommend(now=NOW)
        request = build_execution_request(recommendation, executor="codex", now=NOW)

        prompt = build_hermes_codex_prompt(request)
        outcome = normalize_hermes_output(
            request,
            raw_output=json.dumps(
                {
                    "status": "partial",
                    "elapsed_minutes": 4,
                    "risk_change": "reduced",
                    "followup_needed": True,
                    "summary": "Triage completed.",
                    "blocking_issue": None,
                }
            ),
            elapsed_seconds=240,
            command=["hermes"],
        )

        self.assertIn(recommendation["decision_id"], prompt)
        self.assertIn("success_criteria", prompt)
        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.risk_change, "reduced")
        self.assertTrue(outcome.metadata["parsed_json"])

    def test_whatsapp_formatters_for_resolution_and_execution(self) -> None:
        result = run_sample_flow(choice="confirm", executor=CapturingExecutor(), now=NOW)
        payload = result.to_payload()

        self.assertIn("1 同意执行", payload["confirmation_text"])
        self.assertIn("已完成执行", payload["resolution_text"])
        self.assertIn("风险变化", payload["resolution_text"])

    def test_end_to_end_sample_flow_confirm_reject_details(self) -> None:
        confirm = run_sample_flow(choice="confirm", executor=CapturingExecutor(), now=NOW)
        reject = run_sample_flow(choice="reject", executor=CapturingExecutor(), now=NOW)
        details = run_sample_flow(choice="details", executor=CapturingExecutor(), now=NOW)

        self.assertEqual(confirm.resolution["status"], "executed")
        self.assertEqual(reject.resolution["status"], "rejected")
        self.assertEqual(details.resolution["status"], "details")
        self.assertIsNotNone(confirm.recent_outcome)
        self.assertIsNone(reject.recent_outcome)
        self.assertIsNone(details.recent_outcome)

    def test_run_sample_flow_default_uses_sdep_execution_spine(self) -> None:
        transport = CapturingSDEPTransport()
        with patch(
            "examples.decision_hub_demo.sdep_executor.create_default_sdep_executor",
            return_value=SDEPBackedExecutor(transport),
        ):
            result = run_sample_flow(choice="confirm", now=NOW)

        self.assertEqual(result.resolution["status"], "executed")
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.requests[0].execution.action_type, SDEP_DELEGATE_ACTION_TYPE)
        self.assertIsNotNone(result.recent_outcome)
        assert result.recent_outcome is not None
        self.assertEqual(result.recent_outcome["status"], "success")

    def test_cli_run_demo_flow_default_uses_sdep_execution_spine(self) -> None:
        transport = CapturingSDEPTransport()
        with patch(
            "examples.decision_hub_demo.sdep_executor.create_default_sdep_executor",
            return_value=SDEPBackedExecutor(transport),
        ), patch("spice_hermes_bridge.integrations.hermes_executor.create_executor") as direct_factory:
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = bridge_main(["run-demo-flow", "--choice", "confirm", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.requests[0].execution.action_type, SDEP_DELEGATE_ACTION_TYPE)
        direct_factory.assert_not_called()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["resolution"]["status"], "executed")
        self.assertEqual(payload["recent_outcome"]["status"], "success")

    def test_default_sdep_protocol_error_returns_failed_outcome_and_observation(self) -> None:
        transport = CapturingSDEPTransport(
            response_status="error",
            error={
                "code": "hermes.timeout",
                "message": "Hermes timed out after 30 seconds.",
                "retryable": True,
                "details": {"timeout_seconds": 30},
            },
        )
        with patch(
            "examples.decision_hub_demo.sdep_executor.create_default_sdep_executor",
            return_value=SDEPBackedExecutor(transport),
        ):
            result = run_sample_flow(choice="confirm", now=NOW)

        self.assertEqual(result.resolution["status"], "executed")
        execution = result.resolution["execution"]
        self.assertEqual(execution["outcome"]["status"], "failed")
        self.assertEqual(result.recent_outcome["status"], "failed")
        self.assertEqual(result.updated_work_item["status"], "open")
        self.assertEqual(result.updated_work_item["last_execution_status"], "failed")
        provenance = execution["observation"]["metadata"]["provenance"]
        self.assertEqual(provenance["sdep_response_status"], "error")
        self.assertEqual(provenance["protocol_error"]["code"], "hermes.timeout")
        self.assertEqual(provenance["protocol_error"]["details"]["timeout_seconds"], 30)

    def test_default_sdep_non_json_failed_outcome_round_trips_through_observation(self) -> None:
        transport = CapturingSDEPTransport(
            outcome_status="failed",
            output={
                "status": "failed",
                "summary": "Hermes/Codex returned non-JSON output.",
                "risk_change": "unknown",
                "followup_needed": True,
                "blocking_issue": "invalid_hermes_output",
                "execution_ref": "hermes.exec.nonjson",
            },
            outcome_metadata={
                "executor": "codex",
                "failure_kind": "invalid_hermes_output",
                "parse_error": "No JSON object found.",
            },
        )
        with patch(
            "examples.decision_hub_demo.sdep_executor.create_default_sdep_executor",
            return_value=SDEPBackedExecutor(transport),
        ):
            result = run_sample_flow(choice="confirm", now=NOW)

        execution = result.resolution["execution"]
        self.assertEqual(execution["outcome"]["status"], "failed")
        self.assertEqual(result.updated_work_item["status"], "open")
        self.assertEqual(result.updated_work_item["last_execution_status"], "failed")
        metadata = execution["observation"]["metadata"]["outcome_metadata"]
        self.assertEqual(metadata["sdep_outcome_metadata"]["failure_kind"], "invalid_hermes_output")

    def test_default_sdep_non_success_outcomes_keep_work_item_open(self) -> None:
        for status in ("partial", "failed", "abandoned"):
            with self.subTest(status=status):
                transport = CapturingSDEPTransport(outcome_status=status)
                with patch(
                    "examples.decision_hub_demo.sdep_executor.create_default_sdep_executor",
                    return_value=SDEPBackedExecutor(transport),
                ):
                    result = run_sample_flow(choice="confirm", now=NOW)

                self.assertEqual(result.recent_outcome["status"], status)
                self.assertEqual(result.updated_work_item["status"], "open")
                self.assertEqual(result.updated_work_item["last_execution_status"], status)

    def test_cli_run_demo_flow_with_mock_executor(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = bridge_main(["run-demo-flow", "--executor", "mock", "--choice", "details", "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["resolution"]["status"], "details")

    def test_spice_demo_session_env_config_uses_llm_simulation(self) -> None:
        env = {
            SIMULATION_ENABLED_ENV: "1",
            SIMULATION_MODEL_ENV: "openrouter:test-model",
            OPENROUTER_API_KEY_ENV: "test-key",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "examples.decision_hub_demo.llm_simulation._build_llm_client",
            return_value=FakeLLMClient(),
        ):
            session = SpiceDemoSession(executor=CapturingExecutor())
            session.ingest_many(sample_bridge_observations(now=NOW))
            recommendation = session.recommend(now=NOW)

        sources = {
            item["metadata"]["simulation_source"]
            for item in recommendation["trace"]["candidate_consequences"].values()
        }
        self.assertEqual(sources, {"llm"})


if __name__ == "__main__":
    unittest.main()
