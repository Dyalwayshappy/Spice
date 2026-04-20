from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from spice.llm.core import LLMResponse

from examples.decision_hub_demo.execution_adapter import ExecutionOutcome, ExecutionRequest
from examples.decision_hub_demo.llm_simulation import (
    OPENROUTER_API_KEY_ENV,
    SIMULATION_ENABLED_ENV,
    SIMULATION_MODEL_ENV,
)
from examples.decision_hub_demo.sdep_executor import SDEPBackedExecutor, SDEP_DELEGATE_ACTION_TYPE
from examples.decision_hub_demo.state import DOMAIN_KEY

from spice_hermes_bridge.integrations.spice_demo import sample_bridge_observations
from spice_hermes_bridge.integrations.whatsapp_server import (
    DryRunWhatsAppSender,
    WhatsAppWebhookRuntime,
    inbound_message_from_payload,
)


NOW = datetime(2026, 4, 17, 6, 20, tzinfo=timezone.utc)
CHAT_ID = "whatsapp.self"


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
    def __init__(self, *, outcome_status: str = "success", response_status: str = "success") -> None:
        self.outcome_status = outcome_status
        self.response_status = response_status
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return sdep_response_for_request(
            request,
            outcome_status=self.outcome_status,
            response_status=self.response_status,
        )


def sdep_response_for_request(
    request,
    *,
    outcome_status: str = "success",
    response_status: str = "success",
) -> dict:
    output_status = outcome_status if response_status == "success" else "failed"
    risk_change = "reduced" if output_status in {"success", "partial"} else "increased"
    return {
        "protocol": "sdep",
        "sdep_version": "0.1",
        "message_type": "execute.response",
        "message_id": "sdep-msg-whatsapp-test",
        "request_id": request.request_id,
        "timestamp": "2026-04-17T06:20:01+00:00",
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
            "execution_id": "hermes.exec.whatsapp.001",
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
                "summary": f"WhatsApp SDEP execution ended with status {output_status}.",
                "execution_ref": "hermes.exec.whatsapp.001",
                "blocking_issue": "sdep_test_failure" if output_status == "failed" else None,
            },
            "artifacts": [],
            "metrics": {"elapsed_minutes": 6},
            "metadata": {"executor": "codex"},
        },
        "error": None,
        "traceability": dict(request.traceability),
        "metadata": {"wrapper": "whatsapp_test_sdep_transport"},
    }


