from __future__ import annotations

import json
import sys
import unittest

from spice.runtime.executor_runtime import (
    executor_runtime_specs,
    resolve_executor_runtime,
)


class ExecutorRuntimeResolverTests(unittest.TestCase):
    def test_dry_run_resolves_without_command(self) -> None:
        runtime = resolve_executor_runtime("dry_run")

        self.assertEqual(runtime.status, "ready")
        self.assertEqual(runtime.executor_id, "dry_run")
        self.assertEqual(runtime.transport, "local_dry_run")
        self.assertEqual(runtime.command, "")
        self.assertFalse(runtime.command_required)
        self.assertFalse(runtime.real_executor)
        self.assertFalse(runtime.sends_sdep_request)
        self.assertTrue(runtime.command_found)

    def test_sdep_subprocess_requires_configured_command(self) -> None:
        runtime = resolve_executor_runtime("sdep_subprocess")

        self.assertEqual(runtime.status, "failed")
        self.assertIn("requires executor_command", runtime.detail)
        self.assertTrue(runtime.command_required)
        self.assertFalse(runtime.real_executor)
        self.assertTrue(runtime.sends_sdep_request)

    def test_sdep_subprocess_accepts_executable_command(self) -> None:
        runtime = resolve_executor_runtime(
            "sdep_subprocess",
            executor_command=f"{sys.executable} -m spice.runtime.sdep_echo_executor",
        )

        self.assertEqual(runtime.status, "ready")
        self.assertEqual(runtime.command_argv[0], sys.executable)
        self.assertEqual(runtime.command_source, "config")
        self.assertEqual(runtime.command_path, sys.executable)
        self.assertFalse(runtime.real_executor)
        self.assertTrue(runtime.sends_sdep_request)

    def test_codex_uses_default_command_when_config_is_empty(self) -> None:
        runtime = resolve_executor_runtime("codex")

        self.assertEqual(runtime.executor_id, "codex")
        self.assertEqual(runtime.transport, "sdep_subprocess_wrapper")
        self.assertEqual(
            runtime.command,
            "codex exec --skip-git-repo-check --sandbox workspace-write -",
        )
        self.assertEqual(runtime.command_argv[:2], ("codex", "exec"))
        self.assertEqual(runtime.command_source, "permission:workspace_write")
        self.assertTrue(runtime.command_required)
        self.assertTrue(runtime.real_executor)
        self.assertTrue(runtime.sends_sdep_request)
        if runtime.status == "failed":
            self.assertIn("command not found", runtime.detail)

    def test_real_executor_defaults_are_non_interactive(self) -> None:
        self.assertEqual(
            resolve_executor_runtime("codex").command,
            "codex exec --skip-git-repo-check --sandbox workspace-write -",
        )
        self.assertEqual(
            resolve_executor_runtime("claude_code").command,
            "claude -p --permission-mode acceptEdits",
        )
        self.assertEqual(resolve_executor_runtime("hermes").command, "hermes chat -Q")
        self.assertEqual(
            resolve_executor_runtime("openclaw").command,
            "openclaw agent --json --message",
        )

    def test_codex_permission_modes_resolve_to_sandbox_flags(self) -> None:
        read_only = resolve_executor_runtime("codex", executor_permission_mode="read_only")
        danger = resolve_executor_runtime("codex", executor_permission_mode="danger_full_access")

        self.assertIn("--sandbox read-only", read_only.command)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", danger.command)
        self.assertEqual(read_only.permission_enforcement, "command_flag")

    def test_claude_code_permission_modes_resolve_to_permission_mode_flags(self) -> None:
        read_only = resolve_executor_runtime("claude_code", executor_permission_mode="read_only")
        workspace = resolve_executor_runtime("claude_code", executor_permission_mode="workspace_write")
        danger = resolve_executor_runtime("claude_code", executor_permission_mode="danger_full_access")

        self.assertEqual(read_only.command, "claude -p --permission-mode plan")
        self.assertEqual(workspace.command, "claude -p --permission-mode acceptEdits")
        self.assertEqual(danger.command, "claude -p --permission-mode bypassPermissions")
        self.assertEqual(read_only.permission_enforcement, "command_flag")

    def test_hermes_permission_modes_resolve_to_yolo_only_for_danger(self) -> None:
        read_only = resolve_executor_runtime("hermes", executor_permission_mode="read_only")
        workspace = resolve_executor_runtime("hermes", executor_permission_mode="workspace_write")
        danger = resolve_executor_runtime("hermes", executor_permission_mode="danger_full_access")

        self.assertEqual(read_only.command, "hermes chat -Q")
        self.assertEqual(workspace.command, "hermes chat -Q")
        self.assertEqual(danger.command, "hermes chat --yolo -Q")
        self.assertEqual(read_only.permission_enforcement, "command_flag")

    def test_openclaw_permission_modes_defer_to_executor_policy(self) -> None:
        read_only = resolve_executor_runtime("openclaw", executor_permission_mode="read_only")
        workspace = resolve_executor_runtime("openclaw", executor_permission_mode="workspace_write")
        danger = resolve_executor_runtime("openclaw", executor_permission_mode="danger_full_access")

        self.assertEqual(read_only.command, "openclaw agent --json --message")
        self.assertEqual(workspace.command, "openclaw agent --json --message")
        self.assertEqual(danger.command, "openclaw agent --json --message")
        self.assertEqual(read_only.permission_enforcement, "executor_policy")
        self.assertEqual(workspace.permission_enforcement, "executor_policy")
        self.assertEqual(danger.permission_enforcement, "executor_policy")
        self.assertEqual(read_only.permission_mode, "read_only")
        self.assertEqual(workspace.permission_mode, "workspace_write")
        self.assertEqual(danger.permission_mode, "danger_full_access")
        self.assertEqual(
            read_only.metadata["recommended_policy"]["workspace_write"],
            "cautious",
        )

    def test_codex_accepts_configured_command(self) -> None:
        runtime = resolve_executor_runtime("codex", executor_command=sys.executable)

        self.assertEqual(runtime.status, "ready")
        self.assertEqual(runtime.command, sys.executable)
        self.assertEqual(runtime.command_source, "config")
        self.assertEqual(runtime.command_path, sys.executable)
        self.assertTrue(runtime.real_executor)

    def test_codex_legacy_generated_command_does_not_block_permission_resolution(self) -> None:
        runtime = resolve_executor_runtime(
            "codex",
            executor_command="codex exec --skip-git-repo-check --sandbox read-only -",
            executor_permission_mode="workspace_write",
        )

        self.assertEqual(
            runtime.command,
            "codex exec --skip-git-repo-check --sandbox workspace-write -",
        )
        self.assertEqual(runtime.command_source, "legacy_default:migrated")

    def test_claude_code_legacy_generated_command_does_not_block_permission_resolution(self) -> None:
        runtime = resolve_executor_runtime(
            "claude_code",
            executor_command="claude -p",
            executor_permission_mode="workspace_write",
        )

        self.assertEqual(runtime.command, "claude -p --permission-mode acceptEdits")
        self.assertEqual(runtime.command_source, "legacy_default:migrated")

    def test_hermes_legacy_generated_command_does_not_block_permission_resolution(self) -> None:
        runtime = resolve_executor_runtime(
            "hermes",
            executor_command="hermes -z",
            executor_permission_mode="danger_full_access",
        )

        self.assertEqual(runtime.command, "hermes chat --yolo -Q")
        self.assertEqual(runtime.command_source, "legacy_default:migrated")

    def test_claude_code_accepts_configured_command(self) -> None:
        runtime = resolve_executor_runtime("claude_code", executor_command=sys.executable)

        self.assertEqual(runtime.status, "ready")
        self.assertEqual(runtime.command, sys.executable)
        self.assertEqual(runtime.command_path, sys.executable)
        self.assertTrue(runtime.real_executor)

    def test_hermes_accepts_configured_command(self) -> None:
        runtime = resolve_executor_runtime("hermes", executor_command=sys.executable)

        self.assertEqual(runtime.status, "ready")
        self.assertEqual(runtime.command, sys.executable)
        self.assertEqual(runtime.command_path, sys.executable)
        self.assertTrue(runtime.real_executor)

    def test_openclaw_accepts_configured_command(self) -> None:
        runtime = resolve_executor_runtime("openclaw", executor_command=sys.executable)

        self.assertEqual(runtime.status, "ready")
        self.assertEqual(runtime.command, sys.executable)
        self.assertEqual(runtime.command_path, sys.executable)
        self.assertTrue(runtime.real_executor)
        self.assertEqual(runtime.permission_enforcement, "executor_policy")

    def test_command_is_parsed_without_shell(self) -> None:
        runtime = resolve_executor_runtime(
            "sdep_subprocess",
            executor_command=f"{sys.executable} -m spice.runtime.sdep_echo_executor",
        )

        self.assertEqual(runtime.command_argv[:3], (sys.executable, "-m", "spice.runtime.sdep_echo_executor"))

    def test_unsupported_executor_is_structured(self) -> None:
        runtime = resolve_executor_runtime("unknown_executor")

        self.assertEqual(runtime.status, "unsupported")
        self.assertEqual(runtime.transport, "unsupported")
        self.assertIn("Supported values", runtime.detail)
        self.assertIn("dry_run", runtime.metadata["supported_executors"])

    def test_payload_is_json_serializable(self) -> None:
        payload = resolve_executor_runtime("codex", executor_command=sys.executable).to_payload()

        dumped = json.dumps(payload, sort_keys=True)
        self.assertIn("codex", dumped)

    def test_specs_are_available_without_mutating_resolver_state(self) -> None:
        specs = executor_runtime_specs()

        self.assertIn("dry_run", specs)
        self.assertIn("openclaw", specs)
        specs.pop("dry_run")
        self.assertIn("dry_run", executor_runtime_specs())


if __name__ == "__main__":
    unittest.main()
