from __future__ import annotations

import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

from spice.entry.cli import main as spice_cli_main
from spice.runtime import (
    LocalJsonStore,
    approve_approval,
    execute_openclaw_approval,
    run_once,
    setup_workspace,
)
from spice.runtime.openclaw_executor import execute_openclaw_sdep_request
from spice.runtime.workspace import update_workspace_config


NOW = datetime(2026, 4, 29, 6, 0, tzinfo=timezone.utc)


class RuntimeOpenClawExecutorTests(unittest.TestCase):
    def test_openclaw_sdep_endpoint_returns_valid_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store, _approval_id, run_id = _approved_handoff(tmp_dir)
            request = store.load_run(run_id)["full_loop_preview"]["sdep_request"]

            response = execute_openclaw_sdep_request(
                request,
                command=_fake_openclaw_command("openclaw fixture completed"),
            )

            self.assertEqual(response["message_type"], "execute.response")
            self.assertEqual(response["request_id"], request["request_id"])
            self.assertEqual(response["status"], "success")
            self.assertEqual(response["outcome"]["status"], "success")
            self.assertEqual(response["responder"]["id"], "openclaw")
            self.assertEqual(response["metadata"]["executor_provider"], "openclaw")
            self.assertEqual(response["metadata"]["permission_enforcement"], "executor_policy")
            self.assertEqual(
                response["traceability"]["approval_id"],
                request["traceability"]["approval_id"],
            )

    def test_openclaw_agent_command_receives_prompt_as_message_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store, _approval_id, run_id = _approved_handoff(tmp_dir)
            request = store.load_run(run_id)["full_loop_preview"]["sdep_request"]

            with patch("spice.runtime.openclaw_executor.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    args=["openclaw", "agent", "--json", "--message"],
                    returncode=0,
                    stdout="openclaw fixture completed",
                    stderr="",
                )

                response = execute_openclaw_sdep_request(
                    request,
                    command="openclaw agent --json --message",
                )

            called = run.call_args
            command = called.args[0]
            self.assertEqual(command[:4], ["openclaw", "agent", "--json", "--message"])
            self.assertIn("Fix the failing test.", command[4])
            self.assertIsNone(called.kwargs["input"])
            self.assertEqual(response["outcome"]["status"], "success")

    def test_openclaw_json_stdout_is_parsed_for_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store, _approval_id, run_id = _approved_handoff(tmp_dir)
            request = store.load_run(run_id)["full_loop_preview"]["sdep_request"]

            with patch("spice.runtime.openclaw_executor.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    args=["openclaw", "agent", "--json", "--message"],
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "summary": "OpenClaw JSON summary",
                            "details": {"status": "ok"},
                        }
                    ),
                    stderr="",
                )

                response = execute_openclaw_sdep_request(
                    request,
                    command="openclaw agent --json --message",
                )

            output = response["outcome"]["output"]
            self.assertEqual(output["summary"], "OpenClaw JSON summary")
            self.assertEqual(output["openclaw_json"]["details"]["status"], "ok")
            self.assertEqual(response["outcome"]["status"], "success")

    def test_openclaw_plain_stdout_records_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store, _approval_id, run_id = _approved_handoff(tmp_dir)
            request = store.load_run(run_id)["full_loop_preview"]["sdep_request"]

            with patch("spice.runtime.openclaw_executor.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    args=["openclaw", "agent", "--json", "--message"],
                    returncode=0,
                    stdout="plain openclaw summary\n",
                    stderr="",
                )

                response = execute_openclaw_sdep_request(
                    request,
                    command="openclaw agent --json --message",
                )

            output = response["outcome"]["output"]
            self.assertEqual(output["summary"], "plain openclaw summary")
            self.assertEqual(output["openclaw_json"], {})
            self.assertEqual(output["stdout"], "plain openclaw summary\n")

    def test_approved_approval_executes_through_openclaw_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store, approval_id, run_id = _approved_handoff(tmp_dir)

            result = execute_openclaw_approval(
                approval_id,
                project_root=tmp_dir,
                command=_fake_openclaw_command("openclaw fixture completed"),
                now=NOW,
            )

            artifact = result.artifact
            run_payload = store.load_run(run_id)
            outcome = store.load_outcome(artifact["outcome_id"])
            state = store.load_state()
            general = state["world_state"]["domain_state"]["general_decision"]
            self.assertEqual(artifact["executor_provider"], "openclaw")
            self.assertTrue(artifact["sdep_request_sent"])
            self.assertTrue(artifact["executor_called"])
            self.assertTrue(artifact["transport_executor_called"])
            self.assertTrue(artifact["real_executor_called"])
            self.assertEqual(artifact["protocol_status"], "success")
            self.assertEqual(artifact["task_status"], "success")
            self.assertEqual(outcome["executor_provider"], "openclaw")
            self.assertEqual(run_payload["executor_provider"], "openclaw")
            self.assertIn("openclaw_execution", run_payload)
            self.assertEqual(len(general["outcomes"]), 1)

    def test_default_execute_dispatch_uses_openclaw_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store, approval_id, _run_id = _approved_handoff(tmp_dir)
            update_workspace_config(tmp_dir, "executor", "openclaw")
            update_workspace_config(
                tmp_dir,
                "executor_command",
                shlex.join(_fake_openclaw_command("openclaw default dispatch")),
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = spice_cli_main(
                    [
                        "execute",
                        approval_id,
                        "--workspace",
                        tmp_dir,
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            artifact = json.loads(stdout.getvalue())
            self.assertEqual(artifact["executor_provider"], "openclaw")
            self.assertEqual(len(store.list_record_ids("outcomes")), 1)

    def test_cli_execute_openclaw_override_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store, approval_id, _run_id = _approved_handoff(tmp_dir)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = spice_cli_main(
                    [
                        "execute",
                        "openclaw",
                        approval_id,
                        "--workspace",
                        tmp_dir,
                        "--command",
                        shlex.join(_fake_openclaw_command("openclaw explicit override")),
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            artifact = json.loads(stdout.getvalue())
            self.assertEqual(artifact["executor_provider"], "openclaw")
            self.assertTrue(artifact["real_executor_called"])
            self.assertEqual(len(store.list_record_ids("outcomes")), 1)


def _pending_handoff(tmp_dir: str) -> tuple[LocalJsonStore, str, str]:
    setup_workspace(project_root=tmp_dir)
    result = run_once(
        "Fix the failing test.",
        project_root=tmp_dir,
        now=NOW,
        run_intent_mode="act",
    )
    store = LocalJsonStore.from_project_root(tmp_dir)
    return store, result.artifact["approval_id"], result.artifact["run_id"]


def _approved_handoff(tmp_dir: str) -> tuple[LocalJsonStore, str, str]:
    store, approval_id, run_id = _pending_handoff(tmp_dir)
    approve_approval(store, approval_id, now=NOW)
    return store, approval_id, run_id


def _fake_openclaw_command(message: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        (
            "import sys; "
            "prompt=sys.stdin.read(); "
            f"print({message!r} + ' prompt=' + str(len(prompt)))"
        ),
    ]


if __name__ == "__main__":
    unittest.main()
