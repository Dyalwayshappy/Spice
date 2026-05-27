from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

from spice.runtime import run_once, setup_workspace
from spice.runtime.executor_discovery import ExecutorCLIDetection
from spice.runtime.doctor import render_doctor_report, run_doctor


class RuntimeDoctorTests(unittest.TestCase):
    def test_doctor_reports_missing_workspace_as_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report = run_doctor(tmp_dir)

            self.assertEqual(report.status, "fail")
            names = {check.name: check for check in report.checks}
            self.assertEqual(names[".spice/"].status, "fail")
            self.assertIn("spice setup", names[".spice/"].next_step or "")

    def test_doctor_reports_setup_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)

            report = run_doctor(tmp_dir)
            payload = report.to_payload()
            rendered = render_doctor_report(report)

            self.assertIn(report.status, {"ok", "warn"})
            self.assertEqual(payload["workspace"], str(Path(tmp_dir) / ".spice"))
            self.assertIn("Spice Doctor - workspace check", rendered)
            names = {check.name: check for check in report.checks}
            self.assertEqual(names["config.json"].status, "ok")
            self.assertEqual(names["state.json"].status, "ok")
            self.assertEqual(names["llm provider"].detail, "deterministic")
            self.assertEqual(names["llm model"].detail, "deterministic.v1")
            self.assertEqual(names["llm candidate expansion"].detail, "disabled")
            self.assertEqual(names["llm simulation"].detail, "disabled")
            self.assertEqual(names["llm readiness"].detail, "rule-only mode")
            self.assertEqual(names["llm api key"].detail, "not needed for deterministic")
            self.assertEqual(names["memory provider"].status, "ok")
            self.assertEqual(names["memory provider"].detail, "file")
            self.assertEqual(names["memory path"].status, "ok")
            self.assertIn(".spice", names["memory path"].detail)
            self.assertEqual(names["context compiler"].status, "ok")
            self.assertEqual(names["context compiler"].detail, "deterministic")
            self.assertEqual(names["perception provider"].detail, "manual")
            self.assertEqual(names["perception poll source"].detail, "not needed for manual")
            self.assertEqual(names["perception trigger mode"].detail, "state_only")
            self.assertEqual(names["executor"].detail, "dry_run")
            self.assertEqual(names["executor runtime"].status, "ok")
            self.assertIn("transport=local_dry_run", names["executor runtime"].detail)
            self.assertFalse(names["executor runtime"].metadata["real_executor"])
            self.assertFalse(names["executor runtime"].metadata["sends_sdep_request"])
            self.assertEqual(names["executor_command"].detail, "not needed for dry_run")
            self.assertEqual(names["executor cli"].status, "ok")
            self.assertEqual(names["executor cli"].detail, "not needed for dry_run")

    def test_doctor_warns_for_openai_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "openai"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm provider"].status, "ok")
            self.assertEqual(names["llm api key"].status, "warn")
            self.assertEqual(names["llm readiness"].status, "warn")
            self.assertIn("OPENAI_API_KEY", names["llm api key"].detail)

    def test_doctor_accepts_openai_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "openai"
            config["llm_model"] = "gpt-4o-mini"
            config["llm_candidate_expand"] = "true"
            config["llm_simulation"] = "true"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm api key"].status, "ok")
            self.assertEqual(names["llm api key"].detail, "OPENAI_API_KEY set")
            self.assertEqual(names["llm model"].status, "ok")
            self.assertEqual(names["llm candidate expansion"].status, "ok")
            self.assertEqual(names["llm simulation"].status, "ok")
            self.assertEqual(names["llm readiness"].status, "ok")
            self.assertIn("ready", names["llm readiness"].detail)

    def test_doctor_warns_when_llm_features_enabled_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "openai"
            config["llm_candidate_expand"] = "true"
            config["llm_simulation"] = "true"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm model"].status, "warn")
            self.assertEqual(names["llm readiness"].status, "warn")
            self.assertIn("llm_model", names["llm readiness"].detail)

    def test_doctor_warns_for_anthropic_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "anthropic"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm provider"].status, "ok")
            self.assertEqual(names["llm api key"].status, "warn")
            self.assertIn("ANTHROPIC_API_KEY", names["llm api key"].detail)

    def test_doctor_accepts_anthropic_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "anthropic"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm api key"].status, "ok")
            self.assertEqual(names["llm api key"].detail, "ANTHROPIC_API_KEY set")

    def test_doctor_warns_for_deepseek_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "deepseek"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm provider"].status, "ok")
            self.assertEqual(names["llm api key"].status, "warn")
            self.assertIn("DEEPSEEK_API_KEY", names["llm api key"].detail)

    def test_doctor_accepts_deepseek_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "deepseek"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm api key"].status, "ok")
            self.assertEqual(names["llm api key"].detail, "DEEPSEEK_API_KEY set")

    def test_doctor_warns_for_mimo_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "mimo"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm provider"].status, "ok")
            self.assertEqual(names["llm api key"].status, "warn")
            self.assertIn("XIAOMI_API_KEY", names["llm api key"].detail)
            self.assertIn("MIMO_API_KEY", names["llm api key"].detail)

    def test_doctor_accepts_mimo_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "mimo"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {"XIAOMI_API_KEY": "test-key"}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm api key"].status, "ok")
            self.assertEqual(names["llm api key"].detail, "XIAOMI_API_KEY set")

    def test_doctor_accepts_mimo_legacy_api_key_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["llm_provider"] = "mimo"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {"MIMO_API_KEY": "test-key"}, clear=True):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["llm api key"].status, "ok")
            self.assertEqual(names["llm api key"].detail, "MIMO_API_KEY set")

    def test_doctor_warns_for_pending_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            run_once(
                "Fix the failing test.",
                project_root=tmp_dir,
                run_intent_mode="act",
            )

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["pending approvals"].status, "warn")
            self.assertEqual(names["pending approvals"].metadata["pending"], 1)

    def test_doctor_checks_sdep_executor_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "sdep_subprocess"
            config["executor_command"] = f"{sys.executable} -m spice.runtime.sdep_echo_executor"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["executor_command"].status, "ok")
            self.assertIn(sys.executable, names["executor_command"].detail)
            self.assertEqual(names["executor runtime"].status, "ok")
            self.assertEqual(
                names["executor runtime"].metadata["transport"],
                "sdep_subprocess",
            )

    def test_doctor_fails_for_missing_sdep_executor_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "sdep_subprocess"
            config["executor_command"] = ""
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(report.status, "fail")
            self.assertEqual(names["executor runtime"].status, "fail")
            self.assertEqual(names["executor_command"].status, "fail")
            self.assertIn("missing", names["executor_command"].detail)

    def test_doctor_accepts_codex_executor_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "codex"
            config["executor_command"] = sys.executable
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["executor"].status, "ok")
            self.assertEqual(names["executor"].detail, "codex")
            self.assertEqual(names["executor runtime"].status, "ok")
            self.assertEqual(
                names["executor runtime"].metadata["transport"],
                "sdep_subprocess_wrapper",
            )
            self.assertTrue(names["executor runtime"].metadata["real_executor"])
            self.assertEqual(names["executor_command"].status, "ok")
            self.assertEqual(names["executor_command"].detail, sys.executable)

    def test_doctor_reports_codex_broken_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "codex"
            config["executor_command"] = "codex"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            detection = ExecutorCLIDetection(
                executor_id="codex",
                command_name="codex",
                status="broken_symlink",
                broken_symlink_path="/Users/test/.local/bin/codex",
                broken_symlink_target="/missing/codex",
                detail="broken CLI symlink: /Users/test/.local/bin/codex -> /missing/codex",
            )

            with patch("spice.runtime.doctor.detect_executor_cli", return_value=detection):
                report = run_doctor(tmp_dir)

            names = {check.name: check for check in report.checks}
            self.assertEqual(report.status, "fail")
            self.assertEqual(names["executor cli"].status, "fail")
            self.assertIn("broken CLI symlink", names["executor cli"].detail)
            self.assertIn("install the CLI", names["executor cli"].next_step or "")
            self.assertEqual(
                names["executor cli"].metadata["broken_symlink_path"],
                "/Users/test/.local/bin/codex",
            )

    def test_doctor_reports_codex_app_only_cli_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "codex"
            config["executor_command"] = "codex"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            detection = ExecutorCLIDetection(
                executor_id="codex",
                command_name="codex",
                status="app_only",
                detected_apps=("/Applications/ChatGPT.app",),
                detail="codex app/extension detected, but no executable CLI command was found for Spice subprocess execution.",
            )

            with patch("spice.runtime.doctor.detect_executor_cli", return_value=detection):
                report = run_doctor(tmp_dir)

            names = {check.name: check for check in report.checks}
            self.assertEqual(names["executor cli"].status, "warn")
            self.assertIn("app/extension detected", names["executor cli"].detail)
            self.assertIn("Desktop apps and editor extensions", names["executor cli"].next_step or "")
            self.assertEqual(names["executor cli"].metadata["detected_apps"], ["/Applications/ChatGPT.app"])

    def test_doctor_reports_real_executor_cli_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "codex"
            config["executor_command"] = sys.executable
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            detection = ExecutorCLIDetection(
                executor_id="codex",
                command_name="codex",
                status="ready",
                command=sys.executable,
                executable_path=sys.executable,
                detail=f"codex found on PATH: {sys.executable}",
            )

            with patch("spice.runtime.doctor.detect_executor_cli", return_value=detection):
                report = run_doctor(tmp_dir)

            names = {check.name: check for check in report.checks}
            self.assertEqual(names["executor cli"].status, "ok")
            self.assertIn("codex found", names["executor cli"].detail)
            self.assertEqual(names["executor cli"].metadata["status"], "ready")

    def test_doctor_accepts_claude_code_executor_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "claude_code"
            config["executor_command"] = sys.executable
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["executor"].status, "ok")
            self.assertEqual(names["executor"].detail, "claude_code")
            self.assertEqual(names["executor_command"].status, "ok")
            self.assertEqual(names["executor_command"].detail, sys.executable)

    def test_doctor_accepts_hermes_executor_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "hermes"
            config["executor_command"] = sys.executable
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["executor"].status, "ok")
            self.assertEqual(names["executor"].detail, "hermes")
            self.assertEqual(names["executor_command"].status, "ok")
            self.assertEqual(names["executor_command"].detail, sys.executable)

    def test_doctor_accepts_openclaw_executor_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "openclaw"
            config["executor_command"] = sys.executable
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["executor"].status, "ok")
            self.assertEqual(names["executor"].detail, "openclaw")
            self.assertEqual(names["executor runtime"].status, "ok")
            self.assertIn("permission_enforcement=executor_policy", names["executor runtime"].detail)
            self.assertEqual(names["executor_command"].status, "ok")
            self.assertEqual(names["executor_command"].detail, sys.executable)

    def test_doctor_reports_openclaw_cli_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "openclaw"
            config["executor_command"] = "openclaw agent --json --message"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            detection = ExecutorCLIDetection(
                executor_id="openclaw",
                command_name="openclaw",
                status="ready",
                command="openclaw",
                executable_path="/usr/local/bin/openclaw",
                detail="openclaw found on PATH: /usr/local/bin/openclaw",
            )

            with patch("spice.runtime.doctor.detect_executor_cli", return_value=detection):
                report = run_doctor(tmp_dir)

            names = {check.name: check for check in report.checks}
            self.assertEqual(names["executor cli"].status, "ok")
            self.assertIn("openclaw found", names["executor cli"].detail)
            self.assertEqual(names["executor cli"].metadata["status"], "ready")

    def test_doctor_checks_poll_perception_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["perception_provider"] = "poll"
            config["perception_poll_url"] = "file:///tmp/status.txt"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["perception provider"].status, "ok")
            self.assertEqual(names["perception provider"].detail, "poll")
            self.assertEqual(names["perception poll source"].status, "ok")
            self.assertIn("file:///tmp/status.txt", names["perception poll source"].detail)

    def test_doctor_warns_for_poll_without_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["perception_provider"] = "poll"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["perception poll source"].status, "warn")
            self.assertIn("no URL or command", names["perception poll source"].detail)

    def test_doctor_warns_for_poll_command_without_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["perception_provider"] = "poll"
            config["perception_poll_command"] = sys.executable
            config["perception_allow_command_poll"] = "false"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["perception poll source"].status, "warn")
            self.assertIn("disabled", names["perception poll source"].detail)

    def test_doctor_accepts_poll_command_with_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["perception_provider"] = "poll"
            config["perception_poll_command"] = sys.executable
            config["perception_allow_command_poll"] = "true"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["perception poll source"].status, "ok")
            self.assertIn(sys.executable, names["perception poll source"].detail)

    def test_doctor_checks_open_chronicle_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["perception_provider"] = "open_chronicle"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch("spice.runtime.doctor.urllib.request.urlopen", return_value=_FakeDoctorResponse()):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["perception provider"].status, "ok")
            self.assertEqual(names["perception provider"].detail, "open_chronicle")
            self.assertEqual(names["open chronicle"].status, "ok")
            self.assertIn("MCP reachable", names["open chronicle"].detail)

    def test_doctor_warns_when_open_chronicle_endpoint_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["perception_provider"] = "open_chronicle"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch("spice.runtime.doctor.urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
                report = run_doctor(tmp_dir)
            names = {check.name: check for check in report.checks}

            self.assertEqual(names["open chronicle"].status, "warn")
            self.assertIn("MCP not reachable", names["open chronicle"].detail)


if __name__ == "__main__":
    unittest.main()


class _FakeDoctorResponse:
    def __enter__(self) -> "_FakeDoctorResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return b'{"jsonrpc":"2.0","result":{"tools":[]}}'
