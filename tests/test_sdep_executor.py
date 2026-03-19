from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from spice.executors import SDEPExecutor, SubprocessSDEPTransport
from spice.protocols import ExecutionIntent


REPO_ROOT = Path(__file__).resolve().parents[1]
ECHO_AGENT = REPO_ROOT / "examples" / "sdep_agent_demo" / "echo_agent.py"


class _StaticPayloadTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = dict(payload)

    def execute(self, request: Any) -> dict[str, Any]:
        return dict(self.payload)


class _StaticDescribeTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = dict(payload)

    def execute(self, request: Any) -> dict[str, Any]:
        raise NotImplementedError

    def describe(self, request: Any) -> dict[str, Any]:
        return dict(self.payload)


class SDEPExecutorTests(unittest.TestCase):
    def test_sdep_executor_success_path(self) -> None:
        executor = self._executor_for_echo_agent()
        intent = self._make_intent("intent.sdep.test.success", "demo.echo")
        intent.input_payload = {"ticket_id": "INC-TEST-1"}

        result = executor.execute(intent)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.executor, "echo-agent")
        self.assertEqual(result.result_type, "observation")
        self.assertEqual(result.output.get("operation"), "demo.echo")
        self.assertIn("sdep", result.attributes)
        sdep_payload = result.attributes["sdep"]
        self.assertEqual(sdep_payload["response"]["status"], "success")
        self.assertIn("execution", sdep_payload["request"])
        self.assertEqual(
            sdep_payload["request"]["execution"]["target"],
            {"kind": "service", "id": "checkout-api"},
        )
        self.assertNotIn("intent", sdep_payload["request"])
        self.assertIn("responder", sdep_payload["response"])

    def test_sdep_executor_agent_error_path(self) -> None:
        executor = self._executor_for_echo_agent()
        intent = self._make_intent("intent.sdep.test.fail", "demo.fail")

        result = executor.execute(intent)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.result_type, "error")
        self.assertIn("rejected", (result.error or "").lower())
        self.assertIn("sdep", result.attributes)
        sdep_payload = result.attributes["sdep"]
        self.assertEqual(sdep_payload["response"]["status"], "error")

    def test_sdep_executor_transport_invalid_json(self) -> None:
        transport = SubprocessSDEPTransport([sys.executable, "-c", "print('not-json')"])
        executor = SDEPExecutor(transport)
        intent = self._make_intent("intent.sdep.test.invalid_json", "demo.echo")

        result = executor.execute(intent)

        self.assertEqual(result.status, "failed")
        self.assertIn("non-json", (result.error or "").lower())
        self.assertIn("sdep", result.attributes)
        self.assertIn("transport_error", result.attributes["sdep"])

    def test_sdep_executor_rejects_missing_target_id(self) -> None:
        executor = self._executor_for_echo_agent()
        intent = self._make_intent("intent.sdep.test.bad_target", "demo.echo")
        intent.target = {"kind": "service"}

        result = executor.execute(intent)

        self.assertEqual(result.status, "failed")
        self.assertIn("target.id", (result.error or "").lower())
        self.assertIn("transport_error", result.attributes.get("sdep", {}))

    def test_sdep_executor_rejects_canonical_response_without_responder(self) -> None:
        transport = _StaticPayloadTransport(
            {
                "protocol": "sdep",
                "sdep_version": "0.1",
                "message_type": "execute.response",
                "message_id": "sdep-msg-test",
                "request_id": "sdep-req-test",
                "timestamp": "2026-03-12T12:00:01+00:00",
                "status": "success",
                "outcome": {
                    "execution_id": "exec-test",
                    "status": "success",
                    "output": {"ok": True},
                    "artifacts": [],
                    "metrics": {},
                    "metadata": {},
                },
                "metadata": {},
            }
        )
        executor = SDEPExecutor(transport)
        intent = self._make_intent("intent.sdep.test.no_responder", "demo.echo")

        result = executor.execute(intent)

        self.assertEqual(result.status, "failed")
        self.assertIn("responder", (result.error or "").lower())

    def test_sdep_executor_prefers_responder_identity_over_metadata_fallback(self) -> None:
        transport = _StaticPayloadTransport(
            {
                "protocol": "sdep",
                "sdep_version": "0.1",
                "message_type": "execute.response",
                "message_id": "sdep-msg-test-prefer-responder",
                "request_id": "sdep-req-test-prefer-responder",
                "timestamp": "2026-03-12T12:00:01+00:00",
                "responder": {
                    "id": "agent.echo",
                    "name": "Echo Agent",
                    "version": "0.1",
                    "vendor": "ExampleVendor",
                    "implementation": "responder-impl",
                    "role": "executor",
                },
                "status": "success",
                "outcome": {
                    "execution_id": "exec-prefer-responder",
                    "status": "success",
                    "output": {"ok": True},
                    "artifacts": [],
                    "metrics": {},
                    "metadata": {
                        "result_type": "sdep.demo.echo",
                        "executor": "metadata-fallback",
                    },
                },
                "execution_result": {
                    "id": "legacy-result-id",
                    "result_type": "sdep.demo.legacy",
                    "executor": "legacy-fallback",
                    "output": {"legacy": True},
                },
                "metadata": {},
            }
        )
        executor = SDEPExecutor(transport)
        intent = self._make_intent("intent.sdep.test.prefer_responder", "demo.echo")

        result = executor.execute(intent)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.executor, "responder-impl")

    def test_sdep_executor_prefers_outcome_type_over_metadata_result_type(self) -> None:
        transport = _StaticPayloadTransport(
            {
                "protocol": "sdep",
                "sdep_version": "0.1",
                "message_type": "execute.response",
                "message_id": "sdep-msg-test-outcome-type",
                "request_id": "sdep-req-test-outcome-type",
                "timestamp": "2026-03-12T12:00:01+00:00",
                "responder": {
                    "id": "agent.echo",
                    "name": "Echo Agent",
                    "version": "0.1",
                    "vendor": "ExampleVendor",
                    "implementation": "echo-agent",
                    "role": "executor",
                },
                "status": "success",
                "outcome": {
                    "execution_id": "exec-outcome-type",
                    "status": "success",
                    "outcome_type": "observation",
                    "output": {"ok": True},
                    "artifacts": [],
                    "metrics": {},
                    "metadata": {
                        "result_type": "metadata-result-type",
                    },
                },
                "execution_result": {
                    "id": "legacy-result-id",
                    "result_type": "legacy-result-type",
                    "executor": "legacy-fallback",
                    "output": {"legacy": True},
                },
                "metadata": {},
            }
        )
        executor = SDEPExecutor(transport)
        intent = self._make_intent("intent.sdep.test.outcome_type_precedence", "demo.echo")

        result = executor.execute(intent)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result_type, "observation")

    def test_sdep_executor_describe_returns_canonical_description(self) -> None:
        transport = _StaticDescribeTransport(
            {
                "protocol": "sdep",
                "sdep_version": "0.1",
                "message_type": "agent.describe.response",
                "message_id": "sdep-msg-test-describe",
                "request_id": "sdep-req-test-describe",
                "timestamp": "2026-03-12T12:00:01+00:00",
                "responder": {
                    "id": "agent.echo",
                    "name": "Echo Agent",
                    "version": "0.1",
                    "vendor": "ExampleVendor",
                    "implementation": "echo-agent",
                    "role": "executor",
                },
                "status": "success",
                "description": {
                    "protocol_support": {
                        "protocol": "sdep",
                        "versions": ["0.1"],
                        "metadata": {},
                    },
                    "capabilities": [
                        {
                            "action_type": "demo.echo",
                            "target_kinds": ["service"],
                            "mode_support": ["sync"],
                            "dry_run_supported": True,
                            "input_expectation": "object payload",
                            "parameter_expectation": "object payload",
                            "metadata": {},
                        }
                    ],
                    "metadata": {},
                },
                "metadata": {},
            }
        )
        executor = SDEPExecutor(transport)

        description = executor.describe(action_types=["demo.echo"])

        self.assertEqual(description["message_type"], "agent.describe.response")
        self.assertEqual(description["status"], "success")
        self.assertEqual(
            description["description"]["capabilities"][0]["action_type"],
            "demo.echo",
        )

    @staticmethod
    def _make_intent(intent_id: str, operation_name: str) -> ExecutionIntent:
        return ExecutionIntent(
            id=intent_id,
            intent_type="demo.action",
            status="planned",
            objective={"id": "obj-1", "description": "SDEP test"},
            executor_type="external-agent",
            target={"kind": "service", "id": "checkout-api"},
            operation={"name": operation_name, "mode": "sync", "dry_run": False},
            input_payload={},
            parameters={},
            constraints=[],
            success_criteria=[],
            failure_policy={"strategy": "fail_fast", "max_retries": 0},
            refs=[],
            provenance={"source": "test"},
        )

    @staticmethod
    def _executor_for_echo_agent() -> SDEPExecutor:
        transport = SubprocessSDEPTransport([sys.executable, str(ECHO_AGENT)])
        return SDEPExecutor(transport)


if __name__ == "__main__":
    unittest.main()