class FakeLLMClient:
    def generate(self, request, *, model_override=None) -> LLMResponse:
        del model_override
        action = str(request.metadata["action_type"])
        payload = {
            "candidate_id": str(request.metadata["candidate_id"]),
            "action_type": action,
            "expected_time_cost_minutes": 10 if action == "delegate_to_executor" else 5,
            "commitment_risk": "low",
            "work_item_risk_change": "reduced" if action != "ignore_temporarily" else "increased",
            "reversibility": "high",
            "attention_cost": "low",
            "followup_needed": True,
            "followup_summary": "Fake LLM consequence for WhatsApp integration test.",
            "executor_load": "medium" if action == "delegate_to_executor" else "none",
            "requires_confirmation": action == "delegate_to_executor",
            "confidence": 0.82,
            "assumptions": ["fake llm whatsapp test"],
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


def make_runtime(tmp_path, executor: CapturingExecutor | None = None) -> WhatsAppWebhookRuntime:
    return WhatsAppWebhookRuntime(
        sender=DryRunWhatsAppSender(),
        executor=executor or CapturingExecutor(),
        pending_store_path=tmp_path / "pending_confirmations.json",
        now_provider=lambda: NOW,
    )


def make_default_runtime(tmp_path) -> WhatsAppWebhookRuntime:
    return WhatsAppWebhookRuntime(
        sender=DryRunWhatsAppSender(),
        pending_store_path=tmp_path / "pending_confirmations.json",
        now_provider=lambda: NOW,
    )


def seed_work_item(runtime: WhatsAppWebhookRuntime) -> None:
    work_item = sample_bridge_observations(now=NOW)[2]
    runtime.ingest_observation_for_chat(CHAT_ID, work_item)


def send_clear_schedule(runtime: WhatsAppWebhookRuntime):
    return runtime.handle_payload(
        {
            "chat_id": CHAT_ID,
            "sender": "me",
            "text": "今天下午3点有个投资人会议，持续1小时，提前30分钟准备",
            "received_at": "2026-04-17T14:20:00+08:00",
        }
    )


class WhatsAppServerTest(unittest.TestCase):
    def test_hermes_like_payload_normalization_supports_sender(self) -> None:
        message = inbound_message_from_payload(
            {
                "data": {
                    "chat_id": CHAT_ID,
                    "sender": "me",
                    "message": {"text": "今天下午3点有个会"},
                }
            }
        )

        self.assertEqual(message.chat_id, CHAT_ID)
        self.assertEqual(message.sender_id, "me")
        self.assertEqual(message.text, "今天下午3点有个会")

    def test_clear_schedule_without_work_item_records_observation(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            from pathlib import Path

            runtime = make_runtime(Path(directory))
            result = runtime.handle_payload(
                {
                    "chat_id": CHAT_ID,
                    "sender": "me",
                    "text": "今天下午3点有个投资人会议，持续1小时，提前30分钟准备",
                    "received_at": "2026-04-17T14:20:00+08:00",
                }
            )

        self.assertEqual(result.input_type, "observation_recorded")
        self.assertEqual(result.ingress["result_type"], "observation")
        self.assertIn("已记录到 Spice state", result.reply_text)

    def test_schedule_plus_existing_work_item_generates_confirmation(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            executor = CapturingExecutor()
            runtime = make_runtime(Path(directory), executor=executor)
            seed_work_item(runtime)

            result = runtime.handle_payload(
                {
                    "chat_id": CHAT_ID,
                    "sender": "me",
                    "text": "今天下午3点有个投资人会议，持续1小时，提前30分钟准备",
                    "received_at": "2026-04-17T14:20:00+08:00",
                }
            )

            session = runtime.session_for(CHAT_ID)

        self.assertEqual(result.input_type, "decision_control")
        self.assertEqual(result.control["status"], "confirmation_required")
        self.assertEqual(result.recommendation["selected_action"], "delegate_to_executor")
        self.assertTrue(result.recommendation["requires_confirmation"])
        self.assertIsNotNone(session.active_confirmation_id)
        self.assertEqual(len(executor.requests), 0)
        self.assertIn("1 同意执行", result.reply_text)

    def test_confirm_reply_executes_and_updates_spice_state(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            executor = CapturingExecutor()
            runtime = make_runtime(Path(directory), executor=executor)
            seed_work_item(runtime)
            runtime.handle_payload(
                {
                    "chat_id": CHAT_ID,
                    "text": "今天下午3点有个投资人会议，持续1小时，提前30分钟准备",
                    "received_at": "2026-04-17T14:20:00+08:00",
                }
            )

            result = runtime.handle_payload({"chat_id": CHAT_ID, "text": "1"})
            session = runtime.session_for(CHAT_ID)
            work_items = session.spice_session.state.domain_state[DOMAIN_KEY]["work_items"]

        self.assertEqual(result.input_type, "confirmation_confirm")
        self.assertEqual(result.resolution["status"], "executed")
        self.assertEqual(len(executor.requests), 1)
        self.assertIsNone(session.active_confirmation_id)
        self.assertIn("已完成执行", result.reply_text)
        self.assertTrue(next(iter(work_items.values()))["followup_needed"])

    def test_default_whatsapp_confirm_uses_sdep_execution_spine(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            transport = CapturingSDEPTransport()
            with patch(
                "examples.decision_hub_demo.sdep_executor.create_default_sdep_executor",
                return_value=SDEPBackedExecutor(transport),
            ) as default_factory, patch(
                "spice_hermes_bridge.integrations.hermes_executor.create_executor"
            ) as direct_factory:
                runtime = make_default_runtime(Path(directory))
                seed_work_item(runtime)
                send_clear_schedule(runtime)

                result = runtime.handle_payload({"chat_id": CHAT_ID, "text": "1"})
                session = runtime.session_for(CHAT_ID)

        self.assertEqual(result.input_type, "confirmation_confirm")
        self.assertEqual(result.resolution["status"], "executed")
        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertEqual(request.message_type, "execute.request")
        self.assertEqual(request.execution.action_type, SDEP_DELEGATE_ACTION_TYPE)
        self.assertIsNotNone(session.spice_session.latest_outcome())
        assert session.spice_session.latest_outcome() is not None
        self.assertEqual(session.spice_session.latest_outcome()["status"], "success")
        default_factory.assert_called()
        direct_factory.assert_not_called()

    def test_reject_and_details_do_not_execute(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        for choice, expected_status in (("2", "rejected"), ("3", "details")):
            with self.subTest(choice=choice):
                with TemporaryDirectory() as directory:
                    executor = CapturingExecutor()
                    runtime = make_runtime(Path(directory), executor=executor)
                    seed_work_item(runtime)
                    runtime.handle_payload(
                        {
                            "chat_id": CHAT_ID,
                            "text": "今天下午3点有个投资人会议，持续1小时，提前30分钟准备",
                            "received_at": "2026-04-17T14:20:00+08:00",
                        }
                    )

                    result = runtime.handle_payload({"chat_id": CHAT_ID, "text": choice})

                self.assertEqual(result.resolution["status"], expected_status)
                self.assertEqual(len(executor.requests), 0)

    def test_default_whatsapp_reject_and_details_do_not_emit_sdep_request(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        for choice, expected_status in (("2", "rejected"), ("3", "details")):
            with self.subTest(choice=choice):
                with TemporaryDirectory() as directory:
                    transport = CapturingSDEPTransport()
                    with patch(
                        "examples.decision_hub_demo.sdep_executor.create_default_sdep_executor",
                        return_value=SDEPBackedExecutor(transport),
                    ), patch("spice_hermes_bridge.integrations.hermes_executor.create_executor") as direct_factory:
                        runtime = make_default_runtime(Path(directory))
                        seed_work_item(runtime)
                        send_clear_schedule(runtime)

                        result = runtime.handle_payload({"chat_id": CHAT_ID, "text": choice})

                self.assertEqual(result.resolution["status"], expected_status)
                self.assertEqual(len(transport.requests), 0)
                direct_factory.assert_not_called()

    def test_default_whatsapp_ask_user_does_not_emit_sdep_request(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            transport = CapturingSDEPTransport()
            with patch(
                "examples.decision_hub_demo.sdep_executor.create_default_sdep_executor",
                return_value=SDEPBackedExecutor(transport),
            ), patch("spice_hermes_bridge.integrations.hermes_executor.create_executor") as direct_factory:
                runtime = make_default_runtime(Path(directory))
                seed_work_item(runtime)
                session = runtime.session_for(CHAT_ID)

                def ask_user_recommendation(*, now=None):
                    del now
                    return {
                        "decision_id": "decision.test.ask_user",
                        "selected_action": "ask_user",
                        "acted_on": "workitem.github_pr.123",
                        "recommendation": "Ask user for missing details.",
                        "trace_ref": "trace.test.ask_user",
                        "human_summary": "需要更多信息。",
                        "reason_summary": ["关键信息不足"],
                        "score_breakdown": {},
                        "veto_reasons": [],
                        "tradeoff_rules_applied": [],
                        "requires_confirmation": False,
                    }

                session.spice_session.recommend = ask_user_recommendation
                result = send_clear_schedule(runtime)

        self.assertEqual(result.input_type, "decision_control")
        self.assertEqual(result.control["status"], "ask_user")
        self.assertEqual(len(transport.requests), 0)
        direct_factory.assert_not_called()

    def test_pending_confirmation_and_followup_resolution(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))
            pending = runtime.handle_payload(
                {
                    "chat_id": CHAT_ID,
                    "text": "明天下午有个会",
                    "received_at": "2026-04-17T14:20:00+08:00",
                }
            )
            resolved = runtime.handle_payload(
                {
                    "chat_id": CHAT_ID,
                    "text": "下午3点，1小时",
                    "received_at": "2026-04-17T14:22:00+08:00",
                }
            )

        self.assertEqual(pending.input_type, "pending_confirmation")
        self.assertEqual(resolved.input_type, "observation_recorded")
        self.assertEqual(resolved.ingress["result_type"], "observation")

    def test_choice_without_pending_confirmation_is_rejected(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))
            result = runtime.handle_payload({"chat_id": CHAT_ID, "text": "1"})

        self.assertEqual(result.input_type, "invalid_choice")
        self.assertIn("当前没有待确认", result.reply_text)

    def test_env_configured_llm_simulation_does_not_break_whatsapp_flow(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        env = {
            SIMULATION_ENABLED_ENV: "1",
            SIMULATION_MODEL_ENV: "openrouter:test-model",
            OPENROUTER_API_KEY_ENV: "test-key",
        }
        with TemporaryDirectory() as directory, patch.dict(os.environ, env, clear=False), patch(
            "examples.decision_hub_demo.llm_simulation._build_llm_client",
            return_value=FakeLLMClient(),
        ):
            runtime = make_runtime(Path(directory))
            seed_work_item(runtime)
            result = runtime.handle_payload(
                {
                    "chat_id": CHAT_ID,
                    "sender": "me",
                    "text": "今天下午3点有个投资人会议，持续1小时，提前30分钟准备",
                    "received_at": "2026-04-17T14:20:00+08:00",
                }
            )

        self.assertEqual(result.input_type, "decision_control")
        self.assertIsNotNone(result.recommendation)
        assert result.recommendation is not None
        sources = {
            item["metadata"]["simulation_source"]
            for item in result.recommendation["trace"]["candidate_consequences"].values()
        }
        self.assertEqual(sources, {"llm"})


if __name__ == "__main__":
    unittest.main()
