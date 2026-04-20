from __future__ import annotations

import json
import subprocess
import unittest
from io import StringIO

from spice_hermes_bridge.integrations.hermes_sdep_agent import handle_payload, main
from spice_hermes_bridge.integrations.hermes_sdep_native import HermesCodexNativeRunner


ACTION_TYPE = "decision_hub.delegate_to_executor"


def _execute_request(**overrides):
    payload = {
        "protocol": "sdep",
        "sdep_version": "0.1",
        "message_type": "execute.request",
        "message_id": "msg.execute.1",
        "request_id": "req.execute.1",
        "timestamp": "2026-04-17T08:00:00+00:00",
        "sender": {
            "id": "spice.brain",
            "name": "Spice",
            "version": "0.1",
            "role": "brain",
        },
        "idempotency_key": "idem.1",
        "traceability": {"decision_id": "decision.demo.1"},
        "execution": {
            "action_type": ACTION_TYPE,
            "target": {
                "kind": "work_item",
                "id": "workitem.github_pr.123",
            },
            "parameters": {
                "scope": "triage",
                "time_budget_minutes": 10,
                "target_url": "https://github.com/Dyalwayshappy/Spice/pull/123",
            },
            "input": {
                "decision_id": "decision.demo.1",
                "selected_action": ACTION_TYPE,
                "acted_on": "workitem.github_pr.123",
            },
            "constraints": [],
            "success_criteria": [
                {"criterion": "Return status, blocker, risk_change, followup_needed"}
            ],
            "failure_policy": {"on_failure": "report"},
        },
        "metadata": {"test": True},
    }
    payload.update(overrides)
    return payload


def _describe_request(**overrides):
    payload = {
        "protocol": "sdep",
        "sdep_version": "0.1",
        "message_type": "agent.describe.request",
        "message_id": "msg.describe.1",
        "request_id": "req.describe.1",
        "timestamp": "2026-04-17T08:00:00+00:00",
        "sender": {
            "id": "spice.brain",
            "name": "Spice",
            "version": "0.1",
            "role": "brain",
        },
        "query": {
            "include_capabilities": True,
            "action_types": [ACTION_TYPE],
            "metadata": {},
        },
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _runner_stdout(text: str, *, returncode: int = 0):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout=text,
            stderr="boom" if returncode else "",
        )

    return run


class HermesSDEPAgentTest(unittest.TestCase):
    def test_valid_execute_request_returns_success_response(self) -> None:
        runner = HermesCodexNativeRunner(
            runner=_runner_stdout(
                json.dumps(
                    {
                        "status": "success",
                        "elapsed_minutes": 6,
                        "risk_change": "reduced",
                        "followup_needed": True,
                        "summary": "PR triaged, no blocking issue.",
                        "blocking_issue": None,
                    }
                )
            )
        )

        response = handle_payload(_execute_request(), native_runner=runner)

        self.assertEqual(response["message_type"], "execute.response")
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["outcome"]["status"], "success")
        self.assertEqual(response["outcome"]["outcome_type"], "observation")
        self.assertEqual(response["outcome"]["output"]["decision_id"], "decision.demo.1")
        self.assertEqual(response["outcome"]["output"]["selected_action"], ACTION_TYPE)
        self.assertEqual(response["outcome"]["output"]["risk_change"], "reduced")
        self.assertTrue(response["metadata"]["native_call_hidden"])

    def test_legacy_delegate_action_name_is_not_supported(self) -> None:
        payload = _execute_request()
        payload["execution"]["action_type"] = "delegate_to_executor"

        response = handle_payload(payload)

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error"]["code"], "sdep.action.unsupported")
        self.assertEqual(response["error"]["details"]["action_type"], "delegate_to_executor")

    def test_invalid_execute_request_returns_error_response(self) -> None:
        response = handle_payload(
            {
                "protocol": "sdep",
                "sdep_version": "0.1",
                "message_type": "execute.request",
                "message_id": "msg.bad",
                "request_id": "req.bad",
            }
        )

        self.assertEqual(response["message_type"], "execute.response")
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["outcome"]["status"], "failed")
        self.assertEqual(response["error"]["code"], "sdep.execute_request.invalid")

    def test_hermes_non_json_returns_failed_outcome_not_dirty_success(self) -> None:
        runner = HermesCodexNativeRunner(runner=_runner_stdout("plain text, not json"))

        response = handle_payload(_execute_request(), native_runner=runner)

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["outcome"]["status"], "failed")
        output = response["outcome"]["output"]
        self.assertEqual(output["blocking_issue"], "invalid_hermes_output")
        self.assertEqual(output["status"], "failed")
        self.assertFalse(response["outcome"]["metadata"]["parsed_json"])

    def test_hermes_invalid_json_schema_returns_failed_outcome(self) -> None:
        runner = HermesCodexNativeRunner(
            runner=_runner_stdout(
                json.dumps(
                    {
                        "status": "success",
                        "elapsed_minutes": 1,
                        "risk_change": "reduced",
                        "followup_needed": False,
                        "summary": "done",
                        "blocking_issue": None,
                        "recommendation": "choose me",
                    }
                )
            )
        )

        response = handle_payload(_execute_request(), native_runner=runner)

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["outcome"]["status"], "failed")
        self.assertEqual(response["outcome"]["output"]["blocking_issue"], "invalid_hermes_output")

    def test_hermes_timeout_returns_error_response(self) -> None:
        def run(command, **kwargs):
            raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

        runner = HermesCodexNativeRunner(timeout_seconds=1, runner=run)

        response = handle_payload(_execute_request(), native_runner=runner)

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error"]["code"], "hermes.timeout")
        self.assertTrue(response["error"]["retryable"])
        self.assertEqual(response["error"]["details"]["timeout_seconds"], 1)

    def test_hermes_subprocess_failure_returns_structured_error_details(self) -> None:
        runner = HermesCodexNativeRunner(runner=_runner_stdout("", returncode=7))

        response = handle_payload(_execute_request(), native_runner=runner)

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error"]["code"], "hermes.subprocess_failed")
        self.assertTrue(response["error"]["retryable"])
        self.assertEqual(response["error"]["details"]["exit_code"], 7)
        self.assertEqual(response["error"]["details"]["stderr_excerpt"], "boom")

    def test_describe_request_returns_delegate_capability(self) -> None:
        response = handle_payload(_describe_request())

        self.assertEqual(response["message_type"], "agent.describe.response")
        self.assertEqual(response["status"], "success")
        capabilities = response["description"]["capabilities"]
        self.assertEqual(len(capabilities), 1)
        self.assertEqual(capabilities[0]["action_type"], ACTION_TYPE)
        self.assertEqual(capabilities[0]["metadata"]["executor"], "codex")

    def test_stdin_stdout_main_uses_json_boundary(self) -> None:
        runner = HermesCodexNativeRunner(
            runner=_runner_stdout(
                json.dumps(
                    {
                        "status": "success",
                        "elapsed_minutes": 2,
                        "risk_change": "unchanged",
                        "followup_needed": False,
                        "summary": "Handled.",
                        "blocking_issue": None,
                    }
                )
            )
        )
        stdout = StringIO()

        exit_code = main(
            stdin=StringIO(json.dumps(_execute_request())),
            stdout=stdout,
            native_runner=runner,
        )

        self.assertEqual(exit_code, 0)
        response = json.loads(stdout.getvalue())
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["outcome"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
