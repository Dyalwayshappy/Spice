from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone

from spice.runtime import (
    ClaudeCodeExecutorProvider,
    CodexExecutorProvider,
    DryRunExecutorProvider,
    HermesExecutorProvider,
    LocalJsonStoreProvider,
    ManualInputProvider,
    OpenClawExecutorProvider,
    OpenChroniclePerceptionProvider,
    PollPerceptionProvider,
    default_runtime_provider_descriptors,
    execute_openclaw_approval,
    run_once,
    setup_workspace,
)
import spice.runtime as runtime_exports


NOW = datetime(2026, 4, 29, 6, 0, tzinfo=timezone.utc)


class RuntimeProviderTests(unittest.TestCase):
    def test_manual_input_provider_outputs_generic_observations(self) -> None:
        provider = ManualInputProvider()
        observations = provider.collect_observations(
            "Fix the failing test.",
            config={
                "executor": "dry_run",
                "permission_mode": "confirm_before_execution",
            },
            now=NOW,
        )
        payloads = [observation.to_payload() for observation in observations]

        self.assertEqual(provider.descriptor().provider_id, "manual")
        self.assertEqual(payloads[0]["kind"], "intent")
        self.assertEqual(payloads[0]["source"]["provider"], "manual")
        self.assertEqual(payloads[0]["attributes"]["original_text"], "Fix the failing test.")
        self.assertEqual(payloads[0]["evidence"][0]["kind"], "user_text")
        kinds = [payload["kind"] for payload in payloads]
        self.assertIn("work_item", kinds)
        self.assertIn("capability", kinds)
        self.assertIn("constraint", kinds)
        json.dumps(payloads)

    def test_manual_input_provider_rejects_empty_intent(self) -> None:
        with self.assertRaises(ValueError):
            ManualInputProvider().collect_observations(
                " ",
                config={},
                now=NOW,
            )

    def test_poll_perception_provider_describes_pull_observations(self) -> None:
        provider = PollPerceptionProvider(url="file:///tmp/example")

        self.assertEqual(provider.provider_id, "poll")

    def test_open_chronicle_perception_provider_describes_pull_observations(self) -> None:
        provider = OpenChroniclePerceptionProvider(mcp_url="http://127.0.0.1:8742/mcp")

        self.assertEqual(provider.provider_id, "open_chronicle")

    def test_local_json_store_provider_returns_workspace_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            provider = LocalJsonStoreProvider()
            store = provider.store(tmp_dir)

            self.assertEqual(provider.descriptor().provider_type, "store")
            self.assertIn("world_state", store.load_state())

    def test_dry_run_executor_provider_describes_read_only_boundary(self) -> None:
        provider = DryRunExecutorProvider()
        descriptor = provider.descriptor().to_payload()

        self.assertEqual(descriptor["provider_id"], "dry_run")
        self.assertEqual(descriptor["provider_type"], "executor")
        self.assertFalse(descriptor["metadata"]["real_executor_called"])
        self.assertFalse(descriptor["metadata"]["sdep_request_sent"])
        json.dumps(descriptor)

    def test_codex_executor_provider_describes_sdep_bridge(self) -> None:
        provider = CodexExecutorProvider()
        descriptor = provider.descriptor().to_payload()

        self.assertEqual(descriptor["provider_id"], "codex")
        self.assertEqual(descriptor["provider_type"], "executor")
        self.assertEqual(descriptor["metadata"]["transport"], "local_subprocess")
        self.assertTrue(descriptor["metadata"]["real_executor_called"])
        json.dumps(descriptor)

    def test_claude_code_executor_provider_describes_sdep_bridge(self) -> None:
        provider = ClaudeCodeExecutorProvider()
        descriptor = provider.descriptor().to_payload()

        self.assertEqual(descriptor["provider_id"], "claude_code")
        self.assertEqual(descriptor["provider_type"], "executor")
        self.assertEqual(descriptor["metadata"]["transport"], "local_subprocess")
        self.assertTrue(descriptor["metadata"]["real_executor_called"])
        json.dumps(descriptor)

    def test_hermes_executor_provider_describes_sdep_bridge(self) -> None:
        provider = HermesExecutorProvider()
        descriptor = provider.descriptor().to_payload()

        self.assertEqual(descriptor["provider_id"], "hermes")
        self.assertEqual(descriptor["provider_type"], "executor")
        self.assertEqual(descriptor["metadata"]["transport"], "local_subprocess")
        self.assertTrue(descriptor["metadata"]["real_executor_called"])
        json.dumps(descriptor)

    def test_openclaw_executor_provider_describes_policy_bridge(self) -> None:
        provider = OpenClawExecutorProvider()
        descriptor = provider.descriptor().to_payload()

        self.assertEqual(descriptor["provider_id"], "openclaw")
        self.assertEqual(descriptor["provider_type"], "executor")
        self.assertEqual(descriptor["metadata"]["transport"], "local_subprocess")
        self.assertEqual(descriptor["metadata"]["executor"], "openclaw")
        self.assertTrue(descriptor["metadata"]["real_executor_called"])
        self.assertEqual(descriptor["metadata"]["permission_enforcement"], "executor_policy")
        self.assertIn("openclaw exec-policy show --json", descriptor["metadata"]["policy_commands"])
        json.dumps(descriptor)

    def test_openclaw_runtime_exports_are_public(self) -> None:
        self.assertIs(runtime_exports.execute_openclaw_approval, execute_openclaw_approval)
        self.assertIs(runtime_exports.OpenClawExecutorProvider, OpenClawExecutorProvider)
        self.assertIn("execute_openclaw_approval", runtime_exports.__all__)
        self.assertIn("OpenClawExecutorProvider", runtime_exports.__all__)

    def test_default_runtime_provider_descriptors_are_stable(self) -> None:
        descriptors = default_runtime_provider_descriptors()

        self.assertEqual(
            set(descriptors),
            {
                "perception",
                "open_chronicle_perception",
                "poll_perception",
                "store",
                "executor",
                "sdep_subprocess_executor",
                "codex_executor",
                "claude_code_executor",
                "hermes_executor",
                "openclaw_executor",
            },
        )
        self.assertEqual(descriptors["perception"]["provider_id"], "manual")
        self.assertEqual(descriptors["open_chronicle_perception"]["provider_id"], "open_chronicle")
        self.assertEqual(descriptors["open_chronicle_perception"]["provider_type"], "perception")
        self.assertEqual(descriptors["poll_perception"]["provider_id"], "poll")
        self.assertEqual(descriptors["poll_perception"]["provider_type"], "perception")
        self.assertTrue(descriptors["poll_perception"]["metadata"]["command_poll_requires_opt_in"])
        self.assertEqual(descriptors["store"]["provider_id"], "local_json")
        self.assertEqual(descriptors["executor"]["provider_id"], "dry_run")
        self.assertEqual(descriptors["sdep_subprocess_executor"]["provider_id"], "sdep_subprocess")
        self.assertEqual(descriptors["codex_executor"]["provider_id"], "codex")
        self.assertEqual(descriptors["claude_code_executor"]["provider_id"], "claude_code")
        self.assertEqual(descriptors["hermes_executor"]["provider_id"], "hermes")
        self.assertEqual(descriptors["openclaw_executor"]["provider_id"], "openclaw")
        self.assertEqual(
            descriptors["openclaw_executor"]["metadata"]["permission_enforcement"],
            "executor_policy",
        )
        json.dumps(descriptors)

    def test_run_once_records_runtime_provider_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)

            result = run_once(
                "Review the current project.",
                project_root=tmp_dir,
                now=NOW,
            )
            providers = result.artifact["providers"]

            self.assertEqual(providers["perception"]["provider_id"], "manual")
            self.assertEqual(providers["store"]["provider_id"], "local_json")
            self.assertEqual(providers["executor"]["provider_id"], "dry_run")
            self.assertFalse(providers["executor"]["metadata"]["real_executor_called"])


if __name__ == "__main__":
    unittest.main()
