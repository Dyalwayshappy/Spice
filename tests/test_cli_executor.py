from __future__ import annotations

import sys
import unittest

from spice.executors import CLIActionMapping, CLIAdapterExecutor, CLIAdapterProfile, CLIInvocation
from spice.protocols import ExecutionIntent


class CLIExecutorTests(unittest.TestCase):
    def test_cli_executor_exact_match_success_json(self) -> None:
        profile = CLIAdapterProfile(
            profile_id="portable",
            display_name="Portable CLI",
            action_mappings={
                "repo.request.review": CLIActionMapping(
                    action_type="repo.request.review",
                    parser_mode="json",
                    default_outcome_type="observation",
                    render_invocation=lambda ctx: CLIInvocation(
                        argv=[
                            sys.executable,
                            "-c",
                            (
                                "import json,sys;"
                                "req=json.loads(sys.stdin.read() or '{}');"
                                "print(json.dumps({'outcome_type':'observation','action':req.get('action_type')}))"
                            ),
                        ],
                        stdin_text=(
                            '{"action_type":"repo.request.review","target":{"kind":"repo","id":"spice"}}'
                        ),
                    ),
                )
            },
        )
        executor = CLIAdapterExecutor(profile)
        intent = self._make_intent("repo.request.review")

        result = executor.execute(intent)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result_type, "observation")
        self.assertEqual(result.output.get("action"), "repo.request.review")
        trace = result.attributes.get("cli_adapter", {})
        self.assertEqual(trace.get("profile_id"), "portable")
        self.assertEqual(trace.get("capture", {}).get("exit_code"), 0)
        self.assertIn("argv", trace.get("invocation", {}))

    def test_cli_executor_fails_unknown_action_type(self) -> None:
        profile = CLIAdapterProfile(
            profile_id="portable",
            display_name="Portable CLI",
            action_mappings={
                "repo.request.review": CLIActionMapping(
                    action_type="repo.request.review",
                    render_invocation=lambda ctx: CLIInvocation(argv=[sys.executable, "-c", "print('ok')"]),
                )
            },
        )
        executor = CLIAdapterExecutor(profile)
        intent = self._make_intent("workspace.run.command")

        result = executor.execute(intent)

        self.assertEqual(result.status, "failed")
        self.assertIn("No CLI mapping configured", result.error or "")
        trace = result.attributes.get("cli_adapter", {})
        self.assertIn("available_action_types", trace)

    def test_cli_executor_json_first_text_fallback(self) -> None:
        profile = CLIAdapterProfile(
            profile_id="portable",
            display_name="Portable CLI",
            action_mappings={
                "workspace.run.command": CLIActionMapping(
                    action_type="workspace.run.command",
                    parser_mode="json",
                    default_outcome_type="observation",
                    render_invocation=lambda ctx: CLIInvocation(
                        argv=[sys.executable, "-c", "print('plain-text-output')"],
                    ),
                )
            },
        )
        executor = CLIAdapterExecutor(profile)
        intent = self._make_intent("workspace.run.command")

        result = executor.execute(intent)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result_type, "observation")
        self.assertIn("plain-text-output", result.output.get("text", ""))
        parse = result.attributes.get("cli_adapter", {}).get("parse", {})
        self.assertFalse(bool(parse.get("parsed_json")))
        self.assertIn("JSON parse failed", parse.get("parser_error", ""))

    def test_cli_executor_timeout_maps_to_failed_result(self) -> None:
        profile = CLIAdapterProfile(
            profile_id="portable",
            display_name="Portable CLI",
            default_timeout_seconds=0.1,
            action_mappings={
                "workspace.run.command": CLIActionMapping(
                    action_type="workspace.run.command",
                    parser_mode="text",
                    default_outcome_type="observation",
                    render_invocation=lambda ctx: CLIInvocation(
                        argv=[sys.executable, "-c", "import time; time.sleep(2)"],
                    ),
                )
            },
        )
        executor = CLIAdapterExecutor(profile)
        intent = self._make_intent("workspace.run.command")

        result = executor.execute(intent)

        self.assertEqual(result.status, "failed")
        self.assertIn("timed out", (result.error or "").lower())
        trace = result.attributes.get("cli_adapter", {})
        self.assertTrue(trace.get("capture", {}).get("timed_out"))

    def test_cli_executor_nonzero_exit_uses_stderr_error(self) -> None:
        profile = CLIAdapterProfile(
            profile_id="portable",
            display_name="Portable CLI",
            action_mappings={
                "workspace.run.command": CLIActionMapping(
                    action_type="workspace.run.command",
                    parser_mode="text",
                    default_outcome_type="observation",
                    render_invocation=lambda ctx: CLIInvocation(
                        argv=[
                            sys.executable,
                            "-c",
                            "import sys; print('command failed', file=sys.stderr); sys.exit(2)",
                        ],
                    ),
                )
            },
        )
        executor = CLIAdapterExecutor(profile)
        intent = self._make_intent("workspace.run.command")

        result = executor.execute(intent)

        self.assertEqual(result.status, "failed")
        self.assertIn("command failed", result.error or "")
        trace = result.attributes.get("cli_adapter", {})
        self.assertEqual(trace.get("capture", {}).get("exit_code"), 2)

    def test_cli_executor_result_type_prefers_outcome_type(self) -> None:
        profile = CLIAdapterProfile(
            profile_id="portable",
            display_name="Portable CLI",
            action_mappings={
                "repo.request.review": CLIActionMapping(
                    action_type="repo.request.review",
                    parser_mode="json",
                    default_outcome_type="observation",
                    render_invocation=lambda ctx: CLIInvocation(
                        argv=[
                            sys.executable,
                            "-c",
                            (
                                "import json;"
                                "print(json.dumps({'outcome_type':'state_delta','result_type':'legacy'}))"
                            ),
                        ],
                    ),
                )
            },
        )
        executor = CLIAdapterExecutor(profile)
        intent = self._make_intent("repo.request.review")

        result = executor.execute(intent)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result_type, "state_delta")

    @staticmethod
    def _make_intent(action_type: str) -> ExecutionIntent:
        return ExecutionIntent(
            id=f"intent-{action_type.replace('.', '-')}",
            intent_type="demo.action",
            status="planned",
            objective={"id": "obj-1", "description": "CLI adapter test"},
            executor_type="external-agent",
            target={"kind": "repo", "id": "spice"},
            operation={"name": action_type, "mode": "sync", "dry_run": False},
            input_payload={"prompt": "review the diff"},
            parameters={"temperature": "low"},
            constraints=[],
            success_criteria=[],
            failure_policy={"strategy": "fail_fast", "max_retries": 0},
            refs=[],
            provenance={"source": "test"},
        )


if __name__ == "__main__":
    unittest.main()
