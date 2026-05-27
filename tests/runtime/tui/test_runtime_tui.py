from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from spice.perception import (
    INVESTIGATION_CONSENT_GRANTED,
    INVESTIGATION_CONSENT_PENDING,
    INVESTIGATION_CONSENT_REJECTED,
    build_investigation_consent,
    build_workspace_perception_artifact,
    workspace_context_from_perception,
)
from spice.runtime import (
    LocalJsonStore,
    load_workspace_config,
    load_workspace_memory_provider,
    run_once,
    setup_workspace,
    update_workspace_config,
)
from spice.runtime.approval_flow import load_approval
from spice.runtime.composer_context import build_composer_context_payload
from spice.runtime.composer_result import ComposerResult
from spice.runtime.semantic_router import SemanticRoute
from spice.runtime.tui.shell import (
    SpiceTUIShell,
    _investigation_action_options,
    _investigation_consent_text,
    _startup_dashboard,
    _url_evidence_status_label,
    _workspace_evidence_status_label,
    run_tui_shell,
)
from spice.runtime.tui.surfaces.banner import render_banner
from spice.runtime.tui.theme import COMMANDS


class RuntimeTUITests(unittest.TestCase):
    def test_run_tui_shell_plain_uses_plain_shell(self) -> None:
        with patch("spice.runtime.tui.shell.run_interactive_shell") as plain:
            plain.return_value = object()

            result = run_tui_shell(project_root=".", plain=True)

            self.assertIs(result, plain.return_value)
            plain.assert_called_once()

    def test_run_tui_shell_falls_back_when_prompt_toolkit_missing(self) -> None:
        with patch("spice.runtime.tui.shell._prompt_toolkit_available", return_value=False):
            with patch("spice.runtime.tui.shell.run_interactive_shell") as plain:
                plain.return_value = object()

                result = run_tui_shell(project_root=".")

                self.assertIs(result, plain.return_value)
                plain.assert_called_once()

    def test_tui_shell_startup_loads_setup_saved_env_before_interaction(self) -> None:
        class EOFPromptSession:
            def prompt(self, *_: object, **__: object) -> str:
                raise EOFError

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            env_path = Path(tmp_dir) / ".spice" / ".env"
            env_path.write_text("OPENROUTER_API_KEY=from-setup\n", encoding="utf-8")
            output = io.StringIO()

            with patch.dict(os.environ, {}, clear=True):
                with patch.object(SpiceTUIShell, "_build_prompt_session", return_value=EOFPromptSession()):
                    with patch.object(SpiceTUIShell, "_build_console", return_value=None):
                        shell = SpiceTUIShell(
                            project_root=tmp_dir,
                            output_stream=output,
                            history_path=Path(tmp_dir) / "history",
                        )
                        shell.run()

                self.assertEqual(os.environ.get("OPENROUTER_API_KEY"), "from-setup")

    def test_banner_plain_fallback_contains_runtime_metadata(self) -> None:
        def blocked_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "rich" or name.startswith("rich."):
                raise ImportError("blocked")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=blocked_import):
            banner = render_banner(
                {"executor": "dry_run", "llm_provider": "deterministic", "perception_provider": "manual"},
                {"session_id": "session.default"},
            )

        self.assertIn("Spice Decision Runtime", str(banner))
        self.assertIn("executor: dry_run", str(banner))
        self.assertIn("Available Executors", str(banner))
        self.assertIn("Available Skills", str(banner))

    def test_banner_dashboard_lists_runtime_capabilities(self) -> None:
        from rich.console import Console

        renderable = render_banner(
            {
                "executor": "dry_run",
                "llm_provider": "deterministic",
                "perception_provider": "manual",
            },
            {"session_id": "session.default"},
            dashboard={
                "mode": "decision + dry-run",
                "pending_approvals": 1,
                "decision_count": 3,
                "state_counts": {"work_items": 2, "outcomes": 1},
                "executors": [
                    {"name": "dry_run", "status": "ready"},
                    {"name": "sdep_subprocess", "status": "needs executor_command"},
                ],
                "skills": [
                    {"name": "item.triage", "status": "ready"},
                    {"name": "intent.execute", "status": "ready"},
                ],
                "perception": [
                    {"name": "manual", "status": "ready"},
                    {"name": "poll", "status": "needs poll source"},
                ],
            },
        )
        console = Console(file=io.StringIO(), record=True, force_terminal=False, width=120)
        console.print(renderable)
        text = console.export_text()

        self.assertIn("RUNTIME READINESS", text)
        self.assertIn("Available Executors", text)
        self.assertIn("dry_run", text)
        self.assertIn("Available Skills", text)
        self.assertIn("item.triage", text)
        self.assertIn("Perception", text)
        self.assertIn("pending", text)
        self.assertIn("/pending", text)

    def test_tui_startup_dashboard_marks_openclaw_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "openclaw")
            update_workspace_config(tmp_dir, "executor_command", f"{sys.executable} -c pass")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            config = load_workspace_config(tmp_dir).to_payload()

            dashboard = _startup_dashboard(shell._store(), config)

        self.assertEqual(dashboard["mode"], "decision + OpenClaw handoff")
        executors = {item["name"]: item["status"] for item in dashboard["executors"]}
        self.assertEqual(executors["openclaw"], "configured")

    def test_tui_evidence_status_labels_are_specific(self) -> None:
        self.assertEqual(
            _workspace_evidence_status_label(),
            "Detected repo reference. Reading workspace evidence...",
        )
        self.assertEqual(
            _url_evidence_status_label(),
            "Detected URL. Fetching linked context...",
        )

    def test_tui_investigation_consent_uses_deeper_external_copy(self) -> None:
        consent = build_investigation_consent(
            executor_id="hermes",
            query="Research external agent routing designs.",
        )

        text = _investigation_consent_text(consent, None)
        options = _investigation_action_options("hermes")

        self.assertIn(
            "This needs deeper external investigation. Ask Hermes to run read-only investigation?",
            text,
        )
        self.assertIn("I can ask Hermes to investigate.", text)
        self.assertIn("findings and sources", text)
        self.assertEqual(options[0][1], "Allow read-only investigation via Hermes")

    def test_banner_uses_compact_header_when_terminal_is_narrow(self) -> None:
        from rich.console import Console

        renderable = render_banner(
            {
                "executor": "dry_run",
                "llm_provider": "deterministic",
                "perception_provider": "manual",
            },
            {"session_id": "session.default"},
            width=38,
        )
        console = Console(file=io.StringIO(), record=True, force_terminal=False, width=38)
        console.print(renderable)
        text = console.export_text()

        self.assertIn("compact", text)
        self.assertIn("banner", text)
        self.assertNotIn("██████", text)

    def test_tui_shell_refresh_redraws_banner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.store = LocalJsonStore.from_project_root(tmp_dir)

            should_exit = shell.handle_line("/refresh")

            self.assertFalse(should_exit)
            self.assertIn("Spice Decision Runtime", output.getvalue())

    def test_tui_shell_handles_intent_with_decision_brief_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            should_exit = shell.handle_line("Review the repo and pick the safest next action.")

            self.assertFalse(should_exit)
            text = output.getvalue()
            self.assertIn("I'd choose", text)
            self.assertNotIn("SPICE DECISION CARD", text)
            self.assertNotIn("Artifacts:", text)
            self.assertIn("Next:", text)
            self.assertIn("details  expand the full Decision Card", text)
            self.assertIn("Card is folded.", text)
            self.assertIn("/json for the raw artifact", text)
            self.assertEqual(shell.result.turns, 1)
            run = shell._store().load_run(shell.result.run_ids[-1])
            streaming = run["response_composer"]["metadata"]["streaming"]
            self.assertEqual(streaming["mode"], "block_display")
            self.assertGreaterEqual(streaming["chunk_count"], 1)
            self.assertEqual(streaming["source"], "validated_composer_result")
            turn = shell._store().load_conversation_turn(run["conversation_turn_id"])
            self.assertEqual(turn["metadata"]["decision_response"]["metadata"]["streaming"], streaming)

    def test_tui_shell_run_intent_uses_stream_writer_for_status_and_response_blocks(self) -> None:
        events: list[tuple[str, str, str]] = []
        blocks: list[str] = []
        text_chunks: list[str] = []

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                pass

            def start(self) -> "FakeStreamWriter":
                events.append(("start", "", ""))
                return self

            def status(self, label: str, detail: str = "") -> None:
                events.append(("status", label, detail))

            def write(self, text: str) -> None:
                text_chunks.append(text)

            def write_block(self, text: str) -> None:
                blocks.append(text)

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("finish", label, detail))

            def fail(self, fallback_text: str = "") -> None:
                events.append(("fail", fallback_text, ""))

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch("spice.runtime.tui.shell.TUIStreamWriter", FakeStreamWriter):
                should_exit = shell.handle_line("Review the repo and pick the safest next action.")

        self.assertFalse(should_exit)
        self.assertIn(("status", "Thinking through the decision...", "deterministic runtime"), events)
        self.assertIn(("status", "Composing response...", "deterministic runtime"), events)
        self.assertIn(("finish", "Ready.", ""), events)
        self.assertLess(
            events.index(("status", "Thinking through the decision...", "deterministic runtime")),
            events.index(("status", "Composing response...", "deterministic runtime")),
        )
        self.assertLess(
            events.index(("status", "Composing response...", "deterministic runtime")),
            events.index(("finish", "Ready.", "")),
        )
        self.assertTrue(any("I'd choose" in block for block in blocks))
        self.assertTrue(any("Card is folded." in block for block in blocks))
        self.assertEqual(text_chunks, [])

    def test_tui_shell_new_decision_forces_workspace_perception_for_repo_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            workspace_step = SimpleNamespace(
                context={
                    "perception_id": "workspace.test",
                    "summary": "Read runtime implementation.",
                    "files_read": [{"path": "spice/runtime/run_once.py"}],
                },
                artifact={"perception_id": "workspace.test"},
            )

            with patch.object(shell, "_run_workspace_perception_step", return_value=workspace_step) as workspace:
                should_exit = shell.handle_line("基于当前实现看一下下一步怎么做")

        self.assertFalse(should_exit)
        workspace.assert_called_once()
        self.assertEqual(workspace.call_args.kwargs["trigger"], "new_decision")
        policy = workspace.call_args.kwargs["route_policy"].to_payload()
        self.assertTrue(policy["needs_workspace_context"])
        self.assertEqual(policy["evidence_requirement"]["evidence_domain"], "repo")

    def test_tui_shell_follow_up_forces_workspace_perception_for_repo_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            _install_execution_ready_frame(shell)
            route = SemanticRoute(
                route="follow_up",
                action="answer_from_decision",
                is_continuation=True,
                text="基于当前实现解释一下",
            )
            workspace_step = SimpleNamespace(
                context={"perception_id": "workspace.followup", "files_read": [{"path": "spice/runtime/tui/shell.py"}]},
                artifact={"perception_id": "workspace.followup"},
            )

            with patch("spice.runtime.tui.shell.route_semantic_input_from_runtime_config", return_value=route):
                with patch.object(shell, "_run_workspace_perception_step", return_value=workspace_step) as workspace:
                    with patch.object(shell, "_handle_continuation_resolution") as handler:
                        handled = shell._handle_continuation("基于当前实现解释一下")

        self.assertTrue(handled)
        workspace.assert_called_once()
        self.assertEqual(workspace.call_args.kwargs["trigger"], "follow_up:answer_from_decision")
        handler.assert_called_once()
        self.assertEqual(handler.call_args.kwargs["workspace_context"]["perception_id"], "workspace.followup")

    def test_tui_shell_run_intent_runs_url_perception_before_missing_evidence_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            url_step = SimpleNamespace(
                context={
                    "perception_id": "url.new",
                    "documents": [{"url": "https://example.com/spec", "title": "Spec"}],
                    "facts": [{"text": "The linked spec describes terminal UX."}],
                },
                artifact={"perception_id": "url.new"},
            )

            with patch.object(shell, "_run_url_perception_step", return_value=url_step) as url:
                with patch("spice.runtime.tui.shell.run_once", side_effect=RuntimeError("stop after url")) as run:
                    should_exit = shell.handle_line("基于 https://example.com/spec 判断终端载体")

        self.assertFalse(should_exit)
        url.assert_called_once()
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["url_context"]["perception_id"], "url.new")
        self.assertNotIn(
            "I still do not have the required evidence source after attempting perception",
            output.getvalue(),
        )

    def test_tui_shell_follow_up_runs_url_perception_before_missing_evidence_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            _install_execution_ready_frame(shell)
            route = SemanticRoute(
                route="follow_up",
                action="answer_from_decision",
                is_continuation=True,
                text="结合 https://example.com/spec 回答",
                context_strategy="url",
                needs_url_context=True,
                url_query="结合 https://example.com/spec 回答",
                urls=["https://example.com/spec"],
            )
            url_step = SimpleNamespace(
                context={
                    "perception_id": "url.followup",
                    "documents": [{"url": "https://example.com/spec", "title": "Spec"}],
                    "facts": [{"text": "The linked spec describes follow-up UX."}],
                },
                artifact={"perception_id": "url.followup"},
            )

            with patch("spice.runtime.tui.shell.route_semantic_input_from_runtime_config", return_value=route):
                with patch.object(shell, "_run_url_perception_step", return_value=url_step) as url:
                    with patch.object(shell, "_handle_continuation_resolution") as handler:
                        handled = shell._handle_continuation("结合 https://example.com/spec 回答")

        self.assertTrue(handled)
        url.assert_called_once()
        handler.assert_called_once()
        self.assertEqual(handler.call_args.kwargs["url_context"]["perception_id"], "url.followup")
        self.assertNotIn(
            "I still do not have the required evidence source after attempting perception",
            output.getvalue(),
        )

    def test_tui_shell_refine_runs_url_perception_before_missing_evidence_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            route = SemanticRoute(
                route="follow_up",
                action="refine_decision",
                is_continuation=True,
                text="结合 https://example.com/spec refine",
                context_strategy="url",
                needs_url_context=True,
                url_query="结合 https://example.com/spec refine",
                urls=["https://example.com/spec"],
            )
            url_step = SimpleNamespace(
                context={
                    "perception_id": "url.refine.tui",
                    "documents": [{"url": "https://example.com/spec", "title": "Spec"}],
                    "facts": [{"text": "The linked spec describes refine UX."}],
                },
                artifact={"perception_id": "url.refine.tui"},
            )

            with patch("spice.runtime.tui.shell.route_semantic_input_from_runtime_config", return_value=route):
                with patch.object(shell, "_run_url_perception_step", return_value=url_step) as url:
                    with patch("spice.runtime.tui.shell.refine_decision", side_effect=RuntimeError("stop after url")):
                        shell._refine_decision("结合 https://example.com/spec refine")

        url.assert_called_once()
        self.assertNotIn(
            "I still do not have the required evidence source after attempting perception",
            output.getvalue(),
        )

    def test_tui_shell_pre_run_evidence_gate_blocks_unconfirmed_external_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with tempfile.TemporaryDirectory() as external_dir:
                setup_workspace(project_root=tmp_dir)
                Path(external_dir, "pyproject.toml").write_text("[project]\nname='external'\n", encoding="utf-8")
                output = io.StringIO()
                shell = self._plain_output_shell(tmp_dir, output)

                with patch.object(shell, "_run_workspace_perception_step") as workspace:
                    should_exit = shell.handle_line(f"请读取本地 {external_dir} 当前实现再判断")

        self.assertFalse(should_exit)
        workspace.assert_not_called()
        text = output.getvalue()
        self.assertIn("I need evidence before answering this safely.", text)
        self.assertIn("external repo path", text)

    def test_tui_shell_decision_loading_updates_to_composing_before_ready(self) -> None:
        events: list[tuple[str, str, str]] = []

        class FakeStatusFlow:
            def __init__(self, *, console: object, title: str, label: str, detail: str = "") -> None:
                self.label = label
                self.detail = detail
                events.append(("init", label, detail))

            def __enter__(self) -> "FakeStatusFlow":
                events.append(("enter", self.label, self.detail))
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                events.append(("exit", "", ""))

            def update(self, label: str, detail: str = "") -> None:
                events.append(("update", label, detail))

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("finish", label, detail))

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                pass

            def start(self) -> "FakeStreamWriter":
                return self

            def status(self, label: str, detail: str = "") -> None:
                events.append(("stream_status", label, detail))

            def write(self, text: str) -> None:
                pass

            def write_block(self, text: str) -> None:
                pass

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("stream_finish", label, detail))

            def fail(self, fallback_text: str = "") -> None:
                events.append(("stream_fail", fallback_text, ""))

        class FakeConsole:
            def __init__(self) -> None:
                self.output = io.StringIO()

            def print(self, text: str, *, end: str = "\n", **_: object) -> None:
                self.output.write(f"{text}{end}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            console = FakeConsole()
            with patch.object(SpiceTUIShell, "_build_prompt_session", return_value=object()):
                with patch.object(SpiceTUIShell, "_build_console", return_value=console):
                    shell = SpiceTUIShell(
                        project_root=tmp_dir,
                        output_stream=output,
                        history_path=Path(tmp_dir) / "history",
                    )

            with patch("spice.runtime.tui.surfaces.stream.TUIStatusFlow", FakeStatusFlow):
                should_exit = shell.handle_line("Review the repo and pick the safest next action.")

        self.assertFalse(should_exit)
        self.assertEqual(events[0][0], "init")
        self.assertEqual(events[0][1], "Thinking through the decision...")
        self.assertIn(("update", "Composing response...", "deterministic runtime"), events)
        self.assertIn(("finish", "Ready.", ""), events)
        self.assertLess(events.index(("update", "Composing response...", "deterministic runtime")), events.index(("finish", "Ready.", "")))

    def test_tui_shell_decision_brief_render_failure_uses_deterministic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch(
                "spice.runtime.tui.shell.compose_decision_response_from_runtime_config",
                side_effect=ValueError("composer failed"),
            ):
                should_exit = shell.handle_line("Review the repo and pick the safest next action.")

            self.assertFalse(should_exit)
            text = output.getvalue()
            self.assertIn("I'd choose", text)
            self.assertNotIn("deterministic brief fallback", text)
            self.assertNotIn("SPICE DECISION CARD", text)
            self.assertNotIn("Artifacts:", text)
            self.assertIn("Next:", text)
            self.assertEqual(shell.result.turns, 1)

    def test_tui_shell_default_response_uses_llm_response_composer_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            composed = SimpleNamespace(
                response_text=(
                    "I would start with the state work.\n\n"
                    "That gives Spice better continuity before we deepen handoff."
                )
            )

            with patch(
                "spice.runtime.tui.shell.compose_decision_response_from_runtime_config",
                return_value=composed,
            ) as composer:
                should_exit = shell.handle_line("Review the repo and pick the safest next action.")

            self.assertFalse(should_exit)
            composer.assert_called_once()
            text = output.getvalue()
            self.assertIn("I would start with the state work.", text)
            self.assertNotIn("SPICE DECISION CARD", text)
            self.assertNotIn("Artifacts:", text)
            self.assertIn("Card is folded.", text)
            self.assertIn("/json for the raw artifact", text)

    def test_tui_decision_composer_fallback_is_recorded_without_debug_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            composed = ComposerResult(
                enabled=True,
                status="fallback",
                response_text="I would start with the deterministic brief.",
                deterministic_text="I would start with the deterministic brief.",
                composer_kind="decision_response",
                model_provider="fake",
                model_id="fake-model",
                raw_output='{"not_response": true}',
                fallback_reason="invalid_composed_response",
                error="missing response text",
            )

            with patch(
                "spice.runtime.tui.shell.compose_decision_response_from_runtime_config",
                return_value=composed,
            ):
                should_exit = shell.handle_line("Review the repo and pick the safest next action.")

            self.assertFalse(should_exit)
            text = output.getvalue()
            self.assertIn("I would start with the deterministic brief.", text)
            self.assertNotIn("invalid_composed_response", text)
            self.assertNotIn("not_response", text)
            run = shell._store().load_run(shell.result.run_ids[-1])
            self.assertEqual(run["response_composer"]["status"], "fallback")
            self.assertEqual(run["response_composer"]["raw_output"], '{"not_response": true}')
            self.assertEqual(run["response_composer"]["fallback_reason"], "invalid_composed_response")
            turn = shell._store().load_conversation_turn(run["conversation_turn_id"])
            self.assertEqual(turn["metadata"]["decision_response"]["raw_output"], '{"not_response": true}')

    def test_tui_streamed_decision_composer_fallback_streams_correction_and_deterministic_text(self) -> None:
        def fake_composer(**kwargs: object) -> ComposerResult:
            raw_output = "I recommend Option B instead."
            stream_callback = kwargs.get("stream_callback")
            if callable(stream_callback):
                stream_callback(raw_output)
            return ComposerResult(
                enabled=True,
                status="fallback",
                response_text="I'd choose Option A after validating the decision facts.",
                deterministic_text="I'd choose Option A after validating the decision facts.",
                composer_kind="decision_response",
                model_provider="fake",
                model_id="fake-stream-model",
                raw_output=raw_output,
                fallback_reason="invalid_composed_response",
                error="response recommended non-selected candidate",
                metadata={
                    "streaming": {
                        "mode": "provider_token_stream",
                        "displayed_to_user": True,
                        "valid": False,
                        "fallback_reason": "invalid_composed_response",
                        "source": "invalid_streamed_composer_result",
                    }
                },
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch(
                "spice.runtime.tui.shell.compose_decision_response_from_runtime_config",
                side_effect=fake_composer,
            ):
                should_exit = shell.handle_line("Review the repo and pick the safest next action.")

            self.assertFalse(should_exit)
            text = output.getvalue()
            self.assertIn("I recommend Option B instead.", text)
            self.assertIn("I need to correct that response after validating it:", text)
            self.assertIn("I'd choose Option A after validating the decision facts.", text)
            run = shell._store().load_run(shell.result.run_ids[-1])
            composer = run["response_composer"]
            self.assertEqual(composer["status"], "fallback")
            self.assertEqual(composer["raw_output"], "I recommend Option B instead.")
            self.assertFalse(composer["metadata"]["streaming"]["valid"])

    def test_tui_streamed_json_composer_output_is_not_rendered_raw(self) -> None:
        def fake_composer(**_: object) -> ComposerResult:
            return ComposerResult(
                enabled=True,
                status="composed",
                response_text="I would start with Option A.",
                deterministic_text="I'd choose Option A.",
                composer_kind="decision_response",
                model_provider="fake",
                model_id="fake-stream-model",
                raw_output='{"response": "I would start with Option A."}',
                metadata={
                    "streaming": {
                        "mode": "provider_token_stream",
                        "displayed_to_user": False,
                        "valid": True,
                        "raw_text_chunk_count": 1,
                        "text_chunk_count": 0,
                        "source": "validated_streamed_composer_result",
                    }
                },
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch(
                "spice.runtime.tui.shell.compose_decision_response_from_runtime_config",
                side_effect=fake_composer,
            ):
                self.assertFalse(shell.handle_line("Review the repo and pick the safest next action."))

            text = output.getvalue()
            self.assertIn("I would start with Option A.", text)
            self.assertNotIn('{"response"', text)
            self.assertIn("Card is folded.", text)

    def test_tui_shell_refine_updates_latest_decision_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("Review the repo and pick the safest next action.")
            self.assertFalse(shell.handle_line("/refine Consider rollback first."))

            text = output.getvalue()
            self.assertIn("I'd choose", text)
            self.assertNotIn("Refine artifacts:", text)
            self.assertIn("Card is folded.", text)
            self.assertIn("/json for the raw artifact", text)
            self.assertEqual(shell.result.turns, 2)

    def test_tui_shell_refine_response_uses_stream_writer(self) -> None:
        stream_blocks: list[str] = []
        finish_labels: list[str] = []

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                pass

            def start(self) -> "FakeStreamWriter":
                return self

            def write_block(self, text: str) -> None:
                stream_blocks.append(text)

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                finish_labels.append(label)

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.handle_line("Review the repo and pick the safest next action.")

            with patch("spice.runtime.tui.shell.TUIStreamWriter", FakeStreamWriter):
                self.assertFalse(shell.handle_line("/refine Consider rollback first."))

        self.assertTrue(any("I'd choose" in block for block in stream_blocks))
        self.assertTrue(any("Card is folded." in block for block in stream_blocks))
        self.assertEqual(finish_labels, ["Ready."])

    def test_tui_shell_refine_loading_updates_to_composing_before_ready(self) -> None:
        events: list[tuple[str, str, str]] = []

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                pass

            def start(self) -> "FakeStreamWriter":
                events.append(("start", "", ""))
                return self

            def status(self, label: str, detail: str = "") -> None:
                events.append(("status", label, detail))

            def write(self, text: str) -> None:
                pass

            def write_block(self, text: str) -> None:
                pass

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("finish", label, detail))

            def fail(self, fallback_text: str = "") -> None:
                events.append(("fail", fallback_text, ""))

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.handle_line("Review the repo and pick the safest next action.")
            events.clear()

            with patch("spice.runtime.tui.shell.TUIStreamWriter", FakeStreamWriter):
                should_exit = shell.handle_line("/refine Consider rollback first.")

        self.assertFalse(should_exit)
        self.assertIn(("status", "Revisiting the decision...", "deterministic runtime"), events)
        self.assertIn(("status", "Composing updated response...", "deterministic runtime"), events)
        self.assertIn(("finish", "Ready.", ""), events)
        self.assertLess(
            events.index(("status", "Composing updated response...", "deterministic runtime")),
            events.index(("finish", "Ready.", "")),
        )

    def test_tui_shell_enters_decision_feedback_after_action_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/act Fix the failing test."))

            text = output.getvalue()
            self.assertIn("Decision prompt shortcuts", text)
            self.assertIn("y / yes", text)
            self.assertIn("approve and execute with the configured executor", text)
            self.assertIn("decision> y", text)
            self.assertIn("decision> reject too risky right now", text)
            self.assertIn("decision> refine execute directly; do not split", text)
            self.assertIsNotNone(shell.pending_decision)
            self.assertEqual(shell._prompt_text(), "decision> ")

    def test_tui_shell_approve_only_uses_latest_pending_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            approval_id = str(shell.pending_decision["approval_id"])
            self.assertFalse(shell.handle_line("a"))

            text = output.getvalue()
            self.assertIn("APPROVAL APPROVED", text)
            self.assertIn(approval_id, shell.result.approved_ids)
            self.assertIsNone(shell.pending_decision)
            self.assertEqual(shell._prompt_text(), "spice> ")

    def test_tui_shell_decision_action_picker_can_approve_latest_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch.object(shell, "_decision_action_picker_available", return_value=True):
                with patch.object(shell, "_prompt_decision_action", return_value="approve") as picker:
                    self.assertFalse(shell.handle_line("/act Fix the failing test."))

            text = output.getvalue()
            self.assertIn("APPROVAL APPROVED", text)
            self.assertIsNone(shell.pending_decision)
            picker.assert_called_once()

    def test_tui_shell_decision_action_picker_is_available_for_tty_output(self) -> None:
        class TTYOutput(io.StringIO):
            def isatty(self) -> bool:
                return True

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = TTYOutput()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.console = object()

            with patch("spice.runtime.tui.shell._prompt_toolkit_available", return_value=True):
                self.assertTrue(shell._decision_action_picker_available())

    def test_tui_shell_yes_approves_and_executes_latest_pending_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            approval_id = str(shell.pending_decision["approval_id"])
            self.assertFalse(shell.handle_line("y"))

            text = output.getvalue()
            self.assertIn("APPROVAL APPROVED", text)
            self.assertNotIn("EXECUTION COMPLETE", text)
            self.assertIn("dry_run finished the handoff", text)
            self.assertIn(approval_id, shell.result.approved_ids)
            self.assertGreaterEqual(len(shell.result.dry_run_outcome_ids), 1)
            self.assertIsNone(shell.pending_decision)
            evolution_records = load_workspace_memory_provider(tmp_dir).query(
                namespace="general.evolution",
                limit=-1,
            )
            approval_records = [
                record
                for record in evolution_records
                if record.get("approval_id") == approval_id
                and record.get("follow_up_type") == "approval_resolution"
            ]
            execution_records = [
                record
                for record in evolution_records
                if record.get("approval_id") == approval_id
                and record.get("follow_up_type") == "execution_result"
            ]
            self.assertEqual(len(approval_records), 1)
            self.assertEqual(approval_records[0]["approval"]["status"], "approved")
            self.assertEqual(len(execution_records), 1)
            self.assertEqual(execution_records[0]["route_result"]["action"], "execution_result")
            self.assertTrue(execution_records[0]["outcome_id"])

    def test_tui_shell_rejects_latest_pending_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            approval_id = str(shell.pending_decision["approval_id"])
            self.assertFalse(shell.handle_line("n too risky right now"))

            text = output.getvalue()
            self.assertIn("APPROVAL REJECTED", text)
            self.assertIn(approval_id, shell.result.rejected_ids)
            self.assertIsNone(shell.pending_decision)

    def test_tui_shell_feedback_refines_latest_pending_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            self.assertFalse(shell.handle_line("consider rollback first"))

            text = output.getvalue()
            self.assertIn("Card is folded.", text)
            self.assertIn("/json for the raw artifact", text)
            self.assertNotIn("Refine artifacts:", text)
            self.assertEqual(shell.result.turns, 2)
            self.assertIsNotNone(shell.pending_decision)

    def test_tui_shell_doctor_and_state_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/doctor"))
            self.assertFalse(shell.handle_line("/state"))

            text = output.getvalue()
            self.assertIn("SPICE DOCTOR", text)
            self.assertIn("WORLD STATE", text)

    def test_tui_shell_context_command_renders_compiled_decision_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/context"))

            text = output.getvalue()
            self.assertIn("COMPILED DECISION CONTEXT", text)
            self.assertIn("context_type", text)
            self.assertIn("decision", text)
            self.assertIn("executor_capabilities", text)
            self.assertIn("workspace", text)

    def test_tui_shell_context_command_renders_workspace_debug_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            store = LocalJsonStore.from_project_root(tmp_dir)
            perception = build_workspace_perception_artifact(
                workspace_root=tmp_dir,
                trigger="test",
                query="context debug summary",
                files_read=[{"path": "spice/runtime/context_debug.py", "chars_read": 900}],
                facts=[{"text": "context command summarizes workspace perception."}],
                summary="Context command can show workspace evidence.",
                exploration_status="partial",
                depth="normal",
                budget_used={
                    "rounds_used": 2,
                    "tool_calls_executed": 4,
                    "tool_calls_blocked": 1,
                    "chars_used": 900,
                    "total_char_budget": 500000,
                    "budget_pressure": "medium",
                },
                metadata={
                    "loop": {
                        "sufficiency_check": {
                            "sufficient_evidence": False,
                            "can_answer_user_question": True,
                            "remaining_gaps": ["tests not inspected"],
                            "reason": "Read workspace context debug.",
                        }
                    }
                },
            ).to_payload()
            store.save_perception(str(perception["perception_id"]), perception)
            run_once(
                "Plan based on workspace context.",
                project_root=tmp_dir,
                workspace_context=workspace_context_from_perception(perception),
                workspace_perception=perception,
                full_loop_preview=False,
            )
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/context"))

            text = output.getvalue()
            self.assertIn("workspace_perception", text)
            self.assertIn("depth=normal", text)
            self.assertIn("status=partial", text)
            self.assertIn("rounds=2", text)
            self.assertIn("tools=4", text)
            self.assertIn("blocked=1", text)
            self.assertIn("chars=900/500000", text)
            self.assertIn("pressure=medium", text)
            self.assertIn("sufficiency=partial", text)
            self.assertIn("gaps=1", text)

    def test_tui_shell_context_json_outputs_exact_context_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/context --json"))

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["context_type"], "decision")
            self.assertEqual(payload["domain"], "general")
            self.assertEqual(payload["workspace_context"]["memory_provider"], "file")
            self.assertEqual(payload["workspace_context"]["context_compiler"], "deterministic")
            self.assertEqual(payload["executor_capabilities"]["executor_id"], "dry_run")
            self.assertIn("retrieved_memory", payload)

    def test_tui_shell_context_json_includes_active_decision_frame_after_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            setup_output = io.StringIO()
            setup_shell = self._plain_output_shell(tmp_dir, setup_output)
            setup_shell.handle_line("Review the repo and pick the safest next action.")

            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            self.assertFalse(shell.handle_line("/context --json"))

            payload = json.loads(output.getvalue())
            frame = payload["active_decision_frame"]
            self.assertTrue(frame["decision_id"])
            self.assertEqual(
                payload["current_intent"]["text"],
                "Review the repo and pick the safest next action.",
            )
            self.assertTrue(frame["candidates"])

    def test_tui_shell_workspace_command_renders_latest_workspace_perception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            store = LocalJsonStore.from_project_root(tmp_dir)
            perception = build_workspace_perception_artifact(
                workspace_root=tmp_dir,
                trigger="test",
                query="current workspace context implementation",
                tool_calls=[
                    {
                        "call_id": "tool.1",
                        "round_index": 1,
                        "tool": "read_file",
                        "status": "executed",
                    }
                ],
                blocked_tool_calls=[
                    {
                        "call_id": "tool.2",
                        "round_index": 1,
                        "tool": "write_file",
                        "status": "blocked",
                        "reason": "tool_not_allowed",
                    }
                ],
                files_read=[{"path": "spice/runtime/run_once.py", "chars_read": 1200}],
                facts=[
                    {
                        "text": "run_once accepts workspace_context.",
                        "source_path": "spice/runtime/run_once.py",
                    }
                ],
                summary="Workspace context is wired into run_once.",
                exploration_status="partial",
                depth="normal",
                budget_used={
                    "rounds_used": 2,
                    "tool_calls_executed": 4,
                    "tool_calls_blocked": 1,
                    "chars_used": 1200,
                    "total_char_budget": 500000,
                    "budget_pressure": "medium",
                },
                budget_pressure_events=[
                    {
                        "round_index": 2,
                        "stage": "after_round",
                        "budget_pressure": "medium",
                    }
                ],
                limitations=["tests not inspected"],
                metadata={
                    "loop": {
                        "sufficiency_check": {
                            "sufficient_evidence": False,
                            "can_answer_user_question": True,
                            "remaining_gaps": ["tests not inspected"],
                            "reason": "Read runtime implementation but not tests.",
                        }
                    }
                },
            ).to_payload()
            store.save_perception(str(perception["perception_id"]), perception)
            run_once(
                "Plan based on the current repo.",
                project_root=tmp_dir,
                workspace_context=workspace_context_from_perception(perception),
                workspace_perception=perception,
                full_loop_preview=False,
            )
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/workspace"))

            text = output.getvalue()
            self.assertIn("WORKSPACE PERCEPTION", text)
            self.assertIn(str(perception["perception_id"]), text)
            self.assertIn("spice/runtime/run_once.py", text)
            self.assertIn("run_once accepts workspace_context", text)
            self.assertIn("depth: normal", text)
            self.assertIn("rounds_used: 2", text)
            self.assertIn("tool_calls_executed: 4", text)
            self.assertIn("blocked_tool_calls: 1", text)
            self.assertIn("chars_used: 1200 / 500000", text)
            self.assertIn("exploration_status: partial", text)
            self.assertIn("evidence_sufficiency: partial", text)
            self.assertIn("Budget pressure events:", text)
            self.assertIn("Remaining gaps:", text)
            self.assertIn("Limitations:", text)

    def test_tui_shell_workspace_json_outputs_latest_workspace_perception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            store = LocalJsonStore.from_project_root(tmp_dir)
            perception = build_workspace_perception_artifact(
                workspace_root=tmp_dir,
                trigger="test",
                query="workspace debug json",
                files_read=[{"path": "spice/runtime/context_debug.py", "chars_read": 900}],
                files_skipped=[{"path": ".spice/state/state.json", "reason": "deny_dir"}],
                facts=[{"text": "context_debug renders workspace debug payloads."}],
                summary="Workspace debug is available.",
                budget={"tool_calls_used": 2, "total_chars_read": 900},
                exploration_status="complete",
                depth="normal",
                budget_used={
                    "rounds_used": 1,
                    "tool_calls_executed": 2,
                    "tool_calls_blocked": 0,
                    "chars_used": 900,
                    "total_char_budget": 500000,
                    "budget_pressure": "low",
                },
                metadata={
                    "loop": {
                        "sufficiency_check": {
                            "sufficient_evidence": True,
                            "can_answer_user_question": True,
                            "remaining_gaps": [],
                            "reason": "Read the relevant debug file.",
                        }
                    }
                },
            ).to_payload()
            store.save_perception(str(perception["perception_id"]), perception)
            run_once(
                "Plan based on workspace debug.",
                project_root=tmp_dir,
                workspace_context=workspace_context_from_perception(perception),
                workspace_perception=perception,
                full_loop_preview=False,
            )
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/workspace --json"))

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["schema_version"], "spice.workspace_debug.v1")
            self.assertEqual(payload["status"], "available")
            self.assertEqual(payload["perception_id"], perception["perception_id"])
            self.assertEqual(payload["workspace_context"]["source"], "workspace_perception")
            self.assertEqual(payload["workspace_perception"]["summary"], "Workspace debug is available.")
            self.assertEqual(payload["files_read"][0]["path"], "spice/runtime/context_debug.py")
            self.assertEqual(payload["files_skipped"][0]["reason"], "deny_dir")
            self.assertEqual(payload["depth"], "normal")
            self.assertEqual(payload["rounds_used"], 1)
            self.assertEqual(payload["tool_calls_executed"], 2)
            self.assertEqual(payload["blocked_tool_calls_count"], 0)
            self.assertEqual(payload["chars_used"], 900)
            self.assertEqual(payload["total_char_budget"], 500000)
            self.assertEqual(payload["exploration_status"], "complete")
            self.assertEqual(payload["evidence_sufficiency"], "sufficient")
            self.assertEqual(payload["sufficiency_check"]["reason"], "Read the relevant debug file.")

    def test_tui_shell_sources_command_renders_auditable_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            store = LocalJsonStore.from_project_root(tmp_dir)
            perception = build_workspace_perception_artifact(
                workspace_root=tmp_dir,
                trigger="test",
                query="source audit",
                tool_calls=[
                    {
                        "call_id": "tool.1",
                        "round_index": 1,
                        "tool": "search",
                        "args": {"pattern": "context_debug"},
                        "status": "executed",
                        "result": {
                            "ok": True,
                            "matches": [
                                {
                                    "path": "spice/runtime/context_debug.py",
                                    "line": 10,
                                    "text": "render_sources_debug_text renders sources.",
                                }
                            ],
                        },
                    }
                ],
                files_read=[{"path": "spice/runtime/context_debug.py", "chars_read": 900}],
                snippets=[
                    {
                        "path": "spice/runtime/context_debug.py",
                        "text": "def render_sources_debug_text(...): ...",
                        "source": "read_file",
                    }
                ],
                summary="Sources debug is available.",
                exploration_status="partial",
                depth="normal",
                budget_used={
                    "rounds_used": 2,
                    "tool_calls_executed": 3,
                    "tool_calls_blocked": 1,
                    "chars_used": 900,
                    "total_char_budget": 500000,
                    "budget_pressure": "medium",
                },
                budget_pressure_events=[
                    {
                        "round_index": 2,
                        "stage": "after_round",
                        "budget_pressure": "medium",
                    }
                ],
                limitations=["only sources debug file inspected"],
                metadata={
                    "loop": {
                        "sufficiency_check": {
                            "sufficient_evidence": False,
                            "can_answer_user_question": True,
                            "remaining_gaps": ["context command not inspected"],
                            "reason": "Source renderer was inspected.",
                        }
                    }
                },
            ).to_payload()
            store.save_perception(str(perception["perception_id"]), perception)
            run_once(
                "Plan based on source debug.",
                project_root=tmp_dir,
                workspace_context=workspace_context_from_perception(perception),
                workspace_perception=perception,
                full_loop_preview=False,
            )
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/sources"))

            text = output.getvalue()
            self.assertIn("SOURCES", text)
            self.assertIn(str(perception["perception_id"]), text)
            self.assertIn("evidence:", text)
            self.assertIn("workspace=", text)
            self.assertIn("Files read:", text)
            self.assertIn("Search matches:", text)
            self.assertIn("spice/runtime/context_debug.py", text)
            self.assertIn("- depth: normal", text)
            self.assertIn("- rounds_used: 2", text)
            self.assertIn("- tool_calls_executed: 3", text)
            self.assertIn("- blocked_tool_calls: 1", text)
            self.assertIn("- chars_used: 900 / 500000", text)
            self.assertIn("- exploration_status: partial", text)
            self.assertIn("- evidence_sufficiency: partial", text)
            self.assertIn("Budget pressure events:", text)
            self.assertIn("Remaining gaps:", text)
            self.assertIn("Limitations:", text)

    def test_tui_shell_sources_json_outputs_auditable_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            store = LocalJsonStore.from_project_root(tmp_dir)
            perception = build_workspace_perception_artifact(
                workspace_root=tmp_dir,
                trigger="test",
                query="sources json",
                files_read=[{"path": "spice/runtime/context_debug.py", "chars_read": 900}],
                summary="Sources json is available.",
                exploration_status="complete",
                depth="normal",
                budget_used={
                    "rounds_used": 1,
                    "tool_calls_executed": 1,
                    "tool_calls_blocked": 0,
                    "chars_used": 900,
                    "total_char_budget": 500000,
                },
                metadata={
                    "loop": {
                        "sufficiency_check": {
                            "sufficient_evidence": True,
                            "can_answer_user_question": True,
                            "remaining_gaps": [],
                            "reason": "Read source debug file.",
                        }
                    }
                },
            ).to_payload()
            store.save_perception(str(perception["perception_id"]), perception)
            run_once(
                "Plan based on sources json.",
                project_root=tmp_dir,
                workspace_context=workspace_context_from_perception(perception),
                workspace_perception=perception,
                full_loop_preview=False,
            )
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/sources --json"))

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["schema_version"], "spice.sources_debug.v1")
            self.assertEqual(payload["status"], "available")
            self.assertEqual(payload["workspace"]["perception_id"], perception["perception_id"])
            self.assertEqual(payload["workspace"]["files_read"][0]["path"], "spice/runtime/context_debug.py")
            self.assertEqual(payload["workspace"]["depth"], "normal")
            self.assertEqual(payload["workspace"]["rounds_used"], 1)
            self.assertEqual(payload["workspace"]["tool_calls_executed"], 1)
            self.assertEqual(payload["workspace"]["blocked_tool_calls_count"], 0)
            self.assertEqual(payload["workspace"]["chars_used"], 900)
            self.assertEqual(payload["workspace"]["total_char_budget"], 500000)
            self.assertEqual(payload["workspace"]["exploration_status"], "complete")
            self.assertEqual(payload["workspace"]["evidence_sufficiency"], "sufficient")
            self.assertTrue(payload["evidence_context"]["workspace"]["present"])
            self.assertEqual(payload["evidence_context"]["workspace"]["perception_id"], perception["perception_id"])
            self.assertFalse(payload["evidence_context"]["url"]["present"])
            self.assertFalse(payload["evidence_context"]["delegated"]["present"])

    def test_tui_shell_delegated_route_creates_investigation_consent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "hermes")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="new_decision",
                    action="new_intent",
                    text="Research the latest agent routing patterns.",
                    context_strategy="delegated",
                    needs_delegated_perception=True,
                    delegated_perception_query="latest agent routing patterns",
                    delegated_perception_reason="requires external web research",
                    suggested_capabilities=["web_research"],
                    source="llm",
                ),
            ):
                self.assertFalse(shell.handle_line("Research the latest agent routing patterns."))

            investigation_ids = shell._store().list_record_ids("investigations")
            self.assertEqual(len(investigation_ids), 1)
            consent = shell._store().load_investigation_consent(investigation_ids[0])
            self.assertEqual(consent["status"], INVESTIGATION_CONSENT_PENDING)
            self.assertEqual(consent["executor_id"], "hermes")
            self.assertEqual(consent["permission_mode"], "read_only")
            self.assertIn("write_file", consent["denied_actions"])
            self.assertEqual(shell._store().list_record_ids("approvals"), [])
            self.assertEqual(shell.result.run_ids, [])
            self.assertIsNotNone(shell.pending_investigation)
            self.assertEqual(shell._prompt_text(), "investigation> ")
            text = output.getvalue()
            self.assertIn("read-only investigation", text)
            self.assertIn("latest agent routing patterns", text)

    def test_tui_shell_investigation_yes_grants_without_execution_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "hermes")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="new_decision",
                    action="new_intent",
                    text="Ask Hermes to investigate current docs trends.",
                    context_strategy="delegated",
                    needs_delegated_perception=True,
                    delegated_perception_query="current docs trends",
                    delegated_perception_reason="requires external research",
                    suggested_capabilities=["web_research"],
                    source="llm",
                ),
            ):
                shell.handle_line("Ask Hermes to investigate current docs trends.")

            consent_id = shell._store().list_record_ids("investigations")[0]
            self.assertFalse(shell.handle_line("yes"))

            consent = shell._store().load_investigation_consent(consent_id)
            self.assertEqual(consent["status"], INVESTIGATION_CONSENT_GRANTED)
            self.assertIsNone(shell.pending_investigation)
            self.assertEqual(shell._prompt_text(), "spice> ")
            self.assertEqual(shell._store().list_record_ids("approvals"), [])
            self.assertIn("No files can be modified", output.getvalue())

    def test_tui_shell_investigation_picker_can_grant_consent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "hermes")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch.object(shell, "_decision_action_picker_available", return_value=True):
                with patch.object(shell, "_prompt_inline_choice", return_value="grant") as picker:
                    with patch(
                        "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                        return_value=SemanticRoute(
                            route="new_decision",
                            action="new_intent",
                            text="Ask Hermes to investigate current docs trends.",
                            context_strategy="delegated",
                            needs_delegated_perception=True,
                            delegated_perception_query="current docs trends",
                            delegated_perception_reason="requires external research",
                            suggested_capabilities=["web_research"],
                            source="llm",
                        ),
                    ):
                        self.assertFalse(shell.handle_line("Ask Hermes to investigate current docs trends."))

            consent_id = shell._store().list_record_ids("investigations")[0]
            consent = shell._store().load_investigation_consent(consent_id)
            self.assertEqual(consent["status"], INVESTIGATION_CONSENT_GRANTED)
            self.assertIsNone(shell.pending_investigation)
            self.assertEqual(shell._store().list_record_ids("approvals"), [])
            picker.assert_called_once()
            _, kwargs = picker.call_args
            self.assertEqual(kwargs["title"], "What would you like to do?")
            self.assertEqual(kwargs["prompt_label"], "investigation")
            self.assertIn("consent_id:", kwargs["footer"])

    def test_tui_shell_investigation_no_rejects_consent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "hermes")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="new_decision",
                    action="new_intent",
                    text="Investigate external launch examples.",
                    context_strategy="delegated",
                    needs_delegated_perception=True,
                    delegated_perception_query="external launch examples",
                    delegated_perception_reason="needs external investigation",
                    suggested_capabilities=["web_research"],
                    source="llm",
                ),
            ):
                shell.handle_line("Investigate external launch examples.")

            consent_id = shell._store().list_record_ids("investigations")[0]
            self.assertFalse(shell.handle_line("no"))

            consent = shell._store().load_investigation_consent(consent_id)
            self.assertEqual(consent["status"], INVESTIGATION_CONSENT_REJECTED)
            self.assertIsNone(shell.pending_investigation)
            self.assertEqual(shell._store().list_record_ids("approvals"), [])
            self.assertIn("Investigation consent rejected", output.getvalue())

    def test_tui_shell_investigate_command_shows_pending_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "hermes")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="new_decision",
                    action="new_intent",
                    text="Investigate external launch examples.",
                    context_strategy="delegated",
                    needs_delegated_perception=True,
                    delegated_perception_query="external launch examples",
                    suggested_capabilities=["web_research"],
                    source="llm",
                ),
            ):
                shell.handle_line("Investigate external launch examples.")

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line("/investigate details"))

            text = output.getvalue()
            self.assertIn("READ-ONLY INVESTIGATION CONSENT", text)
            self.assertIn("denied_actions", text)

    def test_tui_shell_deterministic_detail_commands_use_latest_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.handle_line("Review the repo and pick the safest next action.")

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line("/card"))
            self.assertFalse(shell.handle_line("/why"))
            self.assertFalse(shell.handle_line("/sim"))
            self.assertFalse(shell.handle_line("/details"))

            text = output.getvalue()
            self.assertIn("SPICE DECISION CARD", text)
            self.assertIn("WHY THIS DECISION", text)
            self.assertIn("SIMULATION SUMMARY", text)
            self.assertNotIn("ACTIVE DECISION FRAME", text)

    def test_tui_shell_details_command_does_not_trigger_streaming(self) -> None:
        class ForbiddenStreamWriter:
            def __init__(self, *args: object, **kwargs: object) -> None:
                raise AssertionError("/details should not use streaming")

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.handle_line("Review the repo and pick the safest next action.")
            output.seek(0)
            output.truncate(0)

            with patch("spice.runtime.tui.shell.TUIStreamWriter", ForbiddenStreamWriter):
                self.assertFalse(shell.handle_line("/details"))

            self.assertIn("SPICE DECISION CARD", output.getvalue())

    def test_tui_shell_local_read_commands_do_not_use_loading(self) -> None:
        class ForbiddenStatusFlow:
            def __init__(self, *args: object, **kwargs: object) -> None:
                raise AssertionError("local read commands should not show loading")

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.handle_line("Review the repo and pick the safest next action.")
            output.seek(0)
            output.truncate(0)

            with patch("spice.runtime.tui.shell.TUIStatusFlow", ForbiddenStatusFlow):
                for command in [
                    "/details",
                    "/card",
                    "/why",
                    "/sim",
                    "/json",
                    "/state",
                    "/help",
                    "/session",
                    "/stats",
                ]:
                    self.assertFalse(shell.handle_line(command), command)

            text = output.getvalue()
            self.assertIn("SPICE DECISION CARD", text)
            self.assertIn("WHY THIS DECISION", text)
            self.assertIn("SIMULATION SUMMARY", text)
            self.assertIn("WORLD STATE", text)
            self.assertIn("Commands:", text)
            self.assertIn("SESSION:", text)
            self.assertIn("SESSION STATS", text)

    def test_tui_shell_json_command_outputs_latest_run_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            setup_output = io.StringIO()
            setup_shell = self._plain_output_shell(tmp_dir, setup_output)
            setup_shell.handle_line("Review the repo and pick the safest next action.")

            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            self.assertFalse(shell.handle_line("/json"))

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["path_type"], "manual_intent_run_once")
            self.assertIn("compare_payload", payload)

    def test_tui_shell_execution_audit_commands_show_latest_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            approval_id = str(shell.pending_decision["approval_id"])
            self.assertFalse(shell.handle_line(f"/approve {approval_id}"))
            self.assertFalse(shell.handle_line(f"/execute {approval_id}"))
            outcome_id = shell.result.dry_run_outcome_ids[-1]

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line("/details"))
            text = output.getvalue()
            self.assertIn("SPICE DECISION CARD", text)
            self.assertNotIn("DRY-RUN EXECUTION", text)

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line("/json"))
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["path_type"], "manual_intent_run_once")
            self.assertIn("compare_payload", payload)

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line("/details execution"))
            text = output.getvalue()
            self.assertIn("DRY-RUN EXECUTION", text)
            self.assertIn("approval_id:", text)
            self.assertIn(outcome_id, text)

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line("/json execution"))
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["path_type"], "runtime_dry_run_outcome")
            self.assertEqual(payload["approval_id"], approval_id)
            self.assertEqual(payload["outcome_id"], outcome_id)
            execution_id = str(payload["execution_id"])

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line(f"/json {outcome_id}"))
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["outcome_id"], outcome_id)

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line(f"/details {outcome_id}"))
            self.assertIn("DRY-RUN EXECUTION", output.getvalue())

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line(f"/json {execution_id}"))
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["outcome_id"], outcome_id)

            output.seek(0)
            output.truncate(0)
            self.assertFalse(shell.handle_line(f"/details {execution_id}"))
            self.assertIn("DRY-RUN EXECUTION", output.getvalue())

    def test_tui_shell_perceive_command_updates_state_and_renders_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            source = Path(tmp_dir) / "status.txt"
            source.write_text("ci failed\n", encoding="utf-8")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line(f"/perceive --poll-url {source.as_uri()}"))

            text = output.getvalue()
            self.assertIn("PERCEPTION", text)
            self.assertIn("provider:", text)
            self.assertIn("poll", text)
            self.assertIn("Perception artifacts:", text)
            self.assertEqual(shell.result.turns, 1)

    def test_tui_shell_perceive_decide_on_change_records_triggered_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            source = Path(tmp_dir) / "status.txt"
            source.write_text("deployment needs review\n", encoding="utf-8")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line(f"/perceive --poll-url {source.as_uri()} --decide-on-change"))

            text = output.getvalue()
            self.assertIn("decision_triggered:", text)
            self.assertIn("approval_id:", text)
            self.assertEqual(len(shell.result.run_ids), 1)
            self.assertEqual(shell.result.turns, 1)

    def test_tui_shell_perceive_open_chronicle_uses_provider_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            with patch(
                "spice.runtime.tui.shell.perceive_once",
                return_value=SimpleNamespace(
                    artifact={
                        "provider": "open_chronicle",
                        "observation_count": 2,
                        "changed_count": 2,
                        "deduped_count": 0,
                        "decision_triggered": False,
                        "executor_called": False,
                        "sdep_request_sent": False,
                        "observations": [],
                    },
                    perception_path=Path(tmp_dir) / ".spice" / "perceptions" / "p.json",
                    state_path=Path(tmp_dir) / ".spice" / "state" / "state.json",
                ),
            ) as perceive:
                self.assertFalse(
                    shell.handle_line(
                        "/perceive --provider open_chronicle "
                        "--openchronicle-mcp-url http://127.0.0.1:8742/mcp "
                        "--openchronicle-since-minutes 10 "
                        "--openchronicle-context-limit 3"
                    )
                )

            kwargs = perceive.call_args.kwargs
            self.assertEqual(kwargs["provider"], "open_chronicle")
            self.assertEqual(kwargs["openchronicle_mcp_url"], "http://127.0.0.1:8742/mcp")
            self.assertEqual(kwargs["openchronicle_since_minutes"], 10)
            self.assertEqual(kwargs["openchronicle_context_limit"], 3)
            self.assertIn("PERCEPTION", output.getvalue())

    def test_tui_shell_approvals_and_session_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            self.assertFalse(shell.handle_line("/approvals"))
            self.assertFalse(shell.handle_line("/session"))
            self.assertFalse(shell.handle_line("/timeline"))
            self.assertFalse(shell.handle_line("/stats"))

            text = output.getvalue()
            self.assertIn("APPROVALS", text)
            self.assertIn("SESSION:", text)
            self.assertIn("TIMELINE:", text)
            self.assertIn("SESSION STATS", text)

    def test_tui_shell_pending_without_pending_approvals_reports_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/pending"))

            self.assertIn("No pending approvals.", output.getvalue())

    def test_tui_shell_pending_single_approval_opens_action_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            approval_id = str(shell.pending_decision["approval_id"])
            shell.pending_decision = None

            with patch.object(shell, "_decision_action_picker_available", return_value=True):
                with patch.object(shell, "_prompt_decision_action", return_value="approve") as picker:
                    self.assertFalse(shell.handle_line("/pending"))

            text = output.getvalue()
            self.assertIn(f"Pending approval: {approval_id}", text)
            self.assertIn("APPROVAL APPROVED", text)
            picker.assert_called_once()

    def test_tui_shell_pending_approve_execute_runs_configured_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            approval_id = str(shell.pending_decision["approval_id"])
            shell.pending_decision = None

            with patch.object(shell, "_decision_action_picker_available", return_value=True):
                with patch.object(shell, "_prompt_decision_action", return_value="approve_execute"):
                    self.assertFalse(shell.handle_line("/pending"))

            text = output.getvalue()
            self.assertIn("APPROVAL APPROVED", text)
            self.assertNotIn("EXECUTION COMPLETE", text)
            self.assertIn("dry_run finished the handoff", text)
            self.assertIn(approval_id, shell.result.approved_ids)
            self.assertGreaterEqual(len(shell.result.dry_run_outcome_ids), 1)

    def test_tui_shell_approval_command_opens_specific_approval_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            approval_id = str(shell.pending_decision["approval_id"])
            shell.pending_decision = None

            with patch.object(shell, "_decision_action_picker_available", return_value=True):
                with patch.object(shell, "_prompt_decision_action", side_effect=["details", "approve"]) as picker:
                    self.assertFalse(shell.handle_line(f"/approval {approval_id}"))

            text = output.getvalue()
            self.assertIn("SPICE APPROVAL", text)
            self.assertIn("APPROVAL APPROVED", text)
            self.assertEqual(picker.call_count, 2)

    def test_tui_shell_approval_command_rejects_non_pending_approval_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            approval_id = str(shell.pending_decision["approval_id"])
            shell.handle_line("a")

            self.assertFalse(shell.handle_line(f"/approval {approval_id}"))

            text = output.getvalue()
            self.assertIn("is not pending", text)
            self.assertIn("Current status: approved", text)

    def test_tui_shell_pending_multiple_approvals_selects_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            first_id = str(shell.pending_decision["approval_id"])
            shell.handle_line("/act Review the pending PR.")
            second_id = str(shell.pending_decision["approval_id"])
            shell.pending_decision = None

            with patch.object(shell, "_choose_pending_approval", return_value=second_id) as choose:
                with patch.object(shell, "_approval_action_menu") as menu:
                    self.assertFalse(shell.handle_line("/pending"))

            self.assertNotEqual(first_id, second_id)
            choose.assert_called_once()
            menu.assert_called_once_with(second_id)

    def test_tui_shell_continuation_selects_visible_decision_card_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "Compare these 3 next steps for Spice: add LLM retry, polish Decision Card, "
                "add JSON output. Which should we do first?"
            )
            before = shell._store().load_state()
            before_frame = before["world_state"]["domain_state"]["general_decision"]["metadata"][
                "active_decision_frame"
            ]
            visible_b = before_frame["candidates"][1]

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="follow_up",
                    action="choose_option",
                    is_continuation=True,
                    candidate_id=str(visible_b["candidate_id"]),
                    label="B",
                    text="B",
                    source="llm",
                ),
            ):
                self.assertFalse(shell.handle_line("B"))

            after = shell._store().load_state()
            after_frame = after["world_state"]["domain_state"]["general_decision"]["metadata"][
                "active_decision_frame"
            ]
            self.assertEqual(after_frame["selected_candidate_id"], visible_b["candidate_id"])
            self.assertEqual(after_frame["selected"]["label"], "B")
            text = output.getvalue()
            self.assertIn("Selected B", text)
            self.assertIn("advisory-only", text)
            self.assertIn("/act <specific executable task>", text)
            self.assertNotIn("execute selected", text)

    def test_tui_shell_continuation_selects_executable_option_shows_execute_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            _install_execution_ready_frame(shell)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="follow_up",
                    action="choose_option",
                    is_continuation=True,
                    candidate_id="candidate.b",
                    label="B",
                    text="choose B",
                    source="llm",
                ),
            ):
                self.assertFalse(shell.handle_line("choose B"))

            text = output.getvalue()
            self.assertIn("Selected B", text)
            self.assertIn("execute selected", text)
            self.assertNotIn("advisory-only", text)

    def test_tui_shell_continuation_execute_selected_blocks_advisory_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "Compare these 3 next steps for Spice: add LLM retry, polish Decision Card, "
                "add JSON output. Which should we do first?"
            )
            frame = shell._active_decision_frame()
            candidate_b = next(item for item in frame["candidates"] if item.get("label") == "B")
            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="follow_up",
                    action="choose_option",
                    is_continuation=True,
                    candidate_id=str(candidate_b["candidate_id"]),
                    label="B",
                    text="choose B",
                    source="llm",
                ),
            ):
                shell.handle_line("choose B")

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="execution_request",
                    action="execute_selected",
                    is_continuation=True,
                    candidate_id=str(candidate_b["candidate_id"]),
                    label="B",
                    text="execute selected",
                    source="llm",
                ),
            ):
                with patch.object(shell, "_run_intent") as run_intent:
                    self.assertFalse(shell.handle_line("execute selected"))

            run_intent.assert_not_called()
            self.assertIn("advisory-only", output.getvalue())

    def test_tui_shell_why_not_followup_reads_previous_decision_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "Compare these 3 next steps for Spice: add LLM retry, polish Decision Card, "
                "add JSON output. Which should we do first?"
            )
            run_ids_before = list(shell.result.run_ids)

            frame = shell._active_decision_frame()
            candidate_b = next(item for item in frame["candidates"] if item.get("label") == "B")
            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="follow_up",
                    action="explain_why_not",
                    is_continuation=True,
                    candidate_id=str(candidate_b["candidate_id"]),
                    label="B",
                    text="why not B?",
                    source="llm",
                ),
            ):
                with patch.object(shell, "_run_intent") as run_intent:
                    self.assertFalse(shell.handle_line("why not B?"))

            run_intent.assert_not_called()
            self.assertEqual(shell.result.run_ids, run_ids_before)
            text = output.getvalue()
            self.assertIn("I did not pick", text)
            self.assertIn("Next:", text)
            session = shell._store().load_session(shell.result.session_id)
            latest_turn_id = session["conversation_turn_ids"][-1]
            turn = shell._store().load_conversation_turn(latest_turn_id)
            frame = shell._active_decision_frame()
            self.assertEqual(turn["route"], "follow_up")
            self.assertEqual(turn["source_decision_id"], frame["decision_id"])
            self.assertEqual(turn["metadata"]["follow_up_action"], "explain_why_not")
            self.assertEqual(turn["metadata"]["follow_up_response"]["action"], "explain_why_not")
            evolution_records = load_workspace_memory_provider(tmp_dir).query(
                namespace="general.evolution",
                limit=-1,
            )
            follow_up_records = [
                record
                for record in evolution_records
                if record.get("turn_id") == latest_turn_id
            ]
            self.assertEqual(len(follow_up_records), 1)
            self.assertEqual(follow_up_records[0]["route"], "follow_up")
            self.assertEqual(follow_up_records[0]["follow_up_type"], "explain_why_not")
            self.assertEqual(follow_up_records[0]["user_input"], "why not B?")

    def test_tui_shell_why_not_followup_loading_explains_tradeoff(self) -> None:
        events: list[tuple[str, str, str]] = []

        class FakeStatusFlow:
            def __init__(self, *, console: object, title: str, label: str, detail: str = "") -> None:
                self.label = label
                self.detail = detail
                events.append(("init", label, detail))

            def __enter__(self) -> "FakeStatusFlow":
                events.append(("enter", self.label, self.detail))
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                events.append(("exit", "", ""))

            def update(self, label: str, detail: str = "") -> None:
                events.append(("update", label, detail))

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("finish", label, detail))

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                pass

            def start(self) -> "FakeStreamWriter":
                return self

            def status(self, label: str, detail: str = "") -> None:
                events.append(("stream_status", label, detail))

            def write(self, text: str) -> None:
                pass

            def write_block(self, text: str) -> None:
                pass

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("stream_finish", label, detail))

            def fail(self, fallback_text: str = "") -> None:
                events.append(("stream_fail", fallback_text, ""))

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.handle_line(
                "Compare these 3 next steps for Spice: add LLM retry, polish Decision Card, "
                "add JSON output. Which should we do first?"
            )
            frame = shell._active_decision_frame()
            candidate_b = next(item for item in frame["candidates"] if item.get("label") == "B")
            events.clear()

            with patch("spice.runtime.tui.shell.TUIStatusFlow", FakeStatusFlow):
                with patch("spice.runtime.tui.shell.TUIStreamWriter", FakeStreamWriter):
                    with patch(
                        "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                        return_value=SemanticRoute(
                            route="follow_up",
                            action="explain_why_not",
                            is_continuation=True,
                            candidate_id=str(candidate_b["candidate_id"]),
                            label="B",
                            text="why not B?",
                            source="llm",
                        ),
                    ):
                        should_exit = shell.handle_line("why not B?")

        self.assertFalse(should_exit)
        self.assertEqual(events[0][1], "Reading the active decision...")
        self.assertIn(("update", "Understanding your follow-up...", "deterministic runtime"), events)
        self.assertIn(("stream_status", "Explaining the tradeoff...", "deterministic runtime"), events)

    def test_tui_shell_plan_followup_reads_candidate_without_new_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "Compare these 3 next steps for Spice: add LLM retry, polish Decision Card, "
                "add JSON output. Which should we do first?"
            )
            run_ids_before = list(shell.result.run_ids)

            frame = shell._active_decision_frame()
            candidate_a = next(item for item in frame["candidates"] if item.get("label") == "A")
            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="follow_up",
                    action="plan_candidate",
                    is_continuation=True,
                    candidate_id=str(candidate_a["candidate_id"]),
                    label="A",
                    text="give me A's plan",
                    source="llm",
                ),
            ):
                with patch.object(shell, "_run_intent") as run_intent:
                    self.assertFalse(shell.handle_line("give me A's plan"))

            run_intent.assert_not_called()
            self.assertEqual(shell.result.run_ids, run_ids_before)
            text = output.getvalue()
            self.assertIn("Plan for", text)
            self.assertIn("Goal:", text)
            session = shell._store().load_session(shell.result.session_id)
            turn = shell._store().load_conversation_turn(session["conversation_turn_ids"][-1])
            self.assertEqual(turn["route"], "follow_up")
            self.assertEqual(turn["source_decision_id"], frame["decision_id"])
            self.assertEqual(turn["source_candidate_id"], candidate_a["candidate_id"])
            self.assertEqual(turn["metadata"]["follow_up_action"], "plan_candidate")
            evolution_records = load_workspace_memory_provider(tmp_dir).query(
                namespace="general.evolution",
                limit=-1,
            )
            follow_up_records = [
                record
                for record in evolution_records
                if record.get("turn_id") == turn["turn_id"]
            ]
            self.assertEqual(len(follow_up_records), 1)
            self.assertEqual(follow_up_records[0]["follow_up_type"], "plan_candidate")
            self.assertEqual(follow_up_records[0]["user_input"], "give me A's plan")

    def test_tui_shell_plan_followup_loading_drafts_plan(self) -> None:
        events: list[tuple[str, str, str]] = []

        class FakeStatusFlow:
            def __init__(self, *, console: object, title: str, label: str, detail: str = "") -> None:
                events.append(("init", label, detail))

            def __enter__(self) -> "FakeStatusFlow":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

            def update(self, label: str, detail: str = "") -> None:
                events.append(("update", label, detail))

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("finish", label, detail))

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                pass

            def start(self) -> "FakeStreamWriter":
                return self

            def status(self, label: str, detail: str = "") -> None:
                events.append(("stream_status", label, detail))

            def write(self, text: str) -> None:
                pass

            def write_block(self, text: str) -> None:
                pass

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("stream_finish", label, detail))

            def fail(self, fallback_text: str = "") -> None:
                events.append(("stream_fail", fallback_text, ""))

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.handle_line(
                "Compare these 3 next steps for Spice: add LLM retry, polish Decision Card, "
                "add JSON output. Which should we do first?"
            )
            frame = shell._active_decision_frame()
            candidate_a = next(item for item in frame["candidates"] if item.get("label") == "A")
            events.clear()

            with patch("spice.runtime.tui.shell.TUIStatusFlow", FakeStatusFlow):
                with patch(
                    "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                    return_value=SemanticRoute(
                        route="follow_up",
                        action="plan_candidate",
                        is_continuation=True,
                        candidate_id=str(candidate_a["candidate_id"]),
                        label="A",
                        text="give me A's plan",
                        source="llm",
                    ),
                ):
                    should_exit = shell.handle_line("give me A's plan")

        self.assertFalse(should_exit)
        self.assertIn(("init", "Drafting the plan...", ""), events)

    def test_tui_shell_general_followup_answers_without_new_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "Compare state-as-context, proactive perception, and executor handoff."
            )
            run_ids_before = list(shell.result.run_ids)
            frame = shell._active_decision_frame()

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="follow_up",
                    action="answer_from_decision",
                    is_continuation=True,
                    candidate_id=str(frame.get("selected_candidate_id")),
                    text="两周内怎么做？",
                ),
            ):
                with patch.object(shell, "_run_intent") as run_intent:
                    self.assertFalse(shell.handle_line("两周内怎么做？"))

            run_intent.assert_not_called()
            self.assertEqual(shell.result.run_ids, run_ids_before)
            self.assertIn("Based on the current Decision Card", output.getvalue())
            session = shell._store().load_session(shell.result.session_id)
            turn = shell._store().load_conversation_turn(session["conversation_turn_ids"][-1])
            self.assertEqual(turn["route"], "follow_up")
            self.assertEqual(turn["metadata"]["follow_up_action"], "answer_from_decision")
            streaming = turn["metadata"]["follow_up_response"]["streaming"]
            self.assertEqual(streaming["mode"], "block_display")
            self.assertGreaterEqual(streaming["chunk_count"], 1)
            self.assertEqual(streaming["source"], "validated_composer_result")
            composer_streaming = turn["metadata"]["follow_up_response"]["evidence"]["composer_result"]["metadata"]["streaming"]
            self.assertEqual(composer_streaming, streaming)

    def test_tui_shell_general_followup_loading_composes_answer(self) -> None:
        events: list[tuple[str, str, str]] = []

        class FakeStatusFlow:
            def __init__(self, *, console: object, title: str, label: str, detail: str = "") -> None:
                events.append(("init", label, detail))

            def __enter__(self) -> "FakeStatusFlow":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

            def update(self, label: str, detail: str = "") -> None:
                events.append(("update", label, detail))

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("finish", label, detail))

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                pass

            def start(self) -> "FakeStreamWriter":
                return self

            def status(self, label: str, detail: str = "") -> None:
                events.append(("stream_status", label, detail))

            def write(self, text: str) -> None:
                pass

            def write_block(self, text: str) -> None:
                pass

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("stream_finish", label, detail))

            def fail(self, fallback_text: str = "") -> None:
                events.append(("stream_fail", fallback_text, ""))

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            shell.handle_line("Compare state-as-context, proactive perception, and executor handoff.")
            frame = shell._active_decision_frame()
            events.clear()

            with patch("spice.runtime.tui.shell.TUIStatusFlow", FakeStatusFlow):
                with patch("spice.runtime.tui.shell.TUIStreamWriter", FakeStreamWriter):
                    with patch(
                        "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                        return_value=SemanticRoute(
                            route="follow_up",
                            action="answer_from_decision",
                            is_continuation=True,
                            candidate_id=str(frame.get("selected_candidate_id")),
                            text="两周内怎么做？",
                        ),
                    ):
                        should_exit = shell.handle_line("两周内怎么做？")

        self.assertFalse(should_exit)
        self.assertIn(("stream_status", "Composing answer...", "deterministic runtime"), events)

    def test_tui_shell_followup_answers_use_stream_writer(self) -> None:
        stream_blocks: list[str] = []
        finish_count = 0

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                pass

            def start(self) -> "FakeStreamWriter":
                return self

            def write_block(self, text: str) -> None:
                stream_blocks.append(text)

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                nonlocal finish_count
                finish_count += 1

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            resolution = SimpleNamespace(
                text="follow-up",
                candidate_id="candidate.a",
                action="answer_from_decision",
            )

            with patch("spice.runtime.tui.shell.TUIStreamWriter", FakeStreamWriter):
                with patch.object(shell, "_load_run_for_command", return_value={"run_id": "run.test"}):
                    with patch(
                        "spice.runtime.tui.shell.answer_why_not_candidate",
                        return_value=SimpleNamespace(rendered_text="Why-not response."),
                    ):
                        shell._answer_why_not_follow_up(resolution)
                    with patch(
                        "spice.runtime.tui.shell.answer_candidate_plan",
                        return_value=SimpleNamespace(rendered_text="Plan response."),
                    ):
                        shell._answer_plan_follow_up(resolution)
                    with patch(
                        "spice.runtime.tui.shell.answer_general_follow_up",
                        return_value=SimpleNamespace(rendered_text="General response."),
                    ):
                        shell._answer_general_follow_up(resolution)

        self.assertIn("Why-not response.", stream_blocks)
        self.assertIn("Plan response.", stream_blocks)
        self.assertIn("General response.", stream_blocks)
        self.assertEqual(finish_count, 3)

    def test_tui_shell_compare_alternative_followup_answers_visible_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "Compare state-as-context, proactive perception, and executor handoff."
            )
            frame = shell._active_decision_frame()
            candidate_b = next(item for item in frame["candidates"] if item.get("label") == "B")

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="follow_up",
                    action="compare_alternative",
                    is_continuation=True,
                    candidate_id=str(candidate_b["candidate_id"]),
                    text="那 B 有没有可能更适合？",
                ),
            ):
                with patch.object(shell, "_run_intent") as run_intent:
                    self.assertFalse(shell.handle_line("那 B 有没有可能更适合？"))

            run_intent.assert_not_called()
            self.assertIn("could be better", output.getvalue())
            session = shell._store().load_session(shell.result.session_id)
            turn = shell._store().load_conversation_turn(session["conversation_turn_ids"][-1])
            self.assertEqual(turn["source_candidate_id"], candidate_b["candidate_id"])
            self.assertEqual(turn["metadata"]["follow_up_action"], "compare_alternative")

    def test_tui_shell_uses_llm_semantic_route_but_guardrail_blocks_advisory_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "Compare these 3 next steps for Spice: add LLM retry, polish Decision Card, "
                "add JSON output. Which should we do first?"
            )

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="execution_request",
                    action="execute_selected",
                    is_continuation=True,
                    candidate_id=str(
                        shell._active_decision_frame().get("selected_candidate_id")
                    ),
                    text="那就去干吧",
                ),
            ) as resolver:
                with patch.object(shell, "_run_intent") as run_intent:
                    self.assertFalse(shell.handle_line("那就去干吧"))

            resolver.assert_called_once()
            run_intent.assert_not_called()
            self.assertIn("advisory-only", output.getvalue())

    def test_tui_execute_command_does_not_create_approval_for_advisory_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "Compare these 3 next steps for Spice: add LLM retry, polish Decision Card, "
                "add JSON output. Which should we do first?"
            )
            active_frame = shell._active_decision_frame()
            self.assertFalse(active_frame.get("approval_id"))
            self.assertEqual(shell._store().list_record_ids("approvals"), [])

            self.assertFalse(shell.handle_line("/execute"))

            self.assertEqual(shell._store().list_record_ids("approvals"), [])
            self.assertIsNone(shell.pending_decision)
            text = output.getvalue()
            self.assertIn("not executable", text)
            self.assertIn("advisory-only", text)

    def test_tui_shell_natural_execution_opens_pending_approval_for_executable_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            _install_execution_ready_frame(shell)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="execution_request",
                    action="execute_selected",
                    is_continuation=True,
                    candidate_id="candidate.a",
                    label="A",
                    text="start it",
                    source="llm",
                ),
            ):
                with patch.object(shell, "_run_intent") as run_intent:
                    self.assertFalse(shell.handle_line("start it"))

            run_intent.assert_not_called()
            approval_ids = shell._store().list_record_ids("approvals")
            self.assertEqual(len(approval_ids), 1)
            approval = load_approval(shell._store(), approval_ids[0])
            self.assertEqual(approval.status, "pending")
            self.assertEqual(approval.candidate_id, "candidate.a")
            self.assertEqual(shell.pending_decision["approval_id"], approval.approval_id)
            frame = shell._active_decision_frame()
            self.assertEqual(frame["approval_id"], approval.approval_id)
            self.assertEqual(frame["status"], "approval_pending")
            text = output.getvalue()
            self.assertIn("pending approval", text)
            self.assertIn("workspace_write", text)
            session = shell._store().load_session(shell.result.session_id)
            self.assertIn(approval.approval_id, session["pending_approval_ids"])
            turn = shell._store().load_conversation_turn(session["conversation_turn_ids"][-1])
            self.assertEqual(turn["route"], "execution_request")
            self.assertEqual(turn["source_approval_id"], approval.approval_id)
            evolution_records = load_workspace_memory_provider(tmp_dir).query(
                namespace="general.evolution",
                limit=-1,
            )
            execution_request = [
                record
                for record in evolution_records
                if record.get("approval_id") == approval.approval_id
                and record.get("follow_up_type") == "execution_request"
            ]
            self.assertEqual(len(execution_request), 1)
            self.assertEqual(execution_request[0]["route"], "execution_request")
            self.assertEqual(execution_request[0]["candidate_id"], "candidate.a")

    def test_tui_shell_natural_execution_uses_approval_creation_loading(self) -> None:
        events: list[tuple[str, str, str]] = []

        class FakeStatusFlow:
            def __init__(self, *, console: object, title: str, label: str, detail: str = "") -> None:
                events.append(("init", label, detail))

            def __enter__(self) -> "FakeStatusFlow":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

            def update(self, label: str, detail: str = "") -> None:
                events.append(("update", label, detail))

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("finish", label, detail))

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            _install_execution_ready_frame(shell)

            with patch("spice.runtime.tui.shell.TUIStatusFlow", FakeStatusFlow):
                with patch(
                    "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                    return_value=SemanticRoute(
                        route="execution_request",
                        action="execute_selected",
                        is_continuation=True,
                        candidate_id="candidate.a",
                        label="A",
                        text="start it",
                        source="llm",
                    ),
                ):
                    with patch.object(shell, "_execute_configured") as execute_configured:
                        self.assertFalse(shell.handle_line("start it"))

            execute_configured.assert_not_called()
            approval_ids = shell._store().list_record_ids("approvals")
            self.assertEqual(len(approval_ids), 1)
            approval = load_approval(shell._store(), approval_ids[0])
            self.assertEqual(approval.status, "pending")
            self.assertEqual(shell.result.dry_run_outcome_ids, [])

        self.assertIn(("init", "Reading the selected option...", ""), events)
        self.assertIn(("update", "Checking executor and permissions...", ""), events)
        self.assertIn(("update", "Creating pending approval...", ""), events)
        self.assertIn(("finish", "Approval ready.", ""), events)
        self.assertLess(
            events.index(("init", "Reading the selected option...", "")),
            events.index(("update", "Checking executor and permissions...", "")),
        )
        self.assertLess(
            events.index(("update", "Checking executor and permissions...", "")),
            events.index(("update", "Creating pending approval...", "")),
        )
        self.assertLess(
            events.index(("update", "Creating pending approval...", "")),
            events.index(("finish", "Approval ready.", "")),
        )

    def test_tui_shell_chinese_natural_execution_creates_approval_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            _install_execution_ready_frame(shell)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="execution_request",
                    action="execute_selected",
                    is_continuation=True,
                    candidate_id="candidate.a",
                    label="A",
                    text="就按这个做",
                    source="llm",
                ),
            ):
                with patch.object(shell, "_run_intent") as run_intent:
                    with patch.object(shell, "_execute_configured") as execute_configured:
                        self.assertFalse(shell.handle_line("就按这个做"))

            run_intent.assert_not_called()
            execute_configured.assert_not_called()
            approval_ids = shell._store().list_record_ids("approvals")
            self.assertEqual(len(approval_ids), 1)
            approval = load_approval(shell._store(), approval_ids[0])
            self.assertEqual(approval.status, "pending")
            self.assertEqual(approval.candidate_id, "candidate.a")
            self.assertEqual(shell.result.dry_run_outcome_ids, [])
            self.assertIn("pending approval", output.getvalue())

    def test_tui_shell_targeted_execution_selects_candidate_before_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            _install_execution_ready_frame(shell)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="execution_request",
                    action="execute_selected",
                    is_continuation=True,
                    candidate_id="candidate.b",
                    label="B",
                    text="execute B",
                    source="llm",
                ),
            ):
                self.assertFalse(shell.handle_line("execute B"))

            approval_ids = shell._store().list_record_ids("approvals")
            self.assertEqual(len(approval_ids), 1)
            approval = load_approval(shell._store(), approval_ids[0])
            self.assertEqual(approval.candidate_id, "candidate.b")
            frame = shell._active_decision_frame()
            self.assertEqual(frame["selected_candidate_id"], "candidate.b")
            self.assertEqual(frame["selected"]["label"], "B")
            self.assertIn("Execute B", output.getvalue())

    def test_tui_shell_english_natural_execution_blocks_advisory_candidate(self) -> None:
        self._assert_natural_execution_followup_blocks_advisory("implement this")

    def test_tui_shell_chinese_natural_execution_blocks_advisory_candidate(self) -> None:
        self._assert_natural_execution_followup_blocks_advisory("那就开始做吧")

    def test_tui_shell_continuation_refines_active_decision_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("Review the repo and pick the safest next action.")

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="follow_up",
                    action="refine_decision",
                    is_continuation=True,
                    candidate_id=str(shell._active_decision_frame().get("selected_candidate_id")),
                    text="to lower risk",
                    source="llm",
                ),
            ):
                with patch.object(shell, "_refine_decision") as refine:
                    self.assertFalse(shell.handle_line("refine that to lower risk"))

            refine.assert_called_once_with("to lower risk")

    def test_tui_shell_pending_decision_accepts_execute_selected_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line("/act Fix the failing test.")
            approval_id = str(shell.pending_decision["approval_id"])
            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="execution_request",
                    action="approve_execute",
                    is_continuation=True,
                    candidate_id=str(shell._active_decision_frame().get("selected_candidate_id")),
                    text="execute selected",
                    source="llm",
                ),
            ):
                self.assertFalse(shell.handle_line("execute selected"))

            text = output.getvalue()
            self.assertIn("APPROVAL APPROVED", text)
            self.assertNotIn("EXECUTION COMPLETE", text)
            self.assertIn("dry_run finished the handoff", text)
            self.assertIn(approval_id, shell.result.approved_ids)
            self.assertIsNone(shell.pending_decision)

    def test_tui_execute_configured_renders_natural_execution_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            execution = SimpleNamespace(
                artifact={
                    "executor_provider": "dry_run",
                    "approval_id": "approval.test",
                    "decision_id": "decision.test",
                    "trace_ref": "trace.test",
                    "candidate_id": "candidate.test",
                    "execution_id": "execution.test",
                    "request_id": "request.test",
                    "outcome_id": "outcome.test",
                    "executor_id": "spice.general_executor",
                    "skill_id": "runtime.intent.execute",
                    "context_pack_id": "context.test",
                    "sdep_request_sent": False,
                    "executor_called": False,
                    "real_executor_called": False,
                    "executed": False,
                    "protocol_status": "success",
                    "task_status": "success",
                    "state_updated": True,
                    "persisted": True,
                    "state_after_ref": ".spice/state/state.json#after:test",
                },
                rendered_text="SPICE DRY-RUN EXECUTION\nplain executor output",
            )

            with patch("spice.runtime.tui.shell.execute_dry_run_approval", return_value=execution):
                self.assertFalse(shell.handle_line("/execute approval.test"))

            text = output.getvalue()
            self.assertNotIn("EXECUTION COMPLETE", text)
            self.assertIn("dry_run finished the handoff", text)
            self.assertIn("task_status: success", text)
            self.assertIn("approval.test", text)
            self.assertNotIn("plain executor output", text)
            session = shell._store().load_session(shell.result.session_id)
            turn_id = session["conversation_turn_ids"][-1]
            turn = shell._store().load_conversation_turn(turn_id)
            self.assertEqual(turn["route"], "execution_request")
            self.assertEqual(turn["source_approval_id"], "approval.test")
            self.assertEqual(turn["source_decision_id"], "decision.test")
            self.assertEqual(turn["source_candidate_id"], "candidate.test")
            self.assertEqual(turn["source_execution_id"], "execution.test")
            self.assertEqual(turn["source_outcome_id"], "outcome.test")
            self.assertIn("dry_run finished the handoff", turn["metadata"]["execution_response"]["response_text"])
            self.assertEqual(turn["metadata"]["execution_result"]["task_status"], "success")
            context = build_composer_context_payload(
                project_root=tmp_dir,
                session_id=shell.result.session_id,
            )
            latest_turn = context["recent_conversation_turns"][-1]
            self.assertEqual(latest_turn["route"], "execution_request")
            self.assertEqual(latest_turn["source_outcome_id"], "outcome.test")
            self.assertIn("dry_run finished the handoff", latest_turn["response_summary"])

    def test_tui_execution_composer_fallback_is_recorded_without_debug_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            execution = SimpleNamespace(
                artifact={
                    "executor_provider": "dry_run",
                    "approval_id": "approval.test",
                    "decision_id": "decision.test",
                    "trace_ref": "trace.test",
                    "candidate_id": "candidate.test",
                    "execution_id": "execution.test",
                    "request_id": "request.test",
                    "outcome_id": "outcome.test",
                    "executor_id": "spice.general_executor",
                    "protocol_status": "success",
                    "task_status": "success",
                    "state_updated": True,
                    "persisted": True,
                    "memory_writeback": {"status": "written"},
                },
                rendered_text="SPICE DRY-RUN EXECUTION\nplain executor output",
            )
            composed = ComposerResult(
                enabled=True,
                status="fallback",
                response_text="dry_run finished the handoff.",
                deterministic_text="dry_run finished the handoff.",
                composer_kind="execution_response",
                model_provider="fake",
                model_id="fake-model",
                raw_output='{"not_response": true}',
                fallback_reason="invalid_composed_response",
                error="missing response text",
            )

            with patch("spice.runtime.tui.shell.execute_dry_run_approval", return_value=execution):
                with patch(
                    "spice.runtime.tui.shell.compose_execution_response_from_runtime_config",
                    return_value=composed,
                ):
                    self.assertFalse(shell.handle_line("/execute approval.test"))

            text = output.getvalue()
            self.assertIn("dry_run finished the handoff.", text)
            self.assertNotIn("invalid_composed_response", text)
            self.assertNotIn("not_response", text)
            session = shell._store().load_session(shell.result.session_id)
            turn = shell._store().load_conversation_turn(session["conversation_turn_ids"][-1])
            composer_result = turn["metadata"]["execution_response"]["composer_result"]
            self.assertEqual(composer_result["status"], "fallback")
            self.assertEqual(composer_result["raw_output"], '{"not_response": true}')
            self.assertEqual(composer_result["fallback_reason"], "invalid_composed_response")
            streaming = composer_result["metadata"]["streaming"]
            self.assertEqual(streaming["mode"], "block_display")
            self.assertEqual(streaming["chunk_count"], 1)
            self.assertEqual(streaming["source"], "validated_composer_result")

    def test_tui_execute_configured_uses_truthful_executor_loading(self) -> None:
        events: list[tuple[str, str, str]] = []
        stream_blocks: list[str] = []

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                self.failed = False

            def start(self) -> "FakeStreamWriter":
                return self

            def status(self, label: str, detail: str = "") -> None:
                events.append(("status", label, detail))

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("finish", label, detail))

            def write_block(self, text: str) -> None:
                stream_blocks.append(text)

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            execution = SimpleNamespace(
                artifact={
                    "executor_provider": "dry_run",
                    "approval_id": "approval.test",
                    "decision_id": "decision.test",
                    "trace_ref": "trace.test",
                    "candidate_id": "candidate.test",
                    "execution_id": "execution.test",
                    "request_id": "request.test",
                    "outcome_id": "outcome.test",
                    "executor_id": "spice.general_executor",
                    "skill_id": "runtime.intent.execute",
                    "context_pack_id": "context.test",
                    "sdep_request_sent": False,
                    "executor_called": False,
                    "real_executor_called": False,
                    "executed": False,
                    "protocol_status": "success",
                    "task_status": "success",
                    "state_updated": True,
                    "persisted": True,
                    "state_after_ref": ".spice/state/state.json#after:test",
                },
                rendered_text="SPICE DRY-RUN EXECUTION\nplain executor output",
            )

            with patch("spice.runtime.tui.shell.TUIStreamWriter", FakeStreamWriter):
                with patch("spice.runtime.tui.shell.execute_dry_run_approval", return_value=execution):
                    self.assertFalse(shell.handle_line("/execute approval.test"))

        expected = [
            ("status", "Checking approval...", "approval=approval.test"),
            ("status", "Resolving executor...", "approval=approval.test"),
            ("status", "Handing off to dry-run executor...", "dry_run; approval=approval.test"),
            ("status", "Waiting for executor result...", "dry_run; approval=approval.test"),
            ("status", "Recording outcome...", "outcome.test"),
            ("status", "Composing response...", "deterministic runtime"),
            ("finish", "Execution recorded.", ""),
        ]
        for event in expected:
            self.assertIn(event, events)
        self.assertEqual([events.index(event) for event in expected], sorted(events.index(event) for event in expected))
        self.assertTrue(any("dry_run finished the handoff" in block for block in stream_blocks))

    def test_tui_execute_configured_hands_off_to_openclaw(self) -> None:
        events: list[tuple[str, str, str]] = []
        stream_blocks: list[str] = []

        class FakeStreamWriter:
            def __init__(self, **_: object) -> None:
                self.failed = False

            def start(self) -> "FakeStreamWriter":
                return self

            def status(self, label: str, detail: str = "") -> None:
                events.append(("status", label, detail))

            def finish(self, label: str = "Ready.", detail: str = "") -> None:
                events.append(("finish", label, detail))

            def write_block(self, text: str) -> None:
                stream_blocks.append(text)

        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            command = f"{sys.executable} -c pass"
            update_workspace_config(tmp_dir, "executor", "openclaw")
            update_workspace_config(tmp_dir, "executor_command", command)
            update_workspace_config(tmp_dir, "executor_permission_mode", "workspace_write")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            execution = SimpleNamespace(
                artifact={
                    "executor_provider": "openclaw",
                    "approval_id": "approval.test",
                    "decision_id": "decision.test",
                    "trace_ref": "trace.test",
                    "candidate_id": "candidate.test",
                    "execution_id": "execution.test",
                    "request_id": "request.test",
                    "outcome_id": "outcome.test",
                    "executor_id": "openclaw",
                    "skill_id": "runtime.intent.execute",
                    "context_pack_id": "context.test",
                    "sdep_request_sent": True,
                    "executor_called": True,
                    "real_executor_called": True,
                    "executed": True,
                    "protocol_status": "success",
                    "task_status": "success",
                    "state_updated": True,
                    "persisted": True,
                    "state_after_ref": ".spice/state/state.json#after:test",
                },
                rendered_text="OPENCLAW EXECUTION\nplain executor output",
            )

            with patch("spice.runtime.tui.shell.TUIStreamWriter", FakeStreamWriter):
                with patch.object(shell, "_confirm_executor_permission_for_approval", return_value="workspace_write") as confirm:
                    with patch("spice.runtime.tui.shell.execute_openclaw_approval", return_value=execution) as openclaw:
                        self.assertFalse(shell.handle_line("/execute approval.test"))

        confirm.assert_called_once_with("approval.test")
        openclaw.assert_called_once_with(
            "approval.test",
            command=command,
            project_root=Path(tmp_dir),
        )
        self.assertIn(("status", "Handing off to OpenClaw...", "openclaw; approval=approval.test"), events)
        self.assertIn(("status", "Waiting for executor result...", "openclaw; approval=approval.test"), events)
        self.assertIn(("finish", "Execution recorded.", ""), events)
        self.assertTrue(any("openclaw" in block.lower() for block in stream_blocks))

    def test_tui_execute_configured_renders_natural_execution_error_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            with patch("spice.runtime.tui.shell.execute_dry_run_approval", side_effect=TimeoutError("executor timed out")):
                self.assertFalse(shell.handle_line("/execute approval.test"))

            text = output.getvalue()
            self.assertNotIn("EXECUTION DID NOT COMPLETE", text)
            self.assertIn("dry_run did not complete the handoff", text)
            self.assertIn("timed out", text)
            self.assertIn("approval.test", text)
            session = shell._store().load_session(shell.result.session_id)
            turn = shell._store().load_conversation_turn(session["conversation_turn_ids"][-1])
            self.assertEqual(turn["route"], "execution_request")
            self.assertEqual(turn["source_approval_id"], "approval.test")
            self.assertTrue(turn["metadata"]["execution_response"]["failed"])
            self.assertEqual(turn["metadata"]["execution_result"]["execution_status"], "failed")
            self.assertIn("timed out", turn["metadata"]["execution_result"]["error"])

    def test_tui_execute_error_hides_approval_sdep_mismatch_from_default_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            raw_error = "Approved approval does not match the SDEP request approval_id."

            with patch("spice.runtime.tui.shell.execute_dry_run_approval", side_effect=ValueError(raw_error)):
                self.assertFalse(shell.handle_line("/execute approval.test"))

            text = output.getvalue()
            self.assertIn("current selection is not an executable task", text)
            self.assertIn("did not call the executor", text)
            self.assertNotIn("Approved approval", text)
            self.assertNotIn("SDEP request", text)
            self.assertNotIn("mismatch", text.lower())
            session = shell._store().load_session(shell.result.session_id)
            turn = shell._store().load_conversation_turn(session["conversation_turn_ids"][-1])
            execution_result = turn["metadata"]["execution_result"]
            self.assertEqual(execution_result["failure_kind"], "approval_request_mismatch")
            self.assertEqual(execution_result["technical_error"], raw_error)
            self.assertIn("current selection is not an executable task", execution_result["error"])

    def test_tui_handles_pasted_multiline_commands_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/approve approval.test\n/execute approval.test"))

            text = output.getvalue()
            self.assertIn("error:", text)
            self.assertNotIn("__execute", text)
            self.assertIn("approval.test", text)
            self.assertIn("did not complete the handoff", text)

    def test_tui_rejects_extra_approval_id_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            self.assertFalse(shell.handle_line("/approve approval.one approval.two"))
            self.assertFalse(shell.handle_line("/execute approval.one approval.two"))

            text = output.getvalue()
            self.assertIn("/approve requires exactly one approval id", text)
            self.assertIn("/execute requires exactly one approval id", text)

    def test_codex_approve_execute_refuses_permission_escalation_keeps_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "codex")
            update_workspace_config(tmp_dir, "executor_permission_mode", "read_only")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "/act Add a small smoke note file at .spice-smoke/codex_executor_smoke.txt."
            )
            approval_id = str(shell.pending_decision["approval_id"])

            with patch.object(shell, "_prompt_permission_escalation", return_value="no"):
                self.assertFalse(shell.handle_line("y"))

            approval = load_approval(shell._store(), approval_id)
            self.assertEqual(approval.status, "pending")
            self.assertIsNotNone(shell.pending_decision)
            self.assertIn("Approval remains pending", output.getvalue())

    def test_codex_approve_execute_escalates_permission_for_single_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "codex")
            update_workspace_config(tmp_dir, "executor_permission_mode", "read_only")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "/act Add a small smoke note file at .spice-smoke/codex_executor_smoke.txt."
            )
            approval_id = str(shell.pending_decision["approval_id"])

            with patch.object(shell, "_prompt_permission_escalation", return_value="yes"):
                with patch.object(shell, "_execute_configured") as execute:
                    self.assertFalse(shell.handle_line("y"))

            approval = load_approval(shell._store(), approval_id)
            self.assertEqual(approval.status, "approved")
            execute.assert_called_once_with(approval_id, permission_mode="workspace_write")

    def test_claude_code_approve_execute_escalates_permission_for_single_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "claude_code")
            update_workspace_config(tmp_dir, "executor_permission_mode", "read_only")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "/act Add a small smoke note file at .spice-smoke/claude_code_executor_smoke.txt."
            )
            approval_id = str(shell.pending_decision["approval_id"])

            with patch.object(shell, "_prompt_permission_escalation", return_value="yes"):
                with patch.object(shell, "_execute_configured") as execute:
                    self.assertFalse(shell.handle_line("y"))

            approval = load_approval(shell._store(), approval_id)
            self.assertEqual(approval.status, "approved")
            execute.assert_called_once_with(approval_id, permission_mode="workspace_write")

    def test_hermes_approve_execute_escalates_permission_for_single_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "hermes")
            update_workspace_config(tmp_dir, "executor_permission_mode", "read_only")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "/act Add a small smoke note file at .spice-smoke/hermes_executor_smoke.txt."
            )
            approval_id = str(shell.pending_decision["approval_id"])

            with patch.object(shell, "_prompt_permission_escalation", return_value="yes"):
                with patch.object(shell, "_execute_configured") as execute:
                    self.assertFalse(shell.handle_line("y"))

            approval = load_approval(shell._store(), approval_id)
            self.assertEqual(approval.status, "approved")
            execute.assert_called_once_with(approval_id, permission_mode="workspace_write")

    def test_openclaw_approve_execute_uses_policy_boundary_instead_of_spice_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            update_workspace_config(tmp_dir, "executor", "openclaw")
            update_workspace_config(tmp_dir, "executor_command", f"{sys.executable} -c pass")
            update_workspace_config(tmp_dir, "executor_permission_mode", "read_only")
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)
            _install_execution_ready_frame(shell)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="execution_request",
                    action="execute_selected",
                    is_continuation=True,
                    candidate_id="candidate.a",
                    label="A",
                    text="start it",
                    source="llm",
                ),
            ):
                self.assertFalse(shell.handle_line("start it"))
            approval_id = str(shell.pending_decision["approval_id"])

            with patch.object(shell, "_prompt_permission_escalation") as prompt:
                with patch.object(shell, "_execute_configured") as execute:
                    self.assertFalse(shell.handle_line("y"))

            approval = load_approval(shell._store(), approval_id)
            self.assertEqual(approval.status, "pending")
            self.assertIsNotNone(shell.pending_decision)
            prompt.assert_not_called()
            execute.assert_not_called()
            text = output.getvalue()
            self.assertIn("Execution permission is controlled by the executor policy.", text)
            self.assertIn("OpenClaw", text)
            self.assertIn("openclaw exec-policy show --json", text)
            self.assertIn("openclaw sandbox explain --json", text)

    def test_tui_command_completer_includes_perceive(self) -> None:
        self.assertIn("/perceive", COMMANDS)
        self.assertIn("/pending", COMMANDS)
        self.assertIn("/approval", COMMANDS)
        self.assertIn("/context", COMMANDS)
        self.assertIn("/workspace", COMMANDS)
        self.assertIn("/sources", COMMANDS)
        self.assertIn("/investigate", COMMANDS)

    def _assert_natural_execution_followup_blocks_advisory(self, followup: str) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            setup_workspace(project_root=tmp_dir)
            output = io.StringIO()
            shell = self._plain_output_shell(tmp_dir, output)

            shell.handle_line(
                "Compare these 3 next steps for Spice: add LLM retry, polish Decision Card, "
                "add JSON output. Which should we do first?"
            )
            before_state = shell._store().load_state()
            active_frame = before_state["world_state"]["domain_state"]["general_decision"]["metadata"][
                "active_decision_frame"
            ]
            self.assertFalse(active_frame.get("approval_id"))
            self.assertEqual(shell._store().list_record_ids("approvals"), [])
            self.assertIsNone(shell.pending_decision)

            with patch(
                "spice.runtime.tui.shell.route_semantic_input_from_runtime_config",
                return_value=SemanticRoute(
                    route="execution_request",
                    action="execute_selected",
                    is_continuation=True,
                    candidate_id=str(active_frame["selected_candidate_id"]),
                    text=followup,
                    reason="LLM fallback classified this as an execution follow-up.",
                ),
            ) as resolver:
                self.assertFalse(shell.handle_line(followup))

            approval_ids = shell._store().list_record_ids("approvals")
            self.assertEqual(approval_ids, [])
            self.assertIsNone(shell.pending_decision)
            self.assertEqual(shell._prompt_text(), "spice> ")
            self.assertIn("advisory-only", output.getvalue())
            resolver.assert_called_once()

    def _plain_output_shell(self, tmp_dir: str, output: io.StringIO) -> SpiceTUIShell:
        with patch.object(SpiceTUIShell, "_build_prompt_session", return_value=object()):
            with patch.object(SpiceTUIShell, "_build_console", return_value=None):
                return SpiceTUIShell(
                    project_root=tmp_dir,
                    output_stream=output,
                    history_path=Path(tmp_dir) / "history",
                )


