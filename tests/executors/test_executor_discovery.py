from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spice.runtime.executor_discovery import detect_executor_cli, detect_known_executor_clis


class ExecutorDiscoveryTests(unittest.TestCase):
    def test_detects_cli_from_path_lookup(self) -> None:
        detection = detect_executor_cli(
            "codex",
            which=lambda command: f"/usr/local/bin/{command}",
            search_paths=[],
        )

        self.assertEqual(detection.status, "ready")
        self.assertEqual(detection.command, "codex")
        self.assertEqual(detection.executable_path, "/usr/local/bin/codex")

    def test_detects_openclaw_cli_from_path_lookup(self) -> None:
        detection = detect_executor_cli(
            "openclaw",
            which=lambda command: f"/usr/local/bin/{command}",
            search_paths=[],
        )

        self.assertEqual(detection.status, "ready")
        self.assertEqual(detection.command, "openclaw")
        self.assertEqual(detection.executable_path, "/usr/local/bin/openclaw")

    def test_detects_executable_outside_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            command = Path(tmp_dir) / "codex"
            command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            command.chmod(command.stat().st_mode | 0o111)

            detection = detect_executor_cli(
                "codex",
                which=lambda command_name: None,
                search_paths=[command],
            )

        self.assertEqual(detection.status, "ready")
        self.assertEqual(detection.command, str(command))
        self.assertEqual(detection.executable_path, str(command))

    def test_detects_broken_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            link = Path(tmp_dir) / "codex"
            missing_target = Path(tmp_dir) / "missing-codex"
            link.symlink_to(missing_target)

            detection = detect_executor_cli(
                "codex",
                which=lambda command_name: None,
                search_paths=[link],
            )

        self.assertEqual(detection.status, "broken_symlink")
        self.assertEqual(detection.broken_symlink_path, str(link))
        self.assertEqual(detection.broken_symlink_target, str(missing_target))

    def test_unsupported_executor_is_structured(self) -> None:
        detection = detect_executor_cli("unknown", which=lambda command_name: None, search_paths=[])

        self.assertEqual(detection.status, "unsupported")
        self.assertIn("supports codex", detection.detail)
        self.assertIn("openclaw", detection.detail)

    def test_known_executor_detection_includes_openclaw(self) -> None:
        detections = detect_known_executor_clis()

        self.assertIn("codex", detections)
        self.assertIn("claude_code", detections)
        self.assertIn("hermes", detections)
        self.assertIn("openclaw", detections)


if __name__ == "__main__":
    unittest.main()
