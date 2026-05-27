from __future__ import annotations

import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from spice.runtime import (
    EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
    ExecutorCapabilitySnapshot,
    discover_executor_capability_snapshot,
    static_executor_capability_snapshot,
    static_executor_capability_snapshots,
    unavailable_executor_capability_snapshot,
)


class RuntimeExecutorCapabilitySnapshotTests(unittest.TestCase):
    def test_snapshot_round_trip_is_json_serializable(self) -> None:
        snapshot = ExecutorCapabilitySnapshot(
            executor_id="hermes",
            provider="hermes",
            status="available",
            source="static_baseline",
            capability_ids=["general_execution", "workspace_write", "general_execution"],
            skill_ids=["runtime.intent.execute", "runtime.intent.execute"],
            permission_modes=["read_only", "workspace_write"],
            summary="Good for broad tool-use execution after approval.",
            limitations=["Static baseline, not live tool inventory."],
            metadata={"raw": {"ignored_by_compact": True}},
        )
        snapshot.validate()

        payload = snapshot.to_payload()
        restored = ExecutorCapabilitySnapshot.from_payload(json.loads(json.dumps(payload)))

        self.assertEqual(restored.schema_version, EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(restored.executor_id, "hermes")
        self.assertEqual(restored.provider, "hermes")
        self.assertEqual(restored.status, "available")
        self.assertEqual(restored.source, "static_baseline")
        self.assertEqual(restored.capability_ids, ["general_execution", "workspace_write"])
        self.assertEqual(restored.skill_ids, ["runtime.intent.execute"])
        self.assertTrue(restored.has_capability("workspace_write"))
        self.assertFalse(restored.has_capability("code_edit"))

    def test_compact_payload_excludes_raw_metadata(self) -> None:
        snapshot = ExecutorCapabilitySnapshot(
            executor_id="codex",
            provider="codex",
            status="available",
            source="static_baseline",
            capability_ids=["repo_read", "code_edit"],
            skill_ids=["runtime.intent.execute"],
            permission_modes=["read_only", "workspace_write"],
            summary="Good for repo-local code work.",
            metadata={"raw_describe_response": {"too_large": True}},
        )

        compact = snapshot.compact_payload()

        self.assertEqual(compact["executor_id"], "codex")
        self.assertEqual(compact["capability_ids"], ["repo_read", "code_edit"])
        self.assertNotIn("metadata", compact)
        self.assertNotIn("raw_describe_response", repr(compact))

    def test_snapshot_from_payload_ignores_unknown_fields_and_validates_enums(self) -> None:
        restored = ExecutorCapabilitySnapshot.from_payload(
            {
                "executor_id": "dry_run",
                "provider": "dry_run",
                "status": "available",
                "source": "static_baseline",
                "capability_ids": ["simulate_execution"],
                "newer_field": "ignored",
            }
        )

        self.assertEqual(restored.executor_id, "dry_run")
        self.assertEqual(restored.capability_ids, ["simulate_execution"])
        self.assertNotIn("newer_field", restored.to_payload())

        with self.assertRaisesRegex(ValueError, "source"):
            ExecutorCapabilitySnapshot.from_payload(
                {
                    "executor_id": "codex",
                    "status": "available",
                    "source": "live_guess",
                }
            )
        with self.assertRaisesRegex(ValueError, "status"):
            ExecutorCapabilitySnapshot.from_payload(
                {
                    "executor_id": "codex",
                    "status": "ready",
                    "source": "static_baseline",
                }
            )

    def test_unavailable_snapshot_helper(self) -> None:
        snapshot = unavailable_executor_capability_snapshot(
            "unknown_executor",
            reason="Executor is not configured.",
        )

        self.assertEqual(snapshot.executor_id, "unknown_executor")
        self.assertEqual(snapshot.status, "unavailable")
        self.assertEqual(snapshot.source, "unavailable")
        self.assertIn("not configured", snapshot.limitations[0])

    def test_static_baseline_for_dry_run_is_preview_only(self) -> None:
        snapshot = static_executor_capability_snapshot("dry_run")

        self.assertEqual(snapshot.executor_id, "dry_run")
        self.assertEqual(snapshot.status, "available")
        self.assertEqual(snapshot.source, "static_baseline")
        self.assertEqual(snapshot.capability_ids, ["simulate_execution"])
        self.assertIn("No real side effects.", snapshot.limitations)
        self.assertFalse(snapshot.has_capability("workspace_write"))

    def test_static_baseline_for_codex(self) -> None:
        snapshot = static_executor_capability_snapshot("codex")

        self.assertEqual(snapshot.executor_id, "codex")
        self.assertEqual(snapshot.provider, "codex")
        self.assertEqual(
            snapshot.capability_ids,
            [
                "repo_read",
                "code_edit",
                "test_run",
                "workspace_write",
                "terminal_command",
            ],
        )
        self.assertEqual(
            snapshot.permission_modes,
            ["read_only", "workspace_write", "danger_full_access"],
        )
        self.assertIn("Static baseline, not live tool inventory.", snapshot.limitations)

    def test_static_baseline_for_claude_code(self) -> None:
        snapshot = static_executor_capability_snapshot("claude-code")

        self.assertEqual(snapshot.executor_id, "claude_code")
        self.assertEqual(
            snapshot.capability_ids,
            ["repo_read", "code_edit", "workspace_write", "terminal_command"],
        )
        self.assertFalse(snapshot.has_capability("test_run"))

    def test_static_baseline_for_hermes_is_conservative(self) -> None:
        snapshot = static_executor_capability_snapshot("hermes")

        self.assertEqual(snapshot.executor_id, "hermes")
        self.assertEqual(
            snapshot.capability_ids,
            [
                "general_execution",
                "tool_use",
                "workspace_write",
                "browser_or_external_tools",
                "note_or_memory_work",
            ],
        )
        self.assertIn("Hermes tool and skill inventory can vary by installation.", snapshot.limitations)
        self.assertTrue(snapshot.metadata["baseline_only"])
        self.assertFalse(snapshot.metadata["live_tool_list"])

    def test_static_baseline_for_openclaw_delegates_permissions_to_openclaw_policy(self) -> None:
        snapshot = static_executor_capability_snapshot("openclaw")

        self.assertEqual(snapshot.executor_id, "openclaw")
        self.assertEqual(snapshot.provider, "openclaw")
        self.assertEqual(snapshot.status, "available")
        self.assertIn("general_execution", snapshot.capability_ids)
        self.assertIn("gateway_agent_turn", snapshot.capability_ids)
        self.assertIn("agent_routing", snapshot.capability_ids)
        self.assertIn("workspace_write", snapshot.capability_ids)
        self.assertIn("browser_or_external_tools", snapshot.capability_ids)
        self.assertIn("channel_messaging", snapshot.capability_ids)
        self.assertEqual(
            snapshot.metadata["permission_enforcement"],
            "executor_policy",
        )
        self.assertEqual(snapshot.metadata["routing_model"], "gateway_agent_turn")
        self.assertEqual(snapshot.metadata["recommended_policy"]["workspace_write"], "cautious")
        self.assertIn("openclaw exec-policy show --json", snapshot.metadata["policy_commands"])
        self.assertIn("openclaw sandbox explain --json", snapshot.metadata["policy_commands"])
        self.assertIn(
            "OpenClaw permissions are controlled by OpenClaw exec-policy, approvals, and sandbox config.",
            snapshot.limitations,
        )
        self.assertIn("not a live OpenClaw tool inventory", " ".join(snapshot.limitations))

    def test_static_baseline_for_openclaw_accepts_common_aliases(self) -> None:
        self.assertEqual(static_executor_capability_snapshot("open-claw").executor_id, "openclaw")
        self.assertEqual(static_executor_capability_snapshot("open claw").executor_id, "openclaw")
        self.assertEqual(static_executor_capability_snapshot("spice.openclaw").executor_id, "openclaw")

    def test_static_baseline_for_sdep_subprocess_is_unknown_until_describe(self) -> None:
        snapshot = static_executor_capability_snapshot("sdep")

        self.assertEqual(snapshot.executor_id, "sdep_subprocess")
        self.assertEqual(snapshot.status, "unknown")
        self.assertEqual(snapshot.source, "static_baseline")
        self.assertEqual(snapshot.capability_ids, ["general_execution"])
        self.assertIn("agent.describe", " ".join(snapshot.limitations))

    def test_static_baseline_unknown_executor_is_unavailable(self) -> None:
        snapshot = static_executor_capability_snapshot("custom_agent")

        self.assertEqual(snapshot.executor_id, "custom_agent")
        self.assertEqual(snapshot.status, "unavailable")
        self.assertEqual(snapshot.source, "unavailable")
        self.assertIn("No static capability baseline", snapshot.limitations[0])

    def test_static_baseline_listing_returns_copies(self) -> None:
        snapshots = static_executor_capability_snapshots()

        self.assertEqual(
            sorted(snapshots),
            ["claude_code", "codex", "dry_run", "hermes", "openclaw", "sdep_subprocess"],
        )
        snapshots["codex"].capability_ids.append("mutated")

        fresh = static_executor_capability_snapshot("codex")
        self.assertNotIn("mutated", fresh.capability_ids)

    def test_discover_missing_executor_returns_unavailable(self) -> None:
        snapshot = discover_executor_capability_snapshot({})

        self.assertEqual(snapshot.executor_id, "unknown")
        self.assertEqual(snapshot.status, "unavailable")
        self.assertEqual(snapshot.source, "unavailable")
        self.assertIn("not configured", snapshot.limitations[0])

    def test_discover_unknown_executor_falls_back_to_unavailable(self) -> None:
        snapshot = discover_executor_capability_snapshot({"executor": "custom_agent"})

        self.assertEqual(snapshot.executor_id, "custom_agent")
        self.assertEqual(snapshot.status, "unavailable")
        self.assertEqual(snapshot.source, "unavailable")
        self.assertIn("No static capability baseline", snapshot.limitations[0])

    def test_discover_non_sdep_executor_uses_static_baseline(self) -> None:
        snapshot = discover_executor_capability_snapshot({"executor": "codex"})

        self.assertEqual(snapshot.executor_id, "codex")
        self.assertEqual(snapshot.source, "static_baseline")
        self.assertEqual(
            snapshot.capability_ids,
            [
                "repo_read",
                "code_edit",
                "test_run",
                "workspace_write",
                "terminal_command",
            ],
        )

    def test_discover_sdep_describe_success_overrides_static_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "sdep_describe_agent.py"
            script.write_text(
                """
import json
import sys

request = json.load(sys.stdin)
response = {
    "protocol": "sdep",
    "sdep_version": "0.1",
    "message_type": "agent.describe.response",
    "message_id": "sdep-msg-test-describe-response",
    "request_id": request["request_id"],
    "timestamp": "2026-03-12T12:00:01+00:00",
    "responder": {
        "id": "agent.demo",
        "name": "Demo SDEP Agent",
        "version": "0.1",
        "vendor": "SpiceTest",
        "implementation": "demo-sdep-agent",
        "role": "executor"
    },
    "status": "success",
    "description": {
        "protocol_support": {
            "protocol": "sdep",
            "versions": ["0.1"],
            "metadata": {}
        },
        "summary": "Demo SDEP agent with live describe.",
        "capability_version": "demo.v1",
        "capabilities": [
            {
                "action_type": "demo.read",
                "target_kinds": ["workspace"],
                "mode_support": ["sync"],
                "dry_run_supported": True,
                "side_effect_class": "read_only",
                "outcome_type": "observation",
                "semantic_inputs": ["target_ref"],
                "input_expectation": "object payload",
                "parameter_expectation": "object payload",
                "metadata": {}
            },
            {
                "action_type": "demo.write",
                "target_kinds": ["workspace"],
                "mode_support": ["sync"],
                "dry_run_supported": False,
                "side_effect_class": "external_effect",
                "outcome_type": "state_delta",
                "semantic_inputs": ["objective"],
                "input_expectation": "object payload",
                "parameter_expectation": "object payload",
                "metadata": {}
            }
        ],
        "metadata": {}
    },
    "metadata": {}
}
print(json.dumps(response))
""".strip()
                + "\n",
                encoding="utf-8",
            )
            command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"

            snapshot = discover_executor_capability_snapshot(
                {
                    "executor": "sdep_subprocess",
                    "executor_command": command,
                }
            )

        self.assertEqual(snapshot.executor_id, "sdep_subprocess")
        self.assertEqual(snapshot.provider, "demo-sdep-agent")
        self.assertEqual(snapshot.status, "available")
        self.assertEqual(snapshot.source, "sdep_describe")
        self.assertEqual(snapshot.capability_ids, ["demo.read", "demo.write"])
        self.assertEqual(
            snapshot.permission_modes,
            ["read_only", "workspace_write", "danger_full_access"],
        )
        self.assertEqual(snapshot.summary, "Demo SDEP agent with live describe.")
        self.assertEqual(snapshot.metadata["capability_version"], "demo.v1")
        self.assertIn("raw_sdep_describe_response", snapshot.metadata)
        self.assertNotIn("metadata", snapshot.compact_payload())

    def test_discover_sdep_describe_failure_falls_back_to_static_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "bad_sdep_agent.py"
            script.write_text("print('not json')\n", encoding="utf-8")
            command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"

            snapshot = discover_executor_capability_snapshot(
                {
                    "executor": "sdep_subprocess",
                    "executor_command": command,
                }
            )

        self.assertEqual(snapshot.executor_id, "sdep_subprocess")
        self.assertEqual(snapshot.status, "unknown")
        self.assertEqual(snapshot.source, "static_baseline")
        self.assertEqual(snapshot.capability_ids, ["general_execution"])
        self.assertIn("SDEP describe failed", " ".join(snapshot.limitations))
        self.assertFalse(snapshot.metadata["dynamic_discovery"]["success"])


if __name__ == "__main__":
    unittest.main()
