from __future__ import annotations

import json
import subprocess
import unittest

from spice.protocols import SDEPExecuteRequest
from spice_hermes_bridge.integrations.hermes_sdep_native import (
    HermesCodexNativeRunner,
    HermesNativeSubprocessError,
    HermesNativeTimeout,
    normalize_hermes_sdep_output,
)


ACTION_TYPE = "decision_hub.delegate_to_executor"


def _request() -> SDEPExecuteRequest:
    return SDEPExecuteRequest.from_dict(
        {
            "protocol": "sdep",
            "sdep_version": "0.1",
            "message_type": "execute.request",
            "message_id": "msg.execute.native.1",
            "request_id": "req.execute.native.1",
            "timestamp": "2026-04-17T08:00:00+00:00",
            "sender": {
                "id": "spice.brain",
                "name": "Spice",
                "version": "0.1",
                "role": "brain",
            },
            "idempotency_key": "idem.native.1",
            "traceability": {"decision_id": "decision.demo.native.1"},
            "execution": {
                "action_type": ACTION_TYPE,
                "target": {"kind": "work_item", "id": "workitem.github_pr.123"},
                "parameters": {
                    "scope": "triage",
                    "time_budget_minutes": 10,
                    "target_url": "https://github.com/Dyalwayshappy/Spice/pull/123",
                },
                "input": {
                    "decision_id": "decision.demo.native.1",
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
    )


def _runner_stdout(text: str, *, returncode: int = 0, stderr: str = ""):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout=text,
            stderr=stderr,
        )

    return run


class HermesSDEPNativeTest(unittest.TestCase):
    def test_success_native_outcome_has_stable_shape(self) -> None:
        raw = json.dumps(
            {
                "status": "success",
                "elapsed_minutes": 6,
                "risk_change": "reduced",
                "followup_needed": True,
                "summary": "PR triaged, no blocking issue.",
                "blocking_issue": None,
            }
        )

        outcome = normalize_hermes_sdep_output(
            _request(),
            raw_output=raw,
            elapsed_seconds=2.5,
            command=["hermes", "chat", "-q"],
        )

        self.assertEqual(outcome.status, "success")
        self.assertEqual(outcome.elapsed_minutes, 6)
        self.assertEqual(outcome.risk_change, "reduced")
        self.assertTrue(outcome.followup_needed)
        self.assertEqual(outcome.summary, "PR triaged, no blocking issue.")
        self.assertIsNone(outcome.blocking_issue)
        self.assertTrue(outcome.execution_ref.startswith("hermes.codex.req.execute.native.1."))
        self.assertEqual(outcome.raw_output, raw)
        self.assertEqual(outcome.metadata["schema"], "hermes_native_outcome.v1")
        self.assertEqual(outcome.metadata["native_runner"], "hermes.chat")
        self.assertEqual(outcome.metadata["command"], ["hermes", "chat", "-q"])
        self.assertTrue(outcome.metadata["parsed_json"])
        self.assertTrue(outcome.metadata["output_valid"])
        self.assertEqual(outcome.metadata["normalization_status"], "valid")
        self.assertEqual(outcome.to_dict()["metadata"]["schema"], "hermes_native_outcome.v1")

    def test_task_failed_json_is_normalized_as_failed_outcome(self) -> None:
        outcome = normalize_hermes_sdep_output(
            _request(),
            raw_output=json.dumps(
                {
                    "status": "failed",
                    "elapsed_minutes": 3,
                    "risk_change": "increased",
                    "followup_needed": True,
                    "summary": "Codex could not access the target repository.",
                    "blocking_issue": "repo_access_denied",
                    "execution_ref": "exec.native.1",
                }
            ),
            elapsed_seconds=4.0,
            command=["hermes", "chat", "-q"],
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.blocking_issue, "repo_access_denied")
        self.assertEqual(outcome.execution_ref, "exec.native.1")
        self.assertTrue(outcome.metadata["parsed_json"])
        self.assertTrue(outcome.metadata["output_valid"])
        self.assertEqual(outcome.metadata["normalization_status"], "valid")

    def test_non_json_output_returns_consistent_failed_outcome(self) -> None:
        outcome = normalize_hermes_sdep_output(
            _request(),
            raw_output="plain text, not json",
            elapsed_seconds=1.0,
            command=["hermes", "chat", "-q"],
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.risk_change, "unknown")
        self.assertTrue(outcome.followup_needed)
        self.assertEqual(outcome.blocking_issue, "invalid_hermes_output")
        self.assertEqual(outcome.summary, "Hermes/Codex returned non-JSON output.")
        self.assertFalse(outcome.metadata["parsed_json"])
        self.assertFalse(outcome.metadata["output_valid"])
        self.assertEqual(outcome.metadata["normalization_status"], "failed")
        self.assertEqual(outcome.metadata["failure_kind"], "invalid_hermes_output")

    def test_json_with_trailing_prose_is_not_accepted(self) -> None:
        raw = json.dumps(
            {
                "status": "success",
                "elapsed_minutes": 1,
                "risk_change": "reduced",
                "followup_needed": False,
                "summary": "Done.",
            }
        )
        outcome = normalize_hermes_sdep_output(
            _request(),
            raw_output=f"{raw}\nextra prose",
            elapsed_seconds=1.0,
            command=["hermes", "chat", "-q"],
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.blocking_issue, "invalid_hermes_output")
        self.assertFalse(outcome.metadata["parsed_json"])

    def test_invalid_schema_missing_required_field_returns_failed_outcome(self) -> None:
        outcome = normalize_hermes_sdep_output(
            _request(),
            raw_output=json.dumps(
                {
                    "status": "success",
                    "elapsed_minutes": 1,
                    "risk_change": "reduced",
                    "followup_needed": False,
                }
            ),
            elapsed_seconds=1.0,
            command=["hermes", "chat", "-q"],
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.blocking_issue, "invalid_hermes_output")
        self.assertTrue(outcome.metadata["parsed_json"])
        self.assertFalse(outcome.metadata["output_valid"])
        self.assertIn("summary", outcome.summary)

    def test_invalid_schema_unknown_field_returns_failed_outcome(self) -> None:
        outcome = normalize_hermes_sdep_output(
            _request(),
            raw_output=json.dumps(
                {
                    "status": "success",
                    "elapsed_minutes": 1,
                    "risk_change": "reduced",
                    "followup_needed": False,
                    "summary": "Done.",
                    "notes": "extra",
                }
            ),
            elapsed_seconds=1.0,
            command=["hermes", "chat", "-q"],
        )

        self.assertEqual(outcome.status, "failed")
        self.assertIn("unknown fields", outcome.summary)
        self.assertIn("notes", outcome.summary)

    def test_invalid_schema_bool_elapsed_minutes_returns_failed_outcome(self) -> None:
        outcome = normalize_hermes_sdep_output(
            _request(),
            raw_output=json.dumps(
                {
                    "status": "success",
                    "elapsed_minutes": True,
                    "risk_change": "reduced",
                    "followup_needed": False,
                    "summary": "Done.",
                }
            ),
            elapsed_seconds=1.0,
            command=["hermes", "chat", "-q"],
        )

        self.assertEqual(outcome.status, "failed")
        self.assertIn("elapsed_minutes", outcome.summary)

    def test_timeout_raises_explicit_timeout_error(self) -> None:
        def run(command, **kwargs):
            raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

        runner = HermesCodexNativeRunner(timeout_seconds=2, runner=run)

        with self.assertRaises(HermesNativeTimeout) as raised:
            runner.execute(_request())

        self.assertEqual(raised.exception.to_details()["timeout_seconds"], 2)

    def test_nonzero_exit_raises_subprocess_error_with_details(self) -> None:
        runner = HermesCodexNativeRunner(
            runner=_runner_stdout("", returncode=9, stderr="fatal stderr")
        )

        with self.assertRaises(HermesNativeSubprocessError) as raised:
            runner.execute(_request())

        self.assertEqual(raised.exception.to_details()["exit_code"], 9)
        self.assertEqual(raised.exception.to_details()["stderr_excerpt"], "fatal stderr")

    def test_os_error_raises_subprocess_error(self) -> None:
        def run(command, **kwargs):
            raise OSError("missing hermes")

        runner = HermesCodexNativeRunner(runner=run)

        with self.assertRaises(HermesNativeSubprocessError) as raised:
            runner.execute(_request())

        self.assertEqual(str(raised.exception), "missing hermes")
        self.assertEqual(raised.exception.to_details(), {})


if __name__ == "__main__":
    unittest.main()
