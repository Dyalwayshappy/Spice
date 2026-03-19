from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from spice.executors import SDEPExecutor, SubprocessSDEPTransport
from spice.executors.sdep_mapping import build_sdep_describe_request, build_sdep_execute_request
from spice.protocols import ExecutionIntent, SDEPDescribeResponse, SDEPExecuteResponse


REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER_MAIN = REPO_ROOT / "examples" / "sdep_wrapper_template" / "wrapper_main.py"
NATIVE_AGENT = (
    REPO_ROOT
    / "examples"
    / "sdep_wrapper_template"
    / "adapters"
    / "example_non_sdep_agent.py"
)


class SDEPWrapperTemplateTests(unittest.TestCase):
    def test_wrapper_execute_request_returns_valid_execute_response(self) -> None:
        intent = self._make_intent(
            intent_id="intent.wrapper.template.execute",
            operation_name="personal.gather_evidence",
        )
        request = build_sdep_execute_request(intent)

        payload = self._run_wrapper_payload(request.to_dict())
        response = SDEPExecuteResponse.from_dict(payload)

        self.assertEqual(response.status, "success")
        self.assertEqual(response.request_id, request.request_id)
        self.assertEqual(response.outcome.status, "success")
        self.assertEqual(
            response.outcome.output.get("native_agent"),
            "example_non_sdep_agent",
        )
        self.assertEqual(
            response.outcome.output.get("action_type"),
            "personal.gather_evidence",
        )

    def test_wrapper_describe_request_returns_valid_static_description(self) -> None:
        request = build_sdep_describe_request(
            action_types=["personal.gather_evidence"],
        )

        payload = self._run_wrapper_payload(request.to_dict())
        response = SDEPDescribeResponse.from_dict(payload)

        self.assertEqual(response.status, "success")
        capabilities = response.description.capabilities
        self.assertEqual(len(capabilities), 1)
        self.assertEqual(capabilities[0].action_type, "personal.gather_evidence")

    def test_wrapper_adapter_failure_returns_structured_sdep_error(self) -> None:
        intent = self._make_intent(
            intent_id="intent.wrapper.template.native_fail",
            operation_name="demo.native.fail",
        )
        request = build_sdep_execute_request(intent)

        payload = self._run_wrapper_payload(
            request.to_dict(),
            extra_args=["--capability-action", "demo.native.fail"],
        )
        response = SDEPExecuteResponse.from_dict(payload)

        self.assertEqual(response.status, "error")
        self.assertIsNotNone(response.error)
        self.assertEqual(response.error.code, "adapter.failed")
        self.assertIn("failure", response.error.message.lower())

    def test_sdep_executor_e2e_with_wrapper_and_non_sdep_agent(self) -> None:
        command = self._wrapper_command()
        transport = SubprocessSDEPTransport(command, timeout_seconds=20.0)
        executor = SDEPExecutor(transport)

        intent = self._make_intent(
            intent_id="intent.wrapper.template.e2e",
            operation_name="personal.gather_evidence",
        )
        result = executor.execute(intent)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result_type, "observation")
        self.assertEqual(result.output.get("native_agent"), "example_non_sdep_agent")
        self.assertEqual(result.output.get("action_type"), "personal.gather_evidence")
        self.assertIn("sdep", result.attributes)
        self.assertIn("response", result.attributes["sdep"])
        self.assertEqual(
            result.attributes["sdep"]["response"]["status"],
            "success",
        )

    def _run_wrapper_payload(
        self,
        payload: dict[str, object],
        *,
        extra_args: list[str] | None = None,
    ) -> dict[str, object]:
        command = self._wrapper_command(extra_args=extra_args)
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            input=json.dumps(payload, ensure_ascii=True),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        response = json.loads(completed.stdout)
        self.assertIsInstance(response, dict)
        return response

    def _wrapper_command(self, *, extra_args: list[str] | None = None) -> list[str]:
        command = [
            sys.executable,
            str(WRAPPER_MAIN),
            "--adapter",
            "subprocess-json",
            "--agent-command",
            f"{sys.executable} {NATIVE_AGENT}",
        ]
        if extra_args:
            command.extend(extra_args)
        return command

    @staticmethod
    def _make_intent(*, intent_id: str, operation_name: str) -> ExecutionIntent:
        return ExecutionIntent(
            id=intent_id,
            intent_type="personal.assistant.execute",
            status="planned",
            objective={"id": "obj-wrapper", "description": "SDEP wrapper template test"},
            executor_type="external-agent",
            target={"kind": "external.service", "id": "research"},
            operation={"name": operation_name, "mode": "sync", "dry_run": False},
            input_payload={"question": "collect one evidence snapshot"},
            parameters={"priority": "normal"},
            constraints=[],
            success_criteria=[{"id": "exec.ok", "description": "native adapter returns success"}],
            failure_policy={"strategy": "fail_fast", "max_retries": 0},
            refs=[],
            provenance={"source": "test_sdep_wrapper_template"},
        )


if __name__ == "__main__":
    unittest.main()

