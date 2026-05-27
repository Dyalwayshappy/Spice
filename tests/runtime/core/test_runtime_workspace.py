from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spice.runtime import (
    DEFAULT_WORKSPACE_CONFIG,
    DEFAULT_WORKSPACE_PERCEPTION_CONFIG,
    configure_workspace_llm,
    load_workspace_context_compiler,
    load_workspace_env,
    load_workspace_memory_provider,
    load_or_create_session,
    LocalJsonStore,
    setup_workspace,
    update_workspace_config,
    validate_workspace_config_update,
    workspace_paths,
)


class RuntimeWorkspaceTests(unittest.TestCase):
    def test_setup_workspace_creates_default_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report = setup_workspace(project_root=tmp_dir)
            paths = workspace_paths(tmp_dir)

            self.assertEqual(report.workspace, Path(tmp_dir) / ".spice")
            for directory in paths.directories:
                self.assertTrue(directory.is_dir(), str(directory))
            self.assertTrue(paths.config.exists())
            self.assertTrue(paths.decision_profile.exists())
            self.assertTrue(paths.state.exists())
            self.assertTrue(paths.memory_dir.is_dir())
            self.assertTrue(paths.conversations_dir.is_dir())

            config = json.loads(paths.config.read_text(encoding="utf-8"))
            for key, expected in DEFAULT_WORKSPACE_CONFIG.items():
                self.assertEqual(config[key], expected)
            self.assertEqual(config["workspace_perception"], DEFAULT_WORKSPACE_PERCEPTION_CONFIG)
            self.assertEqual(config["memory_provider"], "file")
            self.assertEqual(config["memory_path"], ".spice/memory")
            self.assertEqual(config["context_compiler"], "deterministic")

            state = json.loads(paths.state.read_text(encoding="utf-8"))
            self.assertEqual(state["schema_version"], "spice.workspace.state.v1")
            general = state["world_state"]["domain_state"]["general_decision"]
            self.assertEqual(general["schema_version"], "0.1")
            self.assertEqual(general["signals"], [])

    def test_setup_workspace_does_not_overwrite_existing_files_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = workspace_paths(tmp_dir)
            setup_workspace(project_root=tmp_dir)
            paths.config.write_text('{"custom": true}\n', encoding="utf-8")
            paths.decision_profile.write_text("# custom decision\n", encoding="utf-8")
            paths.state.write_text('{"custom_state": true}\n', encoding="utf-8")

            report = setup_workspace(project_root=tmp_dir)

            self.assertIn(paths.config, report.existing)
            self.assertIn(paths.decision_profile, report.existing)
            self.assertIn(paths.state, report.existing)
            self.assertEqual(json.loads(paths.config.read_text(encoding="utf-8")), {"custom": True})
            self.assertEqual(paths.decision_profile.read_text(encoding="utf-8"), "# custom decision\n")
            self.assertEqual(
                json.loads(paths.state.read_text(encoding="utf-8")),
                {"custom_state": True},
            )

    def test_setup_workspace_force_overwrites_default_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = workspace_paths(tmp_dir)
            setup_workspace(project_root=tmp_dir)
            paths.config.write_text('{"custom": true}\n', encoding="utf-8")

            report = setup_workspace(project_root=tmp_dir, force=True)

            self.assertIn(paths.config, report.overwritten)
            config = json.loads(paths.config.read_text(encoding="utf-8"))
            self.assertEqual(config["executor"], "dry_run")

    def test_update_workspace_config_validates_key_and_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)

            config = update_workspace_config(tmp_dir, "executor", "sdep_subprocess")

            self.assertEqual(config.executor, "sdep_subprocess")
            config = update_workspace_config(tmp_dir, "executor", "codex")
            self.assertEqual(config.executor, "codex")
            config = update_workspace_config(tmp_dir, "executor", "claude_code")
            self.assertEqual(config.executor, "claude_code")
            config = update_workspace_config(tmp_dir, "executor", "hermes")
            self.assertEqual(config.executor, "hermes")
            config = update_workspace_config(tmp_dir, "executor", "openclaw")
            self.assertEqual(config.executor, "openclaw")
            config = update_workspace_config(tmp_dir, "llm_provider", "openai")
            self.assertEqual(config.llm_provider, "openai")
            config = update_workspace_config(tmp_dir, "llm_provider", "anthropic")
            self.assertEqual(config.llm_provider, "anthropic")
            config = update_workspace_config(tmp_dir, "llm_provider", "deepseek")
            self.assertEqual(config.llm_provider, "deepseek")
            config = update_workspace_config(tmp_dir, "llm_provider", "mimo")
            self.assertEqual(config.llm_provider, "mimo")
            config = update_workspace_config(tmp_dir, "llm_model", "gpt-4o-mini")
            self.assertEqual(config.llm_model, "gpt-4o-mini")
            config = update_workspace_config(tmp_dir, "llm_api_key_env", "OPENAI_API_KEY")
            self.assertEqual(config.llm_api_key_env, "OPENAI_API_KEY")
            config = update_workspace_config(tmp_dir, "llm_candidate_expand", "yes")
            self.assertEqual(config.llm_candidate_expand, "true")
            config = update_workspace_config(tmp_dir, "llm_candidate_expand", "0")
            self.assertEqual(config.llm_candidate_expand, "false")
            config = update_workspace_config(tmp_dir, "llm_simulation", "yes")
            self.assertEqual(config.llm_simulation, "true")
            config = update_workspace_config(tmp_dir, "llm_simulation", "0")
            self.assertEqual(config.llm_simulation, "false")
            config = update_workspace_config(tmp_dir, "perception_provider", "poll")
            self.assertEqual(config.perception_provider, "poll")
            config = update_workspace_config(tmp_dir, "perception_provider", "open_chronicle")
            self.assertEqual(config.perception_provider, "open_chronicle")
            config = update_workspace_config(tmp_dir, "perception_poll_url", "file:///tmp/status.txt")
            self.assertEqual(config.perception_poll_url, "file:///tmp/status.txt")
            config = update_workspace_config(tmp_dir, "perception_poll_command", "python --version")
            self.assertEqual(config.perception_poll_command, "python --version")
            config = update_workspace_config(tmp_dir, "perception_poll_interval", "15")
            self.assertEqual(config.perception_poll_interval, "15")
            config = update_workspace_config(tmp_dir, "perception_poll_timeout", "5")
            self.assertEqual(config.perception_poll_timeout, "5")
            config = update_workspace_config(tmp_dir, "perception_allow_command_poll", "yes")
            self.assertEqual(config.perception_allow_command_poll, "true")
            config = update_workspace_config(tmp_dir, "perception_allow_command_poll", "0")
            self.assertEqual(config.perception_allow_command_poll, "false")
            config = update_workspace_config(tmp_dir, "openchronicle_mcp_url", "http://127.0.0.1:8742/mcp")
            self.assertEqual(config.openchronicle_mcp_url, "http://127.0.0.1:8742/mcp")
            config = update_workspace_config(tmp_dir, "openchronicle_since_minutes", "20")
            self.assertEqual(config.openchronicle_since_minutes, "20")
            config = update_workspace_config(tmp_dir, "openchronicle_context_limit", "8")
            self.assertEqual(config.openchronicle_context_limit, "8")
            config = update_workspace_config(tmp_dir, "perception_trigger_mode", "decision_on_change")
            self.assertEqual(config.perception_trigger_mode, "decision_on_change")
            config = update_workspace_config(tmp_dir, "perception_trigger_mode", "state_only")
            self.assertEqual(config.perception_trigger_mode, "state_only")
            config = update_workspace_config(tmp_dir, "memory_provider", "file")
            self.assertEqual(config.memory_provider, "file")
            config = update_workspace_config(tmp_dir, "memory_path", ".spice/custom-memory")
            self.assertEqual(config.memory_path, ".spice/custom-memory")
            config = update_workspace_config(tmp_dir, "context_compiler", "deterministic")
            self.assertEqual(config.context_compiler, "deterministic")
            config = update_workspace_config(tmp_dir, "workspace_perception.depth", "deep")
            self.assertEqual(config.workspace_perception["depth"], "deep")
            config = update_workspace_config(tmp_dir, "workspace_perception.depth", "native")
            self.assertEqual(config.workspace_perception["depth"], "native")
            config = update_workspace_config(tmp_dir, "workspace_perception.max_rounds", "12")
            self.assertEqual(config.workspace_perception["max_rounds"], "12")
            config = update_workspace_config(tmp_dir, "workspace_perception.max_tool_calls", "90")
            self.assertEqual(config.workspace_perception["max_tool_calls"], "90")
            config = update_workspace_config(tmp_dir, "workspace_perception.max_files_read", "70")
            self.assertEqual(config.workspace_perception["max_files_read"], "70")
            config = update_workspace_config(tmp_dir, "workspace_perception.total_char_budget", "600000")
            self.assertEqual(config.workspace_perception["total_char_budget"], "600000")
            with self.assertRaisesRegex(ValueError, "Unknown config key"):
                validate_workspace_config_update(tmp_dir, "executor.command", "x")
            with self.assertRaisesRegex(ValueError, "Unknown workspace_perception config key"):
                validate_workspace_config_update(tmp_dir, "workspace_perception.terminal", "true")
            with self.assertRaisesRegex(ValueError, "Invalid workspace_perception.depth"):
                validate_workspace_config_update(tmp_dir, "workspace_perception.depth", "light")
            with self.assertRaisesRegex(ValueError, "Invalid workspace_perception.max_rounds"):
                validate_workspace_config_update(tmp_dir, "workspace_perception.max_rounds", "0")
            with self.assertRaisesRegex(ValueError, "Invalid workspace_perception.max_tool_calls"):
                validate_workspace_config_update(tmp_dir, "workspace_perception.max_tool_calls", "abc")
            with self.assertRaisesRegex(ValueError, "Invalid executor"):
                validate_workspace_config_update(tmp_dir, "executor", "unknown")
            with self.assertRaisesRegex(ValueError, "Invalid llm_provider"):
                validate_workspace_config_update(tmp_dir, "llm_provider", "unknown")
            with self.assertRaisesRegex(ValueError, "Invalid llm_candidate_expand"):
                validate_workspace_config_update(tmp_dir, "llm_candidate_expand", "maybe")
            with self.assertRaisesRegex(ValueError, "Invalid llm_simulation"):
                validate_workspace_config_update(tmp_dir, "llm_simulation", "maybe")
            with self.assertRaisesRegex(ValueError, "Invalid perception_provider"):
                validate_workspace_config_update(tmp_dir, "perception_provider", "unknown")
            with self.assertRaisesRegex(ValueError, "Invalid perception_allow_command_poll"):
                validate_workspace_config_update(tmp_dir, "perception_allow_command_poll", "maybe")
            with self.assertRaisesRegex(ValueError, "Invalid perception_poll_interval"):
                validate_workspace_config_update(tmp_dir, "perception_poll_interval", "0")
            with self.assertRaisesRegex(ValueError, "Invalid perception_poll_timeout"):
                validate_workspace_config_update(tmp_dir, "perception_poll_timeout", "abc")
            with self.assertRaisesRegex(ValueError, "Invalid openchronicle_since_minutes"):
                validate_workspace_config_update(tmp_dir, "openchronicle_since_minutes", "0")
            with self.assertRaisesRegex(ValueError, "Invalid openchronicle_context_limit"):
                validate_workspace_config_update(tmp_dir, "openchronicle_context_limit", "abc")
            with self.assertRaisesRegex(ValueError, "Invalid perception_trigger_mode"):
                validate_workspace_config_update(tmp_dir, "perception_trigger_mode", "auto_execute")
            with self.assertRaisesRegex(ValueError, "Invalid memory_provider"):
                validate_workspace_config_update(tmp_dir, "memory_provider", "unknown")
            with self.assertRaisesRegex(ValueError, "Invalid context_compiler"):
                validate_workspace_config_update(tmp_dir, "context_compiler", "unknown")

    def test_workspace_memory_defaults_resolve_to_file_provider_and_compiler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)

            provider = load_workspace_memory_provider(tmp_dir)
            compiler = load_workspace_context_compiler(tmp_dir, memory_provider=provider)

            self.assertEqual(provider.base_dir, Path(tmp_dir) / ".spice" / "memory")
            self.assertEqual(compiler.memory_provider, provider)

    def test_store_saves_and_loads_conversation_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            store = LocalJsonStore.from_project_root(tmp_dir)
            payload = {
                "schema_version": "spice.conversation_turn.v1",
                "turn_id": "turn.test",
                "user_input": "What should we do next?",
                "route": "new_decision",
                "source_decision_id": "decision.test",
                "source_candidate_id": "candidate.test",
                "response_id": "response.test",
                "created_at": "2026-04-29T06:00:00+00:00",
            }

            path = store.save_conversation_turn("turn.test", payload)

            self.assertEqual(path.parent, workspace_paths(tmp_dir).conversations_dir)
            self.assertEqual(store.load_conversation_turn("turn.test"), payload)
            self.assertEqual(store.list_record_ids("conversation_turns"), ["turn.test"])

    def test_configure_workspace_llm_sets_provider_model_and_feature_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)

            config = configure_workspace_llm(
                tmp_dir,
                provider="openai",
                model="gpt-4o-mini",
                candidate_expand=True,
                simulation=False,
            )

            self.assertEqual(config.llm_provider, "openai")
            self.assertEqual(config.llm_model, "gpt-4o-mini")
            self.assertEqual(config.llm_api_key_env, "OPENAI_API_KEY")
            self.assertEqual(config.llm_candidate_expand, "true")
            self.assertEqual(config.llm_simulation, "false")
            with self.assertRaisesRegex(ValueError, "llm_model is required"):
                configure_workspace_llm(
                    tmp_dir,
                    provider="openai",
                    model="",
                )

    def test_update_workspace_config_active_session_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            store = LocalJsonStore.from_project_root(tmp_dir)
            session = load_or_create_session(store, session_id="session.alpha")
            store.save_session(session.session_id, session.to_payload())

            config = update_workspace_config(tmp_dir, "active_session_id", "session.alpha")

            self.assertEqual(config.active_session_id, "session.alpha")
            with self.assertRaisesRegex(FileNotFoundError, "Session does not exist"):
                update_workspace_config(tmp_dir, "active_session_id", "session.missing")

    def test_load_workspace_env_loads_saved_api_key_without_overriding_shell_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            env_path = workspace_paths(tmp_dir).spice_dir / ".env"
            env_path.write_text("MIMO_API_KEY=from-file\nOPENAI_API_KEY=from-file\n", encoding="utf-8")

            with patch.dict(os.environ, {"OPENAI_API_KEY": "from-shell"}, clear=False):
                os.environ.pop("MIMO_API_KEY", None)
                loaded = load_workspace_env(tmp_dir)

                self.assertEqual(os.environ["MIMO_API_KEY"], "from-file")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "from-shell")
                self.assertEqual(loaded, {"MIMO_API_KEY": "from-file"})


if __name__ == "__main__":
    unittest.main()