def _install_execution_ready_frame(shell: SpiceTUIShell) -> None:
    candidate_a = _execution_ready_candidate(
        "A",
        "candidate.a",
        "Execute A",
        selected=True,
    )
    candidate_b = _execution_ready_candidate(
        "B",
        "candidate.b",
        "Execute B",
        selected=False,
    )
    frame = {
        "schema_version": "0.1",
        "frame_id": "frame.decision.test",
        "status": "execution_ready",
        "created_at": "2026-05-09T00:00:00Z",
        "updated_at": "2026-05-09T00:00:00Z",
        "source": "test",
        "run_id": "run.test",
        "session_id": shell.result.session_id,
        "decision_id": "decision.test",
        "trace_ref": "trace.test",
        "run_intent_mode": "advise",
        "display_language": "en",
        "input": {"text": "Pick an executable option."},
        "selected_candidate_id": "candidate.a",
        "selected": candidate_a,
        "candidates": [candidate_a, candidate_b],
        "candidate_count": 2,
        "approval_id": "",
        "handoff_blocked": False,
        "handoff_blockers": [],
        "selection_pool": {"kind": "test", "candidate_ids": ["candidate.a", "candidate.b"]},
        "allowed_continuations": [
            {"action": "act_on_selected", "aliases": ["execute this"]},
            {"action": "choose_option", "aliases": ["A", "B"]},
        ],
    }
    store = shell._store()
    payload = store.load_state()
    general = payload["world_state"]["domain_state"]["general_decision"]
    general.setdefault("metadata", {})["active_decision_frame"] = frame
    store.save_state(payload)


