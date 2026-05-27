from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spice.runtime import setup_workspace, update_workspace_config
from spice.runtime.executor_discovery import ExecutorCLIDetection
from spice.runtime.executor_status import (
    build_executor_status,
    render_executor_doctor,
    render_executor_list,
)


class ExecutorStatusTests(unittest.TestCase):
    def test_build_executor_status_lists_supported_executors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)

            status = build_executor_status(tmp_dir)

        executor_ids = {item["executor_id"] for item in status["executors"]}
        self.assertEqual(status["configured_executor"], "dry_run")
        self.assertIn("dry_run", executor_ids)
        self.assertIn("sdep_subprocess", executor_ids)
        self.assertIn("codex", executor_ids)
        self.assertIn("claude_code", executor_ids)
        self.assertIn("hermes", executor_ids)
        self.assertIn("openclaw", executor_ids)

    def test_render_executor_list_and_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            status = build_executor_status(tmp_dir)

        rendered_list = render_executor_list(status)
        rendered_doctor = render_executor_doctor(status)

        self.assertIn("Spice Executors", rendered_list)
        self.assertIn("configured: dry_run", rendered_list)
        self.assertIn("Spice Executor Doctor", rendered_doctor)
        self.assertIn("Resolved Runtime", rendered_doctor)

    def test_executor_status_includes_cli_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "codex")
            update_workspace_config(tmp_dir, "executor_command", "codex")
            detection = ExecutorCLIDetection(
                executor_id="codex",
                command_name="codex",
                status="broken_symlink",
                broken_symlink_path="/tmp/codex",
                broken_symlink_target="/missing/codex",
                detail="broken CLI symlink: /tmp/codex -> /missing/codex",
            )

            with patch(
                "spice.runtime.executor_status.detect_known_executor_clis",
                return_value={"codex": detection},
            ):
                status = build_executor_status(tmp_dir)

        codex = next(item for item in status["executors"] if item["executor_id"] == "codex")
        self.assertEqual(codex["configured"], True)
        self.assertEqual(codex["cli"]["status"], "broken_symlink")
        self.assertIn("configured_runtime", status)
        json.dumps(status, sort_keys=True)

    def test_executor_status_includes_openclaw_policy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "openclaw")
            update_workspace_config(tmp_dir, "executor_command", "openclaw agent --json --message")
            detection = ExecutorCLIDetection(
                executor_id="openclaw",
                command_name="openclaw",
                status="ready",
                command="openclaw",
                executable_path="/usr/local/bin/openclaw",
                detail="openclaw found on PATH: /usr/local/bin/openclaw",
            )

            with patch(
                "spice.runtime.executor_status.detect_known_executor_clis",
                return_value={"openclaw": detection},
            ):
                status = build_executor_status(tmp_dir)

        openclaw = next(item for item in status["executors"] if item["executor_id"] == "openclaw")
        self.assertEqual(openclaw["configured"], True)
        self.assertEqual(openclaw["cli"]["status"], "ready")
        self.assertEqual(openclaw["permission_enforcement"], "executor_policy")
        self.assertEqual(openclaw["resolved_runtime"]["permission_enforcement"], "executor_policy")
        self.assertIn("recommended_policy", openclaw["resolved_runtime"]["metadata"])


if __name__ == "__main__":
    unittest.main()
