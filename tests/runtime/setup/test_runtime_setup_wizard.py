from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spice.runtime.executor_discovery import ExecutorCLIDetection
from spice.runtime.setup_wizard import run_setup_wizard


class RuntimeSetupWizardTests(unittest.TestCase):
    def test_setup_wizard_configures_llm_executor_and_poll_perception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            answers = io.StringIO(
                "\n".join(
                    [
                        "2",  # openai
                        "",  # default model
                        "y",  # save API key
                        "y",  # candidate expansion
                        "n",  # simulation
                        "2",  # sdep subprocess
                        "",  # default permission
                        "",  # default command
                        "2",  # poll perception
                        "y",  # decision on change
                        "1",  # url poll
                        "https://ci.example/status",
                        "30",
                        "5",
                    ]
                )
                + "\n"
            )
            output = io.StringIO()
            password_prompts: list[str] = []

            def password_reader(prompt: str) -> str:
                password_prompts.append(prompt)
                return "sk-test"

            result = run_setup_wizard(
                project_root=tmp_dir,
                input_stream=answers,
                output_stream=output,
                password_reader=password_reader,
            )

            spice_dir = Path(tmp_dir) / ".spice"
            config = json.loads((spice_dir / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(result.config.llm_provider, "openai")
            self.assertEqual(config["llm_provider"], "openai")
            self.assertEqual(config["llm_model"], "gpt-4o-mini")
            self.assertEqual(config["llm_api_key_env"], "OPENAI_API_KEY")
            self.assertEqual(config["llm_candidate_expand"], "true")
            self.assertEqual(config["llm_simulation"], "false")
            self.assertEqual(config["executor"], "sdep_subprocess")
            self.assertEqual(
                config["executor_command"],
                "python -m spice.runtime.sdep_echo_executor",
            )
            self.assertEqual(config["perception_provider"], "poll")
            self.assertEqual(config["perception_trigger_mode"], "decision_on_change")
            self.assertEqual(config["perception_poll_url"], "https://ci.example/status")
            self.assertEqual(config["perception_poll_interval"], "30")
            self.assertEqual(config["perception_poll_timeout"], "5")
            self.assertEqual(password_prompts, ["OPENAI_API_KEY: "])
            self.assertEqual(result.saved_env_path, spice_dir / ".env")
            self.assertIn("OPENAI_API_KEY=sk-test", (spice_dir / ".env").read_text(encoding="utf-8"))
            self.assertIn("Setup complete.", output.getvalue())
            self.assertIn("Spice Doctor - workspace check", output.getvalue())
            self.assertIn("Review configuration", output.getvalue())
            self.assertIn("executor_transport", output.getvalue())

    def test_setup_wizard_defaults_to_safe_local_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            answers = io.StringIO("\n\n\n")
            output = io.StringIO()

            result = run_setup_wizard(
                project_root=tmp_dir,
                input_stream=answers,
                output_stream=output,
                password_reader=lambda prompt: "",
            )

            self.assertEqual(result.config.llm_provider, "deterministic")
            self.assertEqual(result.config.executor, "dry_run")
            self.assertEqual(result.config.perception_provider, "manual")
            self.assertFalse((Path(tmp_dir) / ".spice" / ".env").exists())

    def test_setup_wizard_can_go_back_to_executor_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            answers = io.StringIO(
                "\n".join(
                    [
                        "",  # deterministic
                        "2",  # sdep subprocess
                        "",  # default permission
                        "",  # default command
                        "b",  # back from perception to executor
                        "1",  # dry run
                        "1",  # manual perception
                        "",  # save review
                    ]
                )
                + "\n"
            )
            output = io.StringIO()

            result = run_setup_wizard(
                project_root=tmp_dir,
                input_stream=answers,
                output_stream=output,
                password_reader=lambda prompt: "",
            )

            self.assertEqual(result.config.executor, "dry_run")
            self.assertEqual(result.config.executor_command, "")
            self.assertIn("Back to Executor.", output.getvalue())

    def test_setup_wizard_cancel_does_not_write_config_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            answers = io.StringIO("q\n")
            output = io.StringIO()

            with self.assertRaisesRegex(ValueError, "Setup cancelled"):
                run_setup_wizard(
                    project_root=tmp_dir,
                    input_stream=answers,
                    output_stream=output,
                    password_reader=lambda prompt: "",
                )

    def test_setup_wizard_auto_fills_detected_executor_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            answers = io.StringIO(
                "\n".join(
                    [
                        "",  # deterministic
                        "3",  # codex
                        "",  # workspace write permission
                        "1",  # manual perception
                        "",  # save review
                    ]
                )
                + "\n"
            )
            output = io.StringIO()
            detection = ExecutorCLIDetection(
                executor_id="codex",
                command_name="codex",
                status="ready",
                command=sys.executable,
                executable_path=sys.executable,
                detail=f"codex found on PATH: {sys.executable}",
            )

            with patch(
                "spice.runtime.setup_wizard.detect_known_executor_clis",
                return_value={"codex": detection},
            ):
                with patch(
                    "spice.runtime.setup_wizard.detect_executor_cli",
                    return_value=detection,
                ):
                    result = run_setup_wizard(
                        project_root=tmp_dir,
                        input_stream=answers,
                        output_stream=output,
                        password_reader=lambda prompt: "",
                    )

            self.assertEqual(result.config.executor, "codex")
            self.assertEqual(result.config.executor_permission_mode, "workspace_write")
            self.assertEqual(result.config.executor_command, "")
            text = output.getvalue()
            self.assertIn("Detected executor CLIs", text)
            self.assertIn(f"Detected codex command: {sys.executable}", text)

    def test_setup_wizard_defaults_real_executor_runtime_commands(self) -> None:
        cases = [
            ("3", "codex", "codex exec --skip-git-repo-check --sandbox workspace-write -"),
            ("4", "claude_code", "claude -p --permission-mode acceptEdits"),
            ("5", "hermes", "hermes chat -Q"),
            ("6", "openclaw", "openclaw agent --json --message"),
        ]
        for choice, executor_id, expected_command in cases:
            with self.subTest(executor_id=executor_id):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    answers = io.StringIO(
                        "\n".join(
                            [
                                "",  # deterministic
                                choice,
                                "",  # workspace write permission
                                "1",  # manual perception
                                "",  # save review
                            ]
                        )
                        + "\n"
                    )
                    output = io.StringIO()
                    detection = ExecutorCLIDetection(
                        executor_id=executor_id,
                        command_name=expected_command.split()[0],
                        status="missing",
                        detail="missing for test",
                    )

                    with patch(
                        "spice.runtime.setup_wizard.detect_known_executor_clis",
                        return_value={executor_id: detection},
                    ):
                        with patch(
                            "spice.runtime.setup_wizard.detect_executor_cli",
                            return_value=detection,
                        ):
                            result = run_setup_wizard(
                                project_root=tmp_dir,
                                input_stream=answers,
                                output_stream=output,
                                password_reader=lambda prompt: "",
                            )

                    self.assertEqual(result.config.executor, executor_id)
                    self.assertEqual(result.config.executor_command, "")
                    self.assertIn(expected_command, output.getvalue())

    def test_setup_wizard_openclaw_reports_executor_policy_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            answers = io.StringIO(
                "\n".join(
                    [
                        "",  # deterministic
                        "6",  # openclaw
                        "",  # workspace write permission
                        "1",  # manual perception
                        "",  # save review
                    ]
                )
                + "\n"
            )
            output = io.StringIO()
            detection = ExecutorCLIDetection(
                executor_id="openclaw",
                command_name="openclaw",
                status="ready",
                command=sys.executable,
                executable_path=sys.executable,
                detail=f"openclaw found on PATH: {sys.executable}",
            )

            with patch(
                "spice.runtime.setup_wizard.detect_known_executor_clis",
                return_value={"openclaw": detection},
            ):
                with patch(
                    "spice.runtime.setup_wizard.detect_executor_cli",
                    return_value=detection,
                ):
                    result = run_setup_wizard(
                        project_root=tmp_dir,
                        input_stream=answers,
                        output_stream=output,
                        password_reader=lambda prompt: "",
                    )

            self.assertEqual(result.config.executor, "openclaw")
            self.assertEqual(result.config.executor_permission_mode, "workspace_write")
            self.assertEqual(result.config.executor_command, "")
            text = output.getvalue()
            self.assertIn("Detected openclaw command: " + sys.executable, text)
            self.assertIn("Permission enforcement is controlled by the selected executor CLI.", text)
            self.assertIn("OpenClaw recommended policy for workspace_write: cautious", text)
            self.assertIn("openclaw exec-policy show --json", text)
            self.assertIn("executor_permission_source executor_policy", text)

    def test_setup_wizard_warns_for_broken_executor_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            answers = io.StringIO(
                "\n".join(
                    [
                        "",  # deterministic
                        "3",  # codex
                        "",  # workspace write permission
                        "1",  # manual perception
                        "",  # save review
                    ]
                )
                + "\n"
            )
            output = io.StringIO()
            detection = ExecutorCLIDetection(
                executor_id="codex",
                command_name="codex",
                status="broken_symlink",
                broken_symlink_path="/Users/test/.local/bin/codex",
                broken_symlink_target="/missing/codex",
                detail="broken CLI symlink",
            )

            with patch(
                "spice.runtime.setup_wizard.detect_known_executor_clis",
                return_value={"codex": detection},
            ):
                with patch(
                    "spice.runtime.setup_wizard.detect_executor_cli",
                    return_value=detection,
                ):
                    result = run_setup_wizard(
                        project_root=tmp_dir,
                        input_stream=answers,
                        output_stream=output,
                        password_reader=lambda prompt: "",
                    )

            self.assertEqual(result.config.executor, "codex")
            self.assertEqual(result.config.executor_permission_mode, "workspace_write")
            self.assertEqual(result.config.executor_command, "")
            text = output.getvalue()
            self.assertIn("broken symlink", text)
            self.assertIn("Next: install the CLI or choose dry_run.", text)


if __name__ == "__main__":
    unittest.main()