def _execution_ready_candidate(
    label: str,
    candidate_id: str,
    title: str,
    *,
    selected: bool,
) -> dict[str, object]:
    return {
        "label": label,
        "candidate_id": candidate_id,
        "title": title,
        "action": "intent.execute",
        "intent": title,
        "recommended_action": title,
        "why_now": ["The user asked to execute this option."],
        "expected_result": "The executor receives the selected handoff task.",
        "executor_task": f"{title} via configured executor.",
        "requires_confirmation": True,
        "is_selected": selected,
        "score_total": 0.8,
        "execution_affordance": {
            "generated_by": "spice.runtime.execution_affordance",
            "candidate_executable": True,
            "executor_available": True,
            "executable": True,
            "blocked": False,
            "blockers": [],
            "executor": {
                "executor_id": "dry_run",
                "status": "ready",
                "transport": "local",
            },
            "permission": {
                "required": "workspace_write",
                "configured": "workspace_write",
                "reason": "Test candidate writes workspace files.",
                "source": "test",
                "side_effect_class": "workspace_write",
                "escalation_required": False,
            },
            "approval": {
                "required": True,
                "eligible_for_approval": True,
                "status": "approval_required_on_selection",
            },
        },
        "skill_resolution": {},
        "simulation": {},
    }


if __name__ == "__main__":
    unittest.main()
