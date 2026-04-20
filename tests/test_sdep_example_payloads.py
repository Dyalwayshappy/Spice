from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from spice.protocols.sdep import (
    SDEPDescribeRequest,
    SDEPDescribeResponse,
    SDEPExecuteRequest,
    SDEPExecuteResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_DIR = REPO_ROOT / "examples" / "sdep_payloads" / "v0.1"


class SDEPExamplePayloadTests(unittest.TestCase):
    def test_example_payload_files_exist_and_parse(self) -> None:
        expected = {
            "execute.request.json",
            "execute.response.success.json",
            "execute.response.task_failed.json",
            "execute.response.protocol_error.json",
            "agent.describe.request.json",
            "agent.describe.response.json",
        }

        found = {path.name for path in PAYLOAD_DIR.glob("*.json")}

        self.assertEqual(found, expected)
        for name in expected:
            with self.subTest(payload=name):
                payload = _load_payload(name)
                self.assertEqual(payload["protocol"], "sdep")
                self.assertEqual(payload["sdep_version"], "0.1")

    def test_execute_request_example_matches_current_protocol_model(self) -> None:
        payload = _load_payload("execute.request.json")

        request = SDEPExecuteRequest.from_dict(payload)

        self.assertEqual(request.message_type, "execute.request")
        self.assertEqual(request.sender.role, "brain")
        self.assertEqual(request.execution.action_type, "decision_hub.delegate_to_executor")
        self.assertEqual(request.execution.target["kind"], "work_item")
        self.assertIn("spice_decision_id", request.traceability)

    def test_execute_response_success_example_matches_current_protocol_model(self) -> None:
        payload = _load_payload("execute.response.success.json")

        response = SDEPExecuteResponse.from_dict(payload)

        self.assertEqual(response.message_type, "execute.response")
        self.assertEqual(response.responder.role, "executor")
        self.assertEqual(response.status, "success")
        self.assertEqual(response.outcome.status, "success")
        self.assertEqual(response.outcome.outcome_type, "observation")
        self.assertEqual(response.outcome.output["risk_change"], "reduced")

    def test_execute_response_task_failed_example_preserves_status_split(self) -> None:
        payload = _load_payload("execute.response.task_failed.json")

        response = SDEPExecuteResponse.from_dict(payload)

        self.assertEqual(response.status, "success")
        self.assertEqual(response.outcome.status, "failed")
        self.assertEqual(response.outcome.output["blocking_issue"], "executor_task_failed")

    def test_execute_response_protocol_error_example_matches_current_protocol_model(self) -> None:
        payload = _load_payload("execute.response.protocol_error.json")

        response = SDEPExecuteResponse.from_dict(payload)

        self.assertEqual(response.status, "error")
        self.assertEqual(response.outcome.status, "failed")
        self.assertEqual(response.outcome.outcome_type, "error")
        self.assertIsNotNone(response.error)
        assert response.error is not None
        self.assertEqual(response.error.code, "hermes.timeout")
        self.assertTrue(response.error.retryable)

    def test_agent_describe_examples_match_current_protocol_model(self) -> None:
        request_payload = _load_payload("agent.describe.request.json")
        response_payload = _load_payload("agent.describe.response.json")

        request = SDEPDescribeRequest.from_dict(request_payload)
        response = SDEPDescribeResponse.from_dict(response_payload)

        self.assertEqual(request.message_type, "agent.describe.request")
        self.assertEqual(request.sender.role, "brain")
        self.assertEqual(request.query.action_types, ["decision_hub.delegate_to_executor"])
        self.assertEqual(response.message_type, "agent.describe.response")
        self.assertEqual(response.responder.role, "executor")
        self.assertEqual(response.description.protocol_support.protocol, "sdep")
        self.assertEqual(response.description.protocol_support.versions, ["0.1"])
        self.assertEqual(len(response.description.capabilities), 1)
        capability = response.description.capabilities[0]
        self.assertEqual(capability.action_type, "decision_hub.delegate_to_executor")
        self.assertEqual(capability.side_effect_class, "external_effect")
        self.assertEqual(capability.outcome_type, "observation")


def _load_payload(name: str) -> dict[str, Any]:
    with (PAYLOAD_DIR / name).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"{name} must be a JSON object")
    return payload


if __name__ == "__main__":
    unittest.main()
