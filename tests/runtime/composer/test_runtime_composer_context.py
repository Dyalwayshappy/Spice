from __future__ import annotations

import tempfile
import unittest

from spice.runtime import run_once, setup_workspace
from spice.runtime.composer_context import build_composer_context_payload, compact_composer_context
from spice.runtime.composer_prompt import slim_recent_context


class RuntimeComposerContextTests(unittest.TestCase):
    def test_compact_context_keeps_decision_state_not_full_history(self) -> None:
        context = compact_composer_context(
            {
                "current_intent": {"text": "What should we do next?", "source": "manual"},
                "active_decision_frame": {
                    "decision_id": "decision.active",
                    "run_id": "run.active",
                    "selected_candidate_id": "candidate.a",
                    "selected": {"label": "A", "candidate_id": "candidate.a", "title": "State"},
                    "candidates": [{"label": "A", "candidate_id": "candidate.a", "title": "State"}],
                },
                "recent_conversation_turns": [
                    {
                        "turn_id": "turn.1",
                        "route": "follow_up",
                        "user_input": "Turn this into a one-day plan.",
                    }
                ],
                "recent_decisions": [{"decision_id": "decision.previous", "recommendation": "Previous pick"}],
                "recent_approvals": [{"approval_id": "approval.1", "status": "pending"}],
                "recent_outcomes": [{"outcome_id": "outcome.1", "status": "success"}],
                "session_summary": {"summary_text": "The user cares about short iteration cycles."},
                "retrieved_memory": [{"id": "memory.1", "namespace": "general.decision", "summary": "Prior choice"}],
                "executor_affordance": {"executor": "hermes", "status": "available"},
                "executor_capabilities": {
                    "executor_id": "hermes",
                    "source": "static_baseline",
                    "capability_ids": ["general_execution", "tool_use", "workspace_write"],
                    "summary": "Good for broad tool-use execution after approval.",
                    "limitations": ["Static baseline, not live tool inventory."],
                },
                "workspace_context": {"memory_provider": "file", "executor": "hermes"},
                "url_context": {
                    "source": "url_perception",
                    "perception_id": "url.001",
                    "summary": "A linked PR proposes URL perception.",
                    "urls": ["https://example.com/pr"],
                    "documents": [{"url": "https://example.com/pr", "title": "URL PR"}],
                    "facts": [{"text": "The PR adds URL context.", "source_url": "https://example.com/pr"}],
                },
            }
        )

        self.assertEqual(context["active_decision_frame"]["decision_id"], "decision.active")
        self.assertEqual(context["recent_conversation_turns"][0]["route"], "follow_up")
        self.assertEqual(context["recent_decisions"][0]["decision_id"], "decision.previous")
        self.assertEqual(context["recent_approvals"][0]["approval_id"], "approval.1")
        self.assertEqual(context["recent_executions"][0]["outcome_id"], "outcome.1")
        self.assertIn("short iteration", context["memory_summary"]["summary_text"])
        self.assertEqual(context["executor_affordance"]["executor"], "hermes")
        self.assertEqual(context["executor_capabilities"]["executor_id"], "hermes")
        self.assertIn("tool_use", context["executor_capabilities"]["capability_ids"])
        self.assertEqual(context["workspace_context"]["memory_provider"], "file")
        self.assertEqual(context["url_context"]["perception_id"], "url.001")
        self.assertEqual(context["url_context"]["documents"][0]["title"], "URL PR")
        self.assertTrue(context["evidence_context"]["url"]["present"])
        self.assertEqual(context["evidence_context"]["url"]["perception_id"], "url.001")

    def test_compact_context_keeps_workspace_perception_facts(self) -> None:
        context = compact_composer_context(
            {
                "workspace_context": {
                    "schema_version": "spice.workspace_context.v1",
                    "source": "workspace_perception",
                    "perception_id": "workspace.001",
                    "workspace_root": "/repo",
                    "trigger": "user_follow_up",
                    "queries": [{"query": "state context", "query_type": "semantic", "path": "."}],
                    "files_read": [
                        {
                            "path": "spice/runtime/run_once.py",
                            "chars_read": 1200,
                            "line_start": 1,
                            "line_end": 60,
                            "truncated": False,
                        }
                    ],
                    "files_skipped": [{"path": ".spice/state/state.json", "reason": "deny_dir"}],
                    "facts": [
                        {
                            "text": "run_once writes a conversation turn after the decision.",
                            "source_path": "spice/runtime/run_once.py",
                            "line_start": 333,
                            "line_end": 360,
                        }
                    ],
                    "summary": "Runtime writes conversation turns.",
                    "limits": {
                        "max_files": 20,
                        "max_chars_per_file": 12000,
                        "total_char_budget": 50000,
                    },
                    "raw_file_contents": "drop this",
                }
            }
        )

        workspace = context["workspace_context"]
        self.assertEqual(workspace["source"], "workspace_perception")
        self.assertEqual(workspace["perception_id"], "workspace.001")
        self.assertEqual(workspace["facts"][0]["source_path"], "spice/runtime/run_once.py")
        self.assertEqual(workspace["files_read"][0]["path"], "spice/runtime/run_once.py")
        self.assertEqual(workspace["files_skipped"][0]["reason"], "deny_dir")
        self.assertEqual(workspace["limits"]["total_char_budget"], 50000)
        self.assertTrue(context["evidence_context"]["workspace"]["present"])
        self.assertEqual(context["evidence_context"]["workspace"]["perception_id"], "workspace.001")
        self.assertNotIn("raw_file_contents", repr(workspace))

    def test_compact_context_preserves_safe_openclaw_capability_policy_metadata(self) -> None:
        context = compact_composer_context(
            {
                "executor_capabilities": {
                    "executor_id": "openclaw",
                    "provider": "openclaw",
                    "status": "available",
                    "source": "static_baseline",
                    "capability_ids": [
                        "general_execution",
                        "tool_use",
                        "gateway_agent_turn",
                        "agent_routing",
                        "workspace_write",
                        "browser_or_external_tools",
                        "message_or_channel_work",
                        "channel_messaging",
                    ],
                    "permission_modes": ["read_only", "workspace_write", "danger_full_access"],
                    "summary": "Good for OpenClaw Gateway-backed agent turns.",
                    "limitations": [
                        "Static baseline, not live tool inventory.",
                        "OpenClaw permissions are controlled by OpenClaw exec-policy.",
                    ],
                    "metadata": {
                        "routing_model": "gateway_agent_turn",
                        "permission_enforcement": "executor_policy",
                        "permission_note": "OpenClaw policy owns the final tool boundary.",
                        "policy_commands": [
                            "openclaw exec-policy show --json",
                            "openclaw sandbox explain --json",
                        ],
                        "recommended_policy": {
                            "read_only": "deny-all or read-only allowlist",
                            "workspace_write": "cautious",
                            "danger_full_access": "yolo",
                        },
                        "raw_sdep_describe_response": {"drop": True},
                    },
                }
            }
        )

        capabilities = context["executor_capabilities"]
        self.assertEqual(capabilities["executor_id"], "openclaw")
        self.assertIn("gateway_agent_turn", capabilities["capability_ids"])
        self.assertEqual(capabilities["metadata"]["permission_enforcement"], "executor_policy")
        self.assertEqual(capabilities["metadata"]["recommended_policy"]["workspace_write"], "cautious")
        self.assertIn("openclaw exec-policy show --json", capabilities["metadata"]["policy_commands"])
        self.assertNotIn("raw_sdep_describe_response", repr(capabilities))

    def test_compact_context_keeps_url_perception_facts_without_raw_payloads(self) -> None:
        context = compact_composer_context(
            {
                "url_context": {
                    "schema_version": "spice.url_context.v1",
                    "source": "url_perception",
                    "perception_id": "url.001",
                    "trigger": "new_decision",
                    "query": "linked PR context",
                    "summary": "URL perception read a GitHub PR.",
                    "urls": ["https://github.com/Dyalwayshappy/Spice/pull/1"],
                    "documents": [
                        {
                            "url": "https://github.com/Dyalwayshappy/Spice/pull/1",
                            "final_url": "https://api.github.com/repos/Dyalwayshappy/Spice/issues/1",
                            "source_type": "github_pr",
                            "title": "Add URL perception",
                            "chars_read": 1200,
                            "truncated": False,
                            "raw_response": "drop this",
                        }
                    ],
                    "facts": [
                        {
                            "text": "The PR adds read-only URL perception artifacts.",
                            "source_url": "https://github.com/Dyalwayshappy/Spice/pull/1",
                            "title": "Add URL perception",
                            "confidence": 0.72,
                        }
                    ],
                    "snippets": [
                        {
                            "url": "https://github.com/Dyalwayshappy/Spice/pull/1",
                            "title": "Add URL perception",
                            "text": "A" * 900,
                            "source": "github_pr",
                            "raw_text": "drop",
                        }
                    ],
                    "raw_documents": "drop this too",
                }
            }
        )

        url_context = context["url_context"]
        self.assertEqual(url_context["source"], "url_perception")
        self.assertEqual(url_context["perception_id"], "url.001")
        self.assertEqual(url_context["documents"][0]["source_type"], "github_pr")
        self.assertEqual(url_context["facts"][0]["source_url"], "https://github.com/Dyalwayshappy/Spice/pull/1")
        self.assertLessEqual(len(url_context["snippets"][0]["text"]), 603)
        self.assertTrue(context["evidence_context"]["url"]["present"])
        self.assertEqual(context["evidence_context"]["url"]["perception_id"], "url.001")
        serialized = repr(url_context)
        self.assertNotIn("raw_response", serialized)
        self.assertNotIn("raw_documents", serialized)
        self.assertNotIn("drop", serialized)

    def test_compact_context_enforces_budget_and_strips_raw_payloads(self) -> None:
        context = compact_composer_context(
            {
                "schema_version": "spice.composer_context.v1",
                "active_decision_frame": {
                    "decision_id": "decision.active",
                    "selected": {"candidate_id": "candidate.9", "title": "Latest"},
                    "candidates": [
                        {"label": str(index), "candidate_id": f"candidate.{index}", "title": f"Candidate {index}"}
                        for index in range(8)
                    ],
                    "raw_card": "do not include",
                },
                "latest_decision_artifact": {
                    "decision_id": "decision.latest",
                    "run_id": "run.latest",
                    "decision_card": "large rendered card",
                    "raw_model_output": "raw llm text",
                },
                "recent_conversation_turns": [
                    {
                        "turn_id": f"turn.{index}",
                        "route": "follow_up",
                        "user_input": "x" * 500,
                        "metadata": {
                            "follow_up_response": {
                                "rendered_text": "summary " + ("y" * 500),
                                "raw_output": "raw should not survive",
                            },
                            "raw_executor_output": "raw should not survive",
                        },
                    }
                    for index in range(8)
                ],
                "recent_decisions": [
                    {
                        "decision_id": f"decision.{index}",
                        "recommendation": "r" * 500,
                        "compare_payload": {"full": "card"},
                    }
                    for index in range(6)
                ],
                "recent_approvals": [
                    {"approval_id": f"approval.{index}", "status": "pending", "raw": "drop"}
                    for index in range(5)
                ],
                "recent_executions": [
                    {
                        "outcome_id": f"outcome.{index}",
                        "status": "success",
                        "summary": "s" * 500,
                        "stdout": "raw stdout",
                    }
                    for index in range(5)
                ],
                "executor_capabilities": {
                    "executor_id": "hermes",
                    "source": "static_baseline",
                    "capability_ids": [f"capability.{index}" for index in range(20)],
                    "limitations": ["l" * 500 for _ in range(8)],
                    "metadata": {"raw_describe": "drop"},
                },
                "session_summary": {
                    "summary_text": "z" * 2000,
                    "pending_approvals": [f"approval.{index}" for index in range(5)],
                    "rolling_summary": {
                        "open_threads": [{"thread": index} for index in range(6)],
                        "user_preferences": [{"preference": index} for index in range(6)],
                    },
                },
                "retrieved_memory": [
                    {"id": f"memory.{index}", "namespace": "general.decision", "markdown": "m" * 500}
                    for index in range(6)
                ],
            }
        )

        self.assertEqual(len(context["active_decision_frame"]["candidates"]), 6)
        self.assertEqual(len(context["recent_conversation_turns"]), 6)
        self.assertEqual(context["recent_conversation_turns"][0]["turn_id"], "turn.2")
        self.assertEqual(len(context["recent_decisions"]), 3)
        self.assertEqual(context["recent_decisions"][0]["decision_id"], "decision.3")
        self.assertEqual(len(context["recent_approvals"]), 3)
        self.assertEqual(len(context["recent_executions"]), 3)
        self.assertEqual(len(context["executor_capabilities"]["capability_ids"]), 12)
        self.assertEqual(len(context["executor_capabilities"]["limitations"]), 6)
        self.assertLessEqual(len(context["session_summary"]["summary_text"]), 1200)
        self.assertEqual(len(context["session_summary"]["pending_approvals"]), 3)
        self.assertEqual(len(context["memory_summary"]["retrieved"]), 4)

        serialized = repr(context)
        self.assertNotIn("raw should not survive", serialized)
        self.assertNotIn("raw llm text", serialized)
        self.assertNotIn("large rendered card", serialized)
        self.assertNotIn("raw stdout", serialized)
        self.assertNotIn("raw_describe", serialized)

    def test_slim_recent_context_rebudgets_existing_context_payload(self) -> None:
        context = slim_recent_context(
            {
                "schema_version": "spice.composer_context.v1",
                "recent_conversation_turns": [
                    {"turn_id": f"turn.{index}", "user_input": "x" * 500}
                    for index in range(9)
                ],
                "recent_decisions": [{"decision_id": f"decision.{index}"} for index in range(5)],
                "latest_decision_artifact": {
                    "decision_id": "decision.latest",
                    "raw_model_output": "raw should not survive",
                },
                "executor_capabilities": {
                    "executor_id": "codex",
                    "source": "static_baseline",
                    "capability_ids": ["repo_read", "code_edit"],
                },
                "workspace_context": {
                    "source": "workspace_perception",
                    "perception_id": "workspace.slim",
                    "summary": "The repo already wires workspace facts into run_once.",
                    "facts": [{"text": "run_once accepts workspace_context."}],
                    "raw_file_contents": "drop",
                },
                "url_context": {
                    "source": "url_perception",
                    "perception_id": "url.slim",
                    "summary": "The linked issue describes URL perception.",
                    "facts": [{"text": "URL perception is read-only.", "source_url": "https://example.com/issue"}],
                    "raw_html": "drop",
                },
                "debug_dump": {"raw": "drop"},
            }
        )

        self.assertEqual(len(context["recent_conversation_turns"]), 6)
        self.assertEqual(context["recent_conversation_turns"][0]["turn_id"], "turn.3")
        self.assertEqual(len(context["recent_decisions"]), 3)
        self.assertEqual(context["latest_decision_artifact"]["decision_id"], "decision.latest")
        self.assertIn("executor_capabilities", context)
        self.assertEqual(context["executor_capabilities"]["executor_id"], "codex")
        self.assertEqual(context["workspace_context"]["perception_id"], "workspace.slim")
        self.assertIn("workspace facts", context["workspace_context"]["summary"])
        self.assertEqual(context["url_context"]["perception_id"], "url.slim")
        self.assertIn("read-only", context["url_context"]["facts"][0]["text"])
        self.assertTrue(context["evidence_context"]["workspace"]["present"])
        self.assertEqual(context["evidence_context"]["workspace"]["perception_id"], "workspace.slim")
        self.assertTrue(context["evidence_context"]["url"]["present"])
        self.assertEqual(context["evidence_context"]["url"]["perception_id"], "url.slim")
        serialized = repr(context)
        self.assertNotIn("raw should not survive", serialized)
        self.assertNotIn("raw_file_contents", serialized)
        self.assertNotIn("raw_html", serialized)
        self.assertNotIn("debug_dump", serialized)

    def test_build_context_from_workspace_includes_latest_artifact_and_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            result = run_once(
                "Compare state-as-context, perception, and executor handoff.",
                project_root=tmp_dir,
                use_bars=False,
                full_loop_preview=False,
            )

            context = build_composer_context_payload(
                project_root=tmp_dir,
                session_id=str(result.artifact["session_id"]),
                latest_artifact=result.artifact,
            )

        self.assertEqual(context["status"], "available")
        self.assertEqual(context["latest_decision_artifact"]["decision_id"], result.artifact["decision_id"])
        self.assertEqual(len(context["recent_conversation_turns"]), 1)
        self.assertEqual(context["executor_capabilities"]["executor_id"], "dry_run")
        self.assertEqual(context["executor_capabilities"]["source"], "static_baseline")
        self.assertEqual(context["workspace_context"]["memory_provider"], "file")
        self.assertIn("evidence_context", context)
        self.assertEqual(context["evidence_context"]["confidence"], "none")


if __name__ == "__main__":
    unittest.main()
