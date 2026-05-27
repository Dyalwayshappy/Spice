from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from spice.decision.general.approval import Approval
from spice.entry.cli import main as spice_cli_main
from spice.runtime import LocalJsonStore


class SetupCLITests(unittest.TestCase):
    def test_spice_setup_creates_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stdout_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer):
                exit_code = spice_cli_main(["setup", "--workspace", tmp_dir])

            spice_dir = Path(tmp_dir) / ".spice"
            self.assertEqual(exit_code, 0)
            self.assertIn("Spice workspace initialized.", stdout_buffer.getvalue())
            self.assertTrue((spice_dir / "config.json").exists())
            self.assertTrue((spice_dir / "decision.md").exists())
            self.assertTrue((spice_dir / "state" / "state.json").exists())

            config = json.loads((spice_dir / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["llm_provider"], "deterministic")
            self.assertEqual(config["executor"], "dry_run")
            self.assertEqual(config["workspace_perception"]["depth"], "auto")
            self.assertIn("spice session list", stdout_buffer.getvalue())
            self.assertIn("spice decide", stdout_buffer.getvalue())
            self.assertIn("--decision-only", stdout_buffer.getvalue())
            self.assertIn("--act", stdout_buffer.getvalue())
            self.assertIn("--advise", stdout_buffer.getvalue())

    def test_spice_setup_is_idempotent_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stdout_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer):
                first = spice_cli_main(["setup", "--workspace", tmp_dir])
                second = spice_cli_main(["setup", "--workspace", tmp_dir])

            self.assertEqual(first, 0)
            self.assertEqual(second, 0)

    def test_spice_setup_defaults_flag_skips_interactive_wizard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stdout_buffer = io.StringIO()
            with patch("spice.entry.cli.run_setup_wizard") as wizard:
                with redirect_stdout(stdout_buffer):
                    exit_code = spice_cli_main(["setup", "--workspace", tmp_dir, "--defaults"])

            self.assertEqual(exit_code, 0)
            wizard.assert_not_called()
            self.assertTrue((Path(tmp_dir) / ".spice" / "config.json").exists())

    def test_spice_setup_tty_uses_interactive_wizard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("spice.entry.cli.sys.stdin.isatty", return_value=True):
                with patch("spice.entry.cli.run_setup_wizard", return_value=object()) as wizard:
                    exit_code = spice_cli_main(["setup", "--workspace", tmp_dir])

            self.assertEqual(exit_code, 0)
            wizard.assert_called_once()

    def test_spice_doctor_outputs_workspace_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                doctor_code = spice_cli_main(["doctor", "--workspace", tmp_dir])

            self.assertEqual(setup_code, 0)
            self.assertEqual(doctor_code, 0)
            output = stdout.getvalue()
            self.assertIn("Spice Doctor - workspace check", output)
            self.assertIn("config.json", output)
            self.assertIn("executor_command", output)

    def test_spice_doctor_json_outputs_parseable_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                doctor_code = spice_cli_main(["doctor", "--workspace", tmp_dir, "--json"])

            self.assertEqual(setup_code, 0)
            self.assertEqual(doctor_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertIn(report["status"], {"ok", "warn"})
            self.assertTrue(any(check["name"] == "config.json" for check in report["checks"]))

    def test_spice_context_outputs_compiled_decision_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                context_code = spice_cli_main(["context", "--workspace", tmp_dir])

            self.assertEqual(setup_code, 0)
            self.assertEqual(context_code, 0)
            output = stdout.getvalue()
            self.assertIn("COMPILED DECISION CONTEXT", output)
            self.assertIn("context_type: decision", output)
            self.assertIn("executor_capabilities:", output)
            self.assertIn("workspace:", output)

    def test_spice_context_json_outputs_exact_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
                run_code = spice_cli_main(
                    [
                        "decide",
                        "Pick the safest next action.",
                        "--workspace",
                        tmp_dir,
                        "--decision-only",
                    ]
                )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                context_code = spice_cli_main(["context", "--workspace", tmp_dir, "--json"])

            self.assertEqual(setup_code, 0)
            self.assertEqual(run_code, 0)
            self.assertEqual(context_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["context_type"], "decision")
            self.assertEqual(payload["domain"], "general")
            self.assertEqual(payload["workspace_context"]["memory_provider"], "file")
            self.assertEqual(payload["workspace_context"]["context_compiler"], "deterministic")
            self.assertEqual(payload["executor_capabilities"]["executor_id"], "dry_run")
            self.assertEqual(payload["executor_capabilities"]["source"], "static_baseline")
            self.assertEqual(
                payload["current_intent"]["text"],
                "Pick the safest next action.",
            )
            self.assertTrue(payload["active_decision_frame"]["decision_id"])

    def test_spice_executor_list_outputs_supported_executors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                list_code = spice_cli_main(["executor", "list", "--workspace", tmp_dir])

            self.assertEqual(setup_code, 0)
            self.assertEqual(list_code, 0)
            output = stdout.getvalue()
            self.assertIn("Spice Executors", output)
            self.assertIn("dry_run", output)
            self.assertIn("codex", output)
            self.assertIn("openclaw", output)

    def test_spice_executor_list_json_is_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                list_code = spice_cli_main(["executor", "list", "--workspace", tmp_dir, "--json"])

            self.assertEqual(setup_code, 0)
            self.assertEqual(list_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["configured_executor"], "dry_run")
            self.assertTrue(any(item["executor_id"] == "dry_run" for item in payload["executors"]))
            openclaw = next(item for item in payload["executors"] if item["executor_id"] == "openclaw")
            self.assertEqual(openclaw["permission_enforcement"], "executor_policy")

    def test_spice_executor_doctor_outputs_runtime_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                doctor_code = spice_cli_main(["executor", "doctor", "--workspace", tmp_dir])

            self.assertEqual(setup_code, 0)
            self.assertEqual(doctor_code, 0)
            output = stdout.getvalue()
            self.assertIn("Spice Executor Doctor", output)
            self.assertIn("Resolved Runtime", output)
            self.assertIn("CLI Discovery", output)

    def test_spice_config_show_and_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            set_stdout = io.StringIO()
            show_stdout = io.StringIO()
            with redirect_stdout(set_stdout):
                set_code = spice_cli_main(
                    ["config", "set", "executor", "sdep_subprocess", "--workspace", tmp_dir]
                )
            perception_stdout = io.StringIO()
            with redirect_stdout(perception_stdout):
                perception_code = spice_cli_main(
                    [
                        "config",
                        "set",
                        "workspace_perception.depth",
                        "deep",
                        "--workspace",
                        tmp_dir,
                    ]
                )
            with redirect_stdout(show_stdout):
                show_code = spice_cli_main(["config", "show", "--workspace", tmp_dir])

            self.assertEqual(setup_code, 0)
            self.assertEqual(set_code, 0)
            self.assertEqual(perception_code, 0)
            self.assertEqual(show_code, 0)
            self.assertIn("Set executor = sdep_subprocess", set_stdout.getvalue())
            self.assertIn("Set workspace_perception.depth = deep", perception_stdout.getvalue())
            self.assertIn("executor", show_stdout.getvalue())
            self.assertIn("sdep_subprocess", show_stdout.getvalue())
            self.assertIn("workspace_perception.depth", show_stdout.getvalue())
            self.assertIn("deep", show_stdout.getvalue())
            self.assertIn("perception_poll_url", show_stdout.getvalue())
            self.assertIn("perception_allow_command_poll", show_stdout.getvalue())
            self.assertIn("openchronicle_mcp_url", show_stdout.getvalue())
            self.assertIn("spice config enable-llm", show_stdout.getvalue())
            self.assertIn("Resolved Executor Runtime", show_stdout.getvalue())
            self.assertIn("transport", show_stdout.getvalue())
            self.assertIn("sdep_subprocess", show_stdout.getvalue())

    def test_spice_config_enable_llm_sets_provider_model_and_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                enable_code = spice_cli_main(
                    [
                        "config",
                        "enable-llm",
                        "--provider",
                        "openai",
                        "--model",
                        "gpt-4o-mini",
                        "--workspace",
                        tmp_dir,
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(enable_code, 0)
            output = stdout.getvalue()
            self.assertIn("LLM features configured.", output)
            self.assertIn("llm_provider=openai", output)
            self.assertIn("OPENAI_API_KEY", output)
            config = json.loads(
                (Path(tmp_dir) / ".spice" / "config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(config["llm_provider"], "openai")
            self.assertEqual(config["llm_model"], "gpt-4o-mini")
            self.assertEqual(config["llm_candidate_expand"], "true")
            self.assertEqual(config["llm_simulation"], "true")

    def test_spice_config_enable_llm_can_disable_individual_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                enable_code = spice_cli_main(
                    [
                        "config",
                        "enable-llm",
                        "--provider",
                        "openai",
                        "--model",
                        "gpt-4o-mini",
                        "--no-simulation",
                        "--workspace",
                        tmp_dir,
                        "--json",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(enable_code, 0)
            config = json.loads(stdout.getvalue())
            self.assertEqual(config["llm_candidate_expand"], "true")
            self.assertEqual(config["llm_simulation"], "false")

    def test_spice_config_enable_llm_requires_model_for_external_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                enable_code = spice_cli_main(
                    [
                        "config",
                        "enable-llm",
                        "--provider",
                        "openai",
                        "--workspace",
                        tmp_dir,
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(enable_code, 1)
            self.assertIn("llm_model is required", stderr.getvalue())

    def test_spice_config_show_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                show_code = spice_cli_main(["config", "show", "--workspace", tmp_dir, "--json"])

            self.assertEqual(setup_code, 0)
            self.assertEqual(show_code, 0)
            config = json.loads(stdout.getvalue())
            self.assertEqual(config["executor"], "dry_run")
            self.assertEqual(config["resolved_executor_runtime"]["executor_id"], "dry_run")
            self.assertEqual(
                config["resolved_executor_runtime"]["transport"],
                "local_dry_run",
            )
            self.assertFalse(config["resolved_executor_runtime"]["real_executor"])

    def test_spice_config_set_rejects_unknown_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                set_code = spice_cli_main(
                    ["config", "set", "executor.command", "x", "--workspace", tmp_dir]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(set_code, 1)
            self.assertIn("Unknown config key", stderr.getvalue())
            self.assertIn("Next:", stderr.getvalue())

    def test_spice_config_set_active_session_requires_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                set_code = spice_cli_main(
                    [
                        "config",
                        "set",
                        "active_session_id",
                        "session.missing",
                        "--workspace",
                        tmp_dir,
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(set_code, 1)
            self.assertIn("Session does not exist", stderr.getvalue())

    def test_spice_config_show_missing_workspace_has_friendly_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                show_code = spice_cli_main(["config", "show", "--workspace", tmp_dir])

            self.assertEqual(show_code, 1)
            self.assertIn("config show failed", stderr.getvalue())
            self.assertIn("spice setup", stderr.getvalue())

    def test_spice_run_once_prints_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_stdout = io.StringIO()
            run_stdout = io.StringIO()
            with redirect_stdout(setup_stdout):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            with redirect_stdout(run_stdout):
                run_code = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Review the project and pick the safest next action.",
                        "--json",
                        "--no-bars",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(run_code, 0)
            artifact = json.loads(run_stdout.getvalue())
            self.assertEqual(artifact["path_type"], "manual_intent_run_once")
            self.assertEqual(artifact["loop_mode"], "full_loop_preview")
            self.assertFalse(artifact["executor_called"])
            self.assertFalse(artifact["sdep_request_sent"])
            self.assertTrue(artifact["persisted"])
            self.assertEqual(artifact["persist_mode"], "active_state")
            self.assertIn("compare_payload", artifact)
            self.assertIn("full_loop_preview", artifact)

    def test_spice_decide_prints_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_stdout = io.StringIO()
            decide_stdout = io.StringIO()
            with redirect_stdout(setup_stdout):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            with redirect_stdout(decide_stdout):
                decide_code = spice_cli_main(
                    [
                        "decide",
                        "Review the project and pick the safest next action.",
                        "--workspace",
                        tmp_dir,
                        "--json",
                        "--no-bars",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(decide_code, 0)
            artifact = json.loads(decide_stdout.getvalue())
            self.assertEqual(artifact["path_type"], "manual_intent_run_once")
            self.assertEqual(artifact["source"], "manual_intent")
            self.assertEqual(artifact["loop_mode"], "full_loop_preview")
            self.assertEqual(artifact["input"]["text"], "Review the project and pick the safest next action.")

    def test_spice_run_once_rich_uses_rich_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            run_stdout = io.StringIO()
            with patch("spice.entry.cli.render_compare_rich", return_value="RICH CARD") as rich:
                with redirect_stdout(run_stdout):
                    run_code = spice_cli_main(
                        [
                            "run",
                            "--workspace",
                            tmp_dir,
                            "--once",
                            "Review the project and pick the safest next action.",
                            "--rich",
                            "--no-bars",
                        ]
                    )

            self.assertEqual(setup_code, 0)
            self.assertEqual(run_code, 0)
            rich.assert_called_once()
            self.assertIn("RICH CARD", run_stdout.getvalue())
            self.assertIn("Artifacts:", run_stdout.getvalue())

    def test_spice_decide_rich_uses_rich_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            decide_stdout = io.StringIO()
            with patch("spice.entry.cli.render_compare_rich", return_value="RICH DECISION") as rich:
                with redirect_stdout(decide_stdout):
                    decide_code = spice_cli_main(
                        [
                            "decide",
                            "Review the project and pick the safest next action.",
                            "--workspace",
                            tmp_dir,
                            "--rich",
                            "--no-bars",
                        ]
                    )

            self.assertEqual(setup_code, 0)
            self.assertEqual(decide_code, 0)
            rich.assert_called_once()
            self.assertIn("RICH DECISION", decide_stdout.getvalue())
            self.assertIn("Artifacts:", decide_stdout.getvalue())

    def test_spice_decide_act_can_create_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            decide_stdout = io.StringIO()
            with redirect_stdout(decide_stdout):
                decide_code = spice_cli_main(
                    [
                        "decide",
                        "Fix the failing test.",
                        "--workspace",
                        tmp_dir,
                        "--act",
                        "--json",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(decide_code, 0)
            artifact = json.loads(decide_stdout.getvalue())
            self.assertEqual(artifact["run_intent_mode"], "act")
            self.assertTrue(artifact["handoff_required"])
            self.assertIsNotNone(artifact["approval_id"])
            self.assertEqual(artifact["approval"]["status"], "pending")

    def test_spice_run_once_no_persist_prints_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_stdout = io.StringIO()
            run_stdout = io.StringIO()
            with redirect_stdout(setup_stdout):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            with redirect_stdout(run_stdout):
                run_code = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Review the project without persisting state.",
                        "--json",
                        "--no-persist",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(run_code, 0)
            artifact = json.loads(run_stdout.getvalue())
            self.assertFalse(artifact["persisted"])
            self.assertEqual(artifact["persist_mode"], "no_persist")
            self.assertTrue(artifact["state_after_ref"].startswith("preview:"))

    def test_spice_run_once_prints_full_loop_json_artifact_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            run_stdout = io.StringIO()
            with redirect_stdout(run_stdout):
                run_code = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Review the project and pick the safest next action.",
                        "--json",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(run_code, 0)
            artifact = json.loads(run_stdout.getvalue())
            self.assertEqual(artifact["loop_mode"], "full_loop_preview")
            self.assertIn("full_loop_preview", artifact)
            self.assertFalse(artifact["full_loop_preview"]["executor_called"])
            self.assertFalse(artifact["full_loop_preview"]["sdep_request_sent"])
            self.assertIn("context_pack", artifact["full_loop_preview"])

    def test_spice_run_once_decision_only_flag_stops_before_handoff_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            run_stdout = io.StringIO()
            with redirect_stdout(run_stdout):
                run_code = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Review the project and pick the safest next action.",
                        "--json",
                        "--decision-only",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(run_code, 0)
            artifact = json.loads(run_stdout.getvalue())
            self.assertEqual(artifact["loop_mode"], "decision_only")
            self.assertNotIn("full_loop_preview", artifact)

    def test_spice_run_once_act_and_advise_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])

            act_stdout = io.StringIO()
            with redirect_stdout(act_stdout):
                act_code = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Fix the failing test.",
                        "--json",
                        "--act",
                    ]
                )

            advise_stdout = io.StringIO()
            with redirect_stdout(advise_stdout):
                advise_code = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "What should I do next?",
                        "--json",
                        "--advise",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(act_code, 0)
            self.assertEqual(advise_code, 0)
            act_artifact = json.loads(act_stdout.getvalue())
            advise_artifact = json.loads(advise_stdout.getvalue())
            self.assertEqual(act_artifact["run_intent_mode"], "act")
            self.assertTrue(act_artifact["handoff_required"])
            self.assertTrue(act_artifact["approval_id"])
            self.assertEqual(act_artifact["approval"]["status"], "pending")
            self.assertEqual(advise_artifact["run_intent_mode"], "advise")
            self.assertEqual(advise_artifact["loop_mode"], "decision_only")
            self.assertNotIn("full_loop_preview", advise_artifact)

    def test_spice_session_list_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_stdout = io.StringIO()
            run_stdout = io.StringIO()
            list_stdout = io.StringIO()
            resume_stdout = io.StringIO()
            with redirect_stdout(setup_stdout):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            with redirect_stdout(run_stdout):
                run_code = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Review the current project.",
                        "--json",
                    ]
                )
            with redirect_stdout(list_stdout):
                list_code = spice_cli_main(["session", "list", "--workspace", tmp_dir])
            with redirect_stdout(resume_stdout):
                resume_code = spice_cli_main(
                    ["session", "resume", "session.default", "--workspace", tmp_dir]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(run_code, 0)
            self.assertEqual(list_code, 0)
            self.assertEqual(resume_code, 0)
            self.assertIn("SPICE SESSIONS", list_stdout.getvalue())
            self.assertIn("session.default", list_stdout.getvalue())
            self.assertIn("SPICE SESSION RESUME", resume_stdout.getvalue())
            self.assertIn("LAST DECISION", resume_stdout.getvalue())

    def test_spice_session_resume_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                spice_cli_main(["setup", "--workspace", tmp_dir])
            with redirect_stdout(io.StringIO()):
                spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Review the current project.",
                    ]
                )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = spice_cli_main(
                    ["session", "resume", "session.default", "--workspace", tmp_dir, "--json"]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["session_id"], "session.default")
            self.assertEqual(len(payload["run_ids"]), 1)

    def test_spice_session_show_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                spice_cli_main(["setup", "--workspace", tmp_dir])
            with redirect_stdout(io.StringIO()):
                spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Review the current project.",
                    ]
                )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = spice_cli_main(
                    ["session", "show", "session.default", "--workspace", tmp_dir]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("SPICE SESSION RESUME", stdout.getvalue())
            self.assertIn("RESUME COMMANDS", stdout.getvalue())

    def test_spice_session_resume_start_enters_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                spice_cli_main(["setup", "--workspace", tmp_dir])
            with redirect_stdout(io.StringIO()):
                spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--session-id",
                        "session.work",
                        "--once",
                        "Review the current project.",
                    ]
                )
            stdout = io.StringIO()
            with patch("sys.stdin", io.StringIO("/session\n/exit\n")):
                with redirect_stdout(stdout):
                    exit_code = spice_cli_main(
                        [
                            "session",
                            "resume",
                            "session.work",
                            "--workspace",
                            tmp_dir,
                            "--start",
                        ]
                    )

            self.assertEqual(exit_code, 0)
            text = stdout.getvalue()
            self.assertIn("Spice Agent", text)
            self.assertIn("session: session.work", text)
            self.assertIn("SPICE SESSION RESUME", text)

    def test_spice_session_resume_start_rejects_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                spice_cli_main(["setup", "--workspace", tmp_dir])
            with redirect_stdout(io.StringIO()):
                spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--session-id",
                        "session.work",
                        "--once",
                        "Review the current project.",
                    ]
                )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = spice_cli_main(
                    [
                        "session",
                        "resume",
                        "session.work",
                        "--workspace",
                        tmp_dir,
                        "--json",
                        "--start",
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertIn("--json cannot be combined with --start", stderr.getvalue())

    def test_spice_approval_list_show_and_approve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            store = LocalJsonStore.from_project_root(tmp_dir)
            approval = Approval(
                approval_id="approval.cli.1",
                decision_id="decision.cli.1",
                candidate_id="candidate.cli.1",
                status="pending",
                requested_at="2026-04-29T06:00:00+00:00",
            )
            store.save_approval(approval.approval_id, approval.to_payload())
            store.save_session(
                "session.default",
                {
                    "session_id": "session.default",
                    "created_at": "2026-04-29T06:00:00+00:00",
                    "updated_at": "2026-04-29T06:00:00+00:00",
                    "status": "active",
                    "run_ids": [],
                    "decision_ids": [approval.decision_id],
                    "approval_ids": [approval.approval_id],
                    "pending_approval_ids": [approval.approval_id],
                    "metadata": {},
                },
            )

            list_stdout = io.StringIO()
            show_stdout = io.StringIO()
            approve_stdout = io.StringIO()
            with redirect_stdout(list_stdout):
                list_code = spice_cli_main(["approval", "list", "--workspace", tmp_dir])
            with redirect_stdout(show_stdout):
                show_code = spice_cli_main(
                    ["approval", "show", "approval.cli.1", "--workspace", tmp_dir]
                )
            with redirect_stdout(approve_stdout):
                approve_code = spice_cli_main(
                    [
                        "approval",
                        "approve",
                        "approval.cli.1",
                        "--workspace",
                        tmp_dir,
                        "--json",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(list_code, 0)
            self.assertEqual(show_code, 0)
            self.assertEqual(approve_code, 0)
            self.assertIn("SPICE APPROVALS", list_stdout.getvalue())
            self.assertIn("SPICE APPROVAL", show_stdout.getvalue())
            payload = json.loads(approve_stdout.getvalue())
            self.assertEqual(payload["approval"]["status"], "approved")
            self.assertFalse(payload["executor_called"])
            self.assertFalse(payload["sdep_request_sent"])
            self.assertEqual(store.load_session("session.default")["pending_approval_ids"], [])

    def test_product_runtime_smoke_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_stdout = io.StringIO()
            first_run_stdout = io.StringIO()
            session_stdout = io.StringIO()
            preview_stdout = io.StringIO()

            with redirect_stdout(setup_stdout):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            with redirect_stdout(first_run_stdout):
                first_code = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Review the project and pick the safest next action.",
                        "--no-bars",
                    ]
                )
            with redirect_stdout(session_stdout):
                session_code = spice_cli_main(["session", "list", "--workspace", tmp_dir])
            with redirect_stdout(preview_stdout):
                preview_code = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--once",
                        "Review the project and pick the safest next action.",
                        "--no-bars",
                    ]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(first_code, 0)
            self.assertEqual(session_code, 0)
            self.assertEqual(preview_code, 0)
            self.assertIn("SPICE DECISION LOOP", first_run_stdout.getvalue())
            self.assertIn("SPICE SESSIONS", session_stdout.getvalue())
            self.assertIn("SPICE DECISION LOOP", preview_stdout.getvalue())
            self.assertIn("SKILL RESOLUTION", preview_stdout.getvalue())
            self.assertIn("CONTEXT PACK", preview_stdout.getvalue())
            self.assertIn("sdep_request_sent: false", preview_stdout.getvalue())
            self.assertIn("executor_called: false", preview_stdout.getvalue())

    def test_spice_execute_uses_default_dry_run_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            decide_stdout = io.StringIO()
            with redirect_stdout(decide_stdout):
                decide_code = spice_cli_main(
                    [
                        "decide",
                        "Fix the failing test.",
                        "--workspace",
                        tmp_dir,
                        "--act",
                        "--json",
                    ]
                )
            approval_id = json.loads(decide_stdout.getvalue())["approval_id"]
            with redirect_stdout(io.StringIO()):
                approve_code = spice_cli_main(
                    ["approval", "approve", approval_id, "--workspace", tmp_dir]
                )
            execute_stdout = io.StringIO()
            with redirect_stdout(execute_stdout):
                execute_code = spice_cli_main(
                    ["execute", approval_id, "--workspace", tmp_dir, "--json"]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(decide_code, 0)
            self.assertEqual(approve_code, 0)
            self.assertEqual(execute_code, 0)
            artifact = json.loads(execute_stdout.getvalue())
            self.assertEqual(artifact["executor_provider"], "dry_run")
            self.assertTrue(artifact["dry_run_executor_called"])

    def test_spice_execute_uses_sdep_subprocess_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "sdep_subprocess"
            config["executor_command"] = f"{sys.executable} -m spice.runtime.sdep_echo_executor"
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            decide_stdout = io.StringIO()
            with redirect_stdout(decide_stdout):
                decide_code = spice_cli_main(
                    [
                        "decide",
                        "Fix the failing test.",
                        "--workspace",
                        tmp_dir,
                        "--act",
                        "--json",
                    ]
                )
            approval_id = json.loads(decide_stdout.getvalue())["approval_id"]
            with redirect_stdout(io.StringIO()):
                approve_code = spice_cli_main(
                    ["approval", "approve", approval_id, "--workspace", tmp_dir]
                )
            execute_stdout = io.StringIO()
            with redirect_stdout(execute_stdout):
                execute_code = spice_cli_main(
                    ["execute", approval_id, "--workspace", tmp_dir, "--json"]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(decide_code, 0)
            self.assertEqual(approve_code, 0)
            self.assertEqual(execute_code, 0)
            artifact = json.loads(execute_stdout.getvalue())
            self.assertEqual(artifact["executor_provider"], "sdep_subprocess")
            self.assertTrue(artifact["sdep_request_sent"])
            self.assertTrue(artifact["transport_executor_called"])

    def test_spice_run_without_once_starts_interactive_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stdout = io.StringIO()
            with patch("sys.stdin", io.StringIO("/help\n/exit\n")):
                with redirect_stdout(stdout):
                    exit_code = spice_cli_main(["run", "--workspace", tmp_dir])

            self.assertEqual(setup_code, 0)
            self.assertEqual(exit_code, 0)
            self.assertIn("Spice Agent", stdout.getvalue())
            self.assertIn("/act <intent>", stdout.getvalue())
            self.assertIn("/dry-run <id>", stdout.getvalue())

    def test_spice_without_subcommand_enters_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            cwd = os.getcwd()
            try:
                os.chdir(tmp_dir)
                with patch("spice.entry.cli.run_tui_shell") as shell:
                    shell.return_value = object()
                    exit_code = spice_cli_main([])
            finally:
                os.chdir(cwd)

            self.assertEqual(setup_code, 0)
            self.assertEqual(exit_code, 0)
            shell.assert_called_once()
            self.assertEqual(shell.call_args.kwargs["project_root"], Path("."))

    def test_spice_run_plain_uses_tui_entrypoint_with_plain_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            with patch("spice.entry.cli.run_tui_shell") as shell:
                shell.return_value = object()
                exit_code = spice_cli_main(["run", "--workspace", tmp_dir, "--plain"])

            self.assertEqual(setup_code, 0)
            self.assertEqual(exit_code, 0)
            shell.assert_called_once()
            self.assertTrue(shell.call_args.kwargs["plain"])

    def test_session_current_switch_archive_timeline_search_stats_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
                first_run = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--session-id",
                        "session.alpha",
                        "--once",
                        "Review auth decisions.",
                        "--json",
                    ]
                )
                second_run = spice_cli_main(
                    [
                        "run",
                        "--workspace",
                        tmp_dir,
                        "--session-id",
                        "session.alpha",
                        "--once",
                        "Plan billing decisions.",
                        "--json",
                    ]
                )

            switch_stdout = io.StringIO()
            with redirect_stdout(switch_stdout):
                switch_code = spice_cli_main(["session", "switch", "session.alpha", "--workspace", tmp_dir])
            current_stdout = io.StringIO()
            with redirect_stdout(current_stdout):
                current_code = spice_cli_main(["session", "current", "--workspace", tmp_dir])
            timeline_stdout = io.StringIO()
            with redirect_stdout(timeline_stdout):
                timeline_code = spice_cli_main(["session", "timeline", "session.alpha", "--workspace", tmp_dir])
            search_stdout = io.StringIO()
            with redirect_stdout(search_stdout):
                search_code = spice_cli_main(["session", "search", "billing", "--workspace", tmp_dir])
            stats_stdout = io.StringIO()
            with redirect_stdout(stats_stdout):
                stats_code = spice_cli_main(["session", "stats", "--workspace", tmp_dir])
            archive_stdout = io.StringIO()
            with redirect_stdout(archive_stdout):
                archive_code = spice_cli_main(["session", "archive", "session.alpha", "--workspace", tmp_dir])
            list_stdout = io.StringIO()
            with redirect_stdout(list_stdout):
                list_code = spice_cli_main(["session", "list", "--workspace", tmp_dir])
            list_all_stdout = io.StringIO()
            with redirect_stdout(list_all_stdout):
                list_all_code = spice_cli_main(["session", "list", "--all", "--workspace", tmp_dir])
            delete_stdout = io.StringIO()
            with redirect_stdout(delete_stdout):
                delete_code = spice_cli_main(
                    ["session", "delete", "session.alpha", "--cascade", "--force", "--workspace", tmp_dir]
                )

            self.assertEqual(setup_code, 0)
            self.assertEqual(first_run, 0)
            self.assertEqual(second_run, 0)
            self.assertEqual(switch_code, 0)
            self.assertEqual(current_code, 0)
            self.assertEqual(timeline_code, 0)
            self.assertEqual(search_code, 0)
            self.assertEqual(stats_code, 0)
            self.assertEqual(archive_code, 0)
            self.assertEqual(list_code, 0)
            self.assertEqual(list_all_code, 0)
            self.assertEqual(delete_code, 0)
            self.assertIn("active_session_id: session.alpha", current_stdout.getvalue())
            self.assertIn("SPICE SESSION TIMELINE", timeline_stdout.getvalue())
            self.assertIn("Plan billing decisions.", timeline_stdout.getvalue())
            self.assertIn("session.alpha", search_stdout.getvalue())
            self.assertIn("SPICE SESSION STATS", stats_stdout.getvalue())
            self.assertIn("no sessions found", list_stdout.getvalue())
            self.assertIn("session.alpha", list_all_stdout.getvalue())
            self.assertIn("SPICE SESSION DELETED", delete_stdout.getvalue())

    def test_spice_run_interactive_rejects_json_without_once(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = spice_cli_main(["run", "--json"])

        self.assertEqual(exit_code, 2)
        self.assertIn("--json requires --once", stderr.getvalue())

    def test_spice_shell_plain_uses_tui_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            with patch("spice.entry.cli.run_tui_shell") as shell:
                shell.return_value = object()
                exit_code = spice_cli_main(["shell", "--workspace", tmp_dir, "--plain"])

            self.assertEqual(setup_code, 0)
            self.assertEqual(exit_code, 0)
            shell.assert_called_once()
            self.assertTrue(shell.call_args.kwargs["plain"])

    def test_spice_run_act_rejects_decision_only(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = spice_cli_main(
                ["run", "--once", "Fix this", "--act", "--decision-only"]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("--act cannot be combined with --decision-only", stderr.getvalue())

    def test_friendly_error_for_missing_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = spice_cli_main(
                    ["decide", "Fix the failing test.", "--workspace", tmp_dir]
                )

            error = stderr.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertIn("decide failed:", error)
            self.assertIn("Next:", error)
            self.assertIn(f"spice setup --workspace {tmp_dir}", error)

    def test_friendly_error_for_missing_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = spice_cli_main(
                    ["approval", "show", "approval.missing", "--workspace", tmp_dir]
                )

            error = stderr.getvalue()
            self.assertEqual(setup_code, 0)
            self.assertEqual(exit_code, 1)
            self.assertIn("approval show failed:", error)
            self.assertIn("Next:", error)
            self.assertIn(f"spice approval list --workspace {tmp_dir}", error)

    def test_act_reports_missing_executor_command_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(io.StringIO()):
                setup_code = spice_cli_main(["setup", "--workspace", tmp_dir])
            config_path = Path(tmp_dir) / ".spice" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["executor"] = "sdep_subprocess"
            config["executor_command"] = ""
            config_path.write_text(
                json.dumps(config, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            decide_stdout = io.StringIO()
            with redirect_stdout(decide_stdout):
                decide_code = spice_cli_main(
                    [
                        "decide",
                        "Fix the failing test.",
                        "--workspace",
                        tmp_dir,
                        "--act",
                        "--json",
                    ]
                )
            artifact = json.loads(decide_stdout.getvalue())

            self.assertEqual(setup_code, 0)
            self.assertEqual(decide_code, 0)
            self.assertFalse(artifact.get("approval_id"))
            self.assertTrue(artifact.get("handoff_blocked"))
            blocked_reasons = [
                str(reason)
                for candidate in artifact["compare_payload"]["candidate_decisions"]
                for reason in candidate["execution_affordance"].get("blockers", [])
            ]
            self.assertTrue(
                any("requires executor_command" in reason for reason in blocked_reasons),
                blocked_reasons,
            )

    def test_friendly_error_for_decision_compare_missing_file(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = spice_cli_main(
                ["decision", "compare", "--input", "/tmp/spice-missing-compare.json"]
            )

        error = stderr.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("decision compare failed:", error)
        self.assertIn("Next:", error)
        self.assertIn("Check that the input path exists", error)

    def test_friendly_error_for_init_domain_conflicting_flags(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = spice_cli_main(
                ["init", "domain", "demo", "--assist", "--from-spec", "/tmp/spec.json"]
            )

        error = stderr.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("init domain failed:", error)
        self.assertIn("Next:", error)
        self.assertIn("Use either `--assist` or `--from-spec`", error)


if __name__ == "__main__":
    unittest.main()
