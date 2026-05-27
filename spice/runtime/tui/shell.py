from __future__ import annotations

import json
import shutil
import shlex
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TextIO

from spice.decision.general import load_general_state
from spice.decision.general.types import payload_value
from spice.perception.delegated import (
    INVESTIGATION_CONSENT_GRANTED,
    INVESTIGATION_CONSENT_PENDING,
    INVESTIGATION_CONSENT_REJECTED,
    InvestigationConsent,
    resolve_investigation_consent,
)
from spice.protocols import WorldState
from spice.runtime.approval_flow import (
    approve_approval,
    list_approvals,
    load_approval,
    reject_approval,
)
from spice.runtime.claude_code_provider import execute_claude_code_approval
from spice.runtime.command_router import route_slash_command, split_slash_command
from spice.runtime.continuation_resolver import (
    ContinuationResolution,
    selected_candidate_execution_text,
    update_frame_selected_candidate,
)
from spice.runtime.context_debug import (
    compile_sources_debug_payload,
    compile_workspace_debug_payload,
    latest_delegated_perception_context_from_store,
    latest_url_context_from_store,
    latest_workspace_context_from_store,
    render_sources_debug_text,
    render_workspace_debug_text,
)
from spice.runtime.conversation import build_conversation_turn, save_conversation_turn
from spice.runtime.delegated_perception import (
    RuntimeDelegatedPerceptionHandoffResult,
    run_delegated_perception_handoff,
)
from spice.runtime.composer_context import build_composer_context_payload
from spice.runtime.composer_result import COMPOSER_RESULT_SCHEMA_VERSION, ComposerResult
from spice.runtime.composer_streaming import (
    streamed_response_is_valid,
    streamed_response_was_displayed,
)
from spice.runtime.codex_provider import execute_codex_approval
from spice.runtime.dry_run_executor import execute_dry_run_approval
from spice.runtime.doctor import run_doctor
from spice.runtime.escalation_policy import (
    ESCALATION_AWAIT_INVESTIGATION_CONSENT,
    ESCALATION_BLOCKED,
    ESCALATION_CREATE_INVESTIGATION_CONSENT,
    ESCALATION_RUN_DELEGATED_PERCEPTION,
    RuntimeEscalationDecision,
    build_investigation_consent_for_escalation,
    decide_runtime_escalation,
)
from spice.runtime.pre_run_evidence_gate import (
    PRE_RUN_EVIDENCE_CREATE_INVESTIGATION_CONSENT,
    PRE_RUN_EVIDENCE_RUN_URL_PERCEPTION,
    PRE_RUN_EVIDENCE_RUN_WORKSPACE_PERCEPTION,
    PreRunEvidenceGateDecision,
    evaluate_pre_run_evidence_gate,
    render_pre_run_evidence_gate_message,
)
from spice.runtime.execution_conversation import open_execution_approval_from_frame
from spice.runtime.execution_permission import approval_requires_permission_escalation
from spice.runtime.executor_capabilities import config_with_executor_capability_snapshot
from spice.runtime.executor_runtime import (
    resolve_executor_runtime_from_config,
    resolve_executor_runtime_from_config_with_permission,
)
from spice.runtime.follow_up import (
    answer_candidate_plan,
    answer_general_follow_up,
    answer_why_not_candidate,
)
from spice.runtime.hermes_provider import execute_hermes_approval
from spice.runtime.openclaw_provider import execute_openclaw_approval
from spice.runtime.interactive_shell import InteractiveShellResult, run_interactive_shell
from spice.runtime.memory_writeback import (
    skipped_general_evolution_memory_writeback,
    write_general_evolution_memory,
)
from spice.runtime.perceive import perceive_once
from spice.runtime.resource_extractor import extract_resources
from spice.runtime.run_once import RunOnceResult, run_once
from spice.runtime.refine import RefineResult, refine_decision
from spice.runtime.execution_response_composer import (
    classify_execution_error,
    compose_execution_response_from_runtime_config,
    execution_response_facts,
    render_execution_response_fallback,
    user_facing_execution_error,
)
from spice.runtime.response_composer import compose_decision_response_from_runtime_config
from spice.runtime.evidence_requirement import detect_evidence_requirement
from spice.runtime.route_merge_policy import RouteMergePolicy, merge_route_context_policy
from spice.runtime.runtime_guardrails import render_guardrail_message, validate_active_frame_route
from spice.runtime.sdep_subprocess_executor import execute_sdep_subprocess_approval
from spice.runtime.session import (
    DEFAULT_SESSION_ID,
    build_session_timeline,
    load_or_create_session,
    session_stats,
)
from spice.runtime.semantic_router import (
    route_semantic_input_from_runtime_config,
    semantic_route_to_continuation,
)
from spice.runtime.store import LocalJsonStore
from spice.runtime.tui.surfaces.approval import (
    render_approval_details_panel,
    render_approval_resolution_panel,
    render_approvals_panel,
)
from spice.runtime.tui.surfaces.banner import render_banner
from spice.runtime.tui.surfaces.decisioncard import render_decision_card
from spice.runtime.tui.surfaces.doctor import render_doctor_panel
from spice.runtime.tui.surfaces.execution import render_execution_panel
from spice.runtime.tui.surfaces.perception import render_perception_panel
from spice.runtime.tui.surfaces.progress import TUIStatusFlow
from spice.runtime.tui.surfaces.session import render_session_panel, render_stats_panel, render_timeline_panel
from spice.runtime.tui.surfaces.state import render_state_panel
from spice.runtime.tui.surfaces.stream import TUIStreamWriter
from spice.runtime.tui.theme import COMMANDS, SpiceTheme
from spice.runtime.workspace import (
    SpiceWorkspaceConfig,
    load_workspace_config,
    load_workspace_env,
    require_workspace,
)
from spice.runtime.workspace import load_workspace_context_compiler
from spice.runtime.workspace import load_workspace_memory_provider
from spice.runtime.workspace_scope import resolve_workspace_scope
from spice.runtime.workspace_perception import (
    RuntimeWorkspacePerceptionResult,
    run_runtime_workspace_perception_step,
)
from spice.runtime.url_perception import (
    RuntimeURLPerceptionResult,
    run_runtime_url_perception_step,
)


def run_tui_shell(
    *,
    project_root: str | Path = ".",
    session_id: str = DEFAULT_SESSION_ID,
    plain: bool = False,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    use_bars: bool = True,
    persist: bool = True,
    full_loop_preview: bool = True,
    run_intent_mode: str = "auto",
) -> InteractiveShellResult:
    if plain or not _prompt_toolkit_available():
        return run_interactive_shell(
            project_root=project_root,
            session_id=session_id,
            input_stream=input_stream,
            output_stream=output_stream,
            use_bars=use_bars,
            persist=persist,
            full_loop_preview=full_loop_preview,
            run_intent_mode=run_intent_mode,
        )
    shell = SpiceTUIShell(
        project_root=project_root,
        session_id=session_id,
        output_stream=output_stream,
        use_bars=use_bars,
        persist=persist,
        full_loop_preview=full_loop_preview,
        run_intent_mode=run_intent_mode,
    )
    return shell.run()


class SpiceTUIShell:
    def __init__(
        self,
        *,
        project_root: str | Path = ".",
        session_id: str = DEFAULT_SESSION_ID,
        output_stream: TextIO | None = None,
        history_path: Path | None = None,
        use_bars: bool = True,
        persist: bool = True,
        full_loop_preview: bool = True,
        run_intent_mode: str = "auto",
    ) -> None:
        self.project_root = Path(project_root)
        self.session_id = session_id
        self.output_stream = output_stream
        self.use_bars = use_bars
        self.persist = persist
        self.full_loop_preview = full_loop_preview
        self.run_intent_mode = run_intent_mode
        self.history_path = history_path or (Path.home() / ".spice" / ".history")
        self.console = self._build_console(output_stream)
        self.prompt_session = self._build_prompt_session()
        self.store: LocalJsonStore | None = None
        self.result = InteractiveShellResult(session_id=session_id)
        self.pending_decision: dict[str, str] | None = None
        self.pending_investigation: dict[str, Any] | None = None

    def run(self) -> InteractiveShellResult:
        paths = require_workspace(self.project_root)
        load_workspace_env(self.project_root)
        self.store = LocalJsonStore(paths)
        config = load_workspace_config(self.project_root).to_payload()
        session = load_or_create_session(self.store, session_id=self.session_id)
        self.store.save_session(session.session_id, session.to_payload())
        self.result.session_id = session.session_id
        self._render_startup_banner(config=config, session_payload=session.to_payload())
        self.print(self.render_help(compact=True))
        while True:
            try:
                line = self.prompt_session.prompt([("class:prompt", self._prompt_text())])
            except (EOFError, KeyboardInterrupt):
                break
            if self.handle_line(line):
                break
        self.print(f"Spice session closed: {self.result.session_id}")
        self.print(f"turns: {self.result.turns}")
        return self.result

    def handle_line(self, raw_line: str) -> bool:
        lines = [line.strip() for line in raw_line.splitlines() if line.strip()]
        if not lines:
            return False
        should_exit = False
        for line in lines:
            if line.startswith("/"):
                should_exit = self._handle_command(line)
            elif self.pending_investigation is not None:
                self._handle_investigation_feedback(line)
                should_exit = False
            elif self.pending_decision is not None:
                self._handle_decision_feedback(line)
                should_exit = False
            elif self._handle_continuation(line):
                should_exit = False
            else:
                self._run_intent(line, mode=self.run_intent_mode, full_loop_preview=self.full_loop_preview)
                should_exit = False
            if should_exit:
                break
        return should_exit

    def print(self, renderable: Any) -> None:
        if isinstance(renderable, str):
            stream = self.output_stream
            if stream is None and self.console is not None:
                stream = getattr(self.console, "file", None)
            if stream is None:
                print(renderable)
            else:
                stream.write(f"{renderable}\n")
                stream.flush()
            return
        if self.console is not None:
            self.console.print(renderable)
            return
        if not isinstance(renderable, str):
            try:
                from rich.console import Console

                Console(file=self.output_stream, force_terminal=None, legacy_windows=False).print(renderable)
                return
            except ImportError:
                pass
        stream = self.output_stream
        if stream is None:
            print(str(renderable))
        else:
            stream.write(f"{renderable}\n")
            stream.flush()

    def _render_width(self) -> int:
        if self.console is not None:
            try:
                return int(self.console.size.width)
            except (AttributeError, TypeError, ValueError):
                pass
        return shutil.get_terminal_size((100, 24)).columns

    def render_help(self, *, compact: bool = False) -> Any:
        text = "\n".join(
            [
                "Commands:",
                "- type any intent to run the default decision loop",
                "- /act <intent>       run an execution-handoff decision",
                "- /advise <intent>    run a decision-only advisory turn",
                "- /refine <feedback>  refine the latest decision card",
                "- /details           expand the latest Decision Card",
                "- /details execution show latest execution/outcome audit",
                "- /card              show the latest Decision Card",
                "- /why               show why the latest decision won",
                "- /sim               show latest simulation outcomes",
                "- /json              show latest run artifact JSON",
                "- /sources [--json]  show files, URLs, snippets, and perception artifacts used",
                "- /investigate       inspect or resolve pending read-only investigation consent",
                "- /json execution    show latest execution/outcome JSON",
                "- /perceive [opts]    pull external signals once; optionally open a Decision Card",
                "- /pending           continue a pending approval flow",
                "- /approval <id>     open an approval action menu",
                "- /approvals         list approval checkpoints",
                "- /approve <id>      approve a pending checkpoint",
                "- /reject <id> [why] reject a pending checkpoint",
                "- /details <id>      show approval details",
                "- /execute <id>      execute using configured executor",
                "- /dry-run <id>      run the local dry-run executor bridge",
                "- /session           show current session summary",
                "- /timeline          show current session timeline",
                "- /stats             show session stats",
                "- /doctor            check workspace health",
                "- /context [--json]  show the compiled model context",
                "- /workspace [--json] show latest workspace perception",
                "- /state             show General Decision state",
                "- /refresh           redraw the startup banner",
                "- /help              show this help",
                "- /exit              close the shell",
            ]
        )
        if compact:
            text = "\n".join(text.splitlines()[:6] + ["- /help              show all commands"])
        try:
            from rich import box
            from rich.panel import Panel
        except ImportError:
            return text
        return Panel(
            text,
            title="[bold red]HELP[/bold red]",
            border_style=SpiceTheme.PANEL_BORDER,
            box=box.ROUNDED,
        )

    def _handle_command(self, line: str) -> bool:
        routed = route_slash_command(line)
        command, value = routed.command, routed.value
        if not routed.known:
            self.print(f"unknown command: {command}. Type /help for commands.")
            return False
        if command in {"/exit", "/quit"}:
            return True
        if command == "/help":
            self.print(self.render_help())
            return False
        if command == "/refresh":
            self._refresh_banner()
            return False
        if command in {"/refine", "/explore"}:
            if command == "/explore":
                self.print("explore is not available yet; use /refine to update the latest decision card.")
                return False
            if not value:
                self.print("error: /refine requires feedback text")
                return False
            self._refine_decision(value)
            return False
        if command == "/doctor":
            self.print(render_doctor_panel(run_doctor(self.project_root)))
            return False
        if command == "/state":
            self._show_state()
            return False
        if command == "/context":
            self._show_context(value)
            return False
        if command == "/workspace":
            self._show_workspace(value)
            return False
        if command == "/sources":
            self._show_sources(value)
            return False
        if command == "/investigate":
            self._handle_investigate_command(value)
            return False
        if command == "/card":
            self._show_latest_card(value)
            return False
        if command == "/why":
            self._show_latest_why(value)
            return False
        if command == "/sim":
            self._show_latest_simulation(value)
            return False
        if command == "/json":
            self._show_latest_json(value)
            return False
        if command == "/perceive":
            self._perceive(value)
            return False
        if command == "/session":
            self._show_session()
            return False
        if command == "/timeline":
            self._show_timeline()
            return False
        if command in {"/stats", "/metrics"}:
            self._show_stats()
            return False
        if command == "/approvals":
            self._show_approvals()
            return False
        if command == "/pending":
            self._open_pending_approval_flow()
            return False
        if command == "/approval":
            if not value:
                self.print("error: /approval requires an approval id")
                return False
            self._open_pending_approval_flow(value)
            return False
        if command == "/details":
            if value:
                if _execution_audit_target(value):
                    self._show_latest_execution_details(value)
                else:
                    approval_id = self._single_approval_id(command, value)
                    if approval_id:
                        self._show_approval_details(approval_id)
            else:
                self._show_latest_card()
            return False
        if command in {"/approve", "/yes", "/y"}:
            approval_id = self._single_approval_id(command, value)
            if approval_id:
                self._resolve_approval(approval_id, status="approved")
            return False
        if command in {"/reject", "/no", "/n"}:
            approval_id, reason = _split_first(value)
            self._resolve_approval(approval_id, status="rejected", reason=reason)
            return False
        if command == "/dry-run":
            approval_id = self._single_approval_id(command, value)
            if approval_id:
                self._execute_dry_run(approval_id)
            return False
        if command == "/execute":
            if value:
                approval_id = self._single_approval_id(command, value)
                if approval_id:
                    self._execute_configured(approval_id)
            else:
                self._execute_active_frame_selected()
            return False
        if command == "/act":
            if not value:
                self.print("error: /act requires an intent")
                return False
            self._run_intent(value, mode="act", full_loop_preview=self.full_loop_preview)
            return False
        if command == "/advise":
            if not value:
                self.print("error: /advise requires an intent")
                return False
            self._run_intent(value, mode="advise", full_loop_preview=False)
            return False
        self.print(f"unknown command: {command}. Type /help for commands.")
        return False

    def _render_startup_banner(self, *, config: dict[str, Any], session_payload: dict[str, Any]) -> None:
        if self.store is None:
            return
        self.print(
            render_banner(
                config,
                session_payload,
                dashboard=_startup_dashboard(self.store, config),
                width=self._render_width(),
            )
        )

    def _refresh_banner(self) -> None:
        if self.store is None:
            self.print("error: shell store is not initialized")
            return
        config = load_workspace_config(self.project_root).to_payload()
        session = load_or_create_session(self.store, session_id=self.result.session_id)
        self._render_startup_banner(config=config, session_payload=session.to_payload())

    def _single_approval_id(self, command: str, value: str) -> str:
        tokens = value.split()
        if len(tokens) != 1:
            self.print(f"error: {command} requires exactly one approval id")
            return ""
        return tokens[0]

    def _merge_runtime_perception_route(
        self,
        user_input: str,
        route: Any,
        *,
        interactive: bool = True,
    ) -> tuple[Any, RouteMergePolicy, PreRunEvidenceGateDecision]:
        resources = extract_resources(user_input)
        evidence_requirement = detect_evidence_requirement(
            user_input,
            resource_extraction=resources,
        )
        workspace_scope = resolve_workspace_scope(
            project_root=self.project_root,
            resource_extraction=resources,
            interactive=interactive,
            allow_external_roots=False,
        )
        policy = merge_route_context_policy(
            route,
            user_input=user_input,
            resource_extraction=resources,
            evidence_requirement=evidence_requirement,
            workspace_scope=workspace_scope,
        )
        gate = evaluate_pre_run_evidence_gate(policy)
        return _with_merged_route_context(route, policy), policy, gate

    def _block_for_pre_run_evidence_gate(
        self,
        gate: PreRunEvidenceGateDecision,
        *,
        stream: TUIStreamWriter | None = None,
        status: TUIStatusFlow | None = None,
    ) -> bool:
        if gate.allowed:
            return False
        message = render_pre_run_evidence_gate_message(gate)
        if stream is not None:
            stream.write_block(message)
            stream.finish("Evidence needed.")
            return True
        if status is not None:
            status.finish("Evidence needed.")
            self.print(message)
            return True
        self.print(message)
        return True

    def _block_if_required_evidence_is_still_missing(
        self,
        gate: PreRunEvidenceGateDecision,
        *,
        stream: TUIStreamWriter | None = None,
        status: TUIStatusFlow | None = None,
    ) -> bool:
        if gate.action not in {
            PRE_RUN_EVIDENCE_RUN_WORKSPACE_PERCEPTION,
            PRE_RUN_EVIDENCE_RUN_URL_PERCEPTION,
        }:
            return False
        message = (
            "I still do not have the required evidence source after attempting perception.\n"
            f"Reason: {gate.reason}\n"
            "I will not make a high-confidence repo/URL claim without a source."
        )
        if stream is not None:
            stream.write_block(message)
            stream.finish("Evidence missing.")
            return True
        if status is not None:
            status.finish("Evidence missing.")
            self.print(message)
            return True
        self.print(message)
        return True

    def _run_intent(self, intent: str, *, mode: str, full_loop_preview: bool) -> None:
        stream = TUIStreamWriter(
            console=self.console,
            output_stream=self.output_stream,
            status_title="SPICE",
        ).start()
        try:
            config = load_workspace_config(self.project_root).to_payload()
            model_detail = _runtime_model_detail(config)
            _stream_status(stream, _decision_status_label(mode), model_detail)
            route = route_semantic_input_from_runtime_config(
                intent,
                self._active_decision_frame(),
                config=config,
            )
            route, route_policy, gate = self._merge_runtime_perception_route(intent, route)
            if self._block_for_pre_run_evidence_gate(gate, stream=stream):
                return
            workspace_step = None
            if gate.should_run_workspace_perception or gate.action == PRE_RUN_EVIDENCE_RUN_WORKSPACE_PERCEPTION:
                _stream_status(stream, _workspace_evidence_status_label(), model_detail)
                workspace_step = self._run_workspace_perception_step(
                    query=route.workspace_query or intent,
                    trigger="new_decision",
                    config=config,
                    route_policy=route_policy,
                )
            url_step = None
            gate = evaluate_pre_run_evidence_gate(
                route_policy,
                workspace_context=_workspace_context_from_step(workspace_step),
                url_context=None,
                delegated_perception_context=None,
            )
            if self._block_for_pre_run_evidence_gate(gate, stream=stream):
                return
            if (
                gate.action != PRE_RUN_EVIDENCE_RUN_URL_PERCEPTION
                and self._block_if_required_evidence_is_still_missing(gate, stream=stream)
            ):
                return
            if gate.should_run_url_perception or gate.action == PRE_RUN_EVIDENCE_RUN_URL_PERCEPTION:
                _stream_status(stream, _url_evidence_status_label(), model_detail)
                url_step = self._run_url_perception_step(
                    text=intent,
                    urls=route.urls,
                    query=route.url_query or intent,
                    trigger="new_decision",
                )
            gate = evaluate_pre_run_evidence_gate(
                route_policy,
                workspace_context=_workspace_context_from_step(workspace_step),
                url_context=_url_context_from_step(url_step),
                delegated_perception_context=None,
            )
            if self._block_if_required_evidence_is_still_missing(gate, stream=stream):
                return
            escalation = self._delegated_escalation_for_route(
                route,
                config=config,
                workspace_context=_workspace_context_from_step(workspace_step),
                workspace_perception=_workspace_artifact_from_step(workspace_step),
                url_context=_url_context_from_step(url_step),
                url_perception=_url_artifact_from_step(url_step),
            )
            if self._should_pause_for_delegated_escalation(escalation):
                stream.finish(_delegated_escalation_finish_label(escalation))
                self._open_investigation_consent_from_escalation(
                    escalation,
                    route_payload=route.to_payload(),
                    user_input=intent,
                    trigger="new_decision",
                    workspace_perception=_workspace_artifact_from_step(workspace_step),
                    url_perception=_url_artifact_from_step(url_step),
                )
                return
            result = run_once(
                intent,
                project_root=self.project_root,
                session_id=self.result.session_id,
                use_bars=self.use_bars,
                persist=self.persist,
                full_loop_preview=full_loop_preview,
                run_intent_mode=mode,
                workspace_context=_workspace_context_from_step(workspace_step),
                workspace_perception=_workspace_artifact_from_step(workspace_step),
                url_context=_url_context_from_step(url_step),
                url_perception=_url_artifact_from_step(url_step),
            )
            _stream_status(stream, "Composing response...", model_detail)
            composed = self._compose_decision_response_result(
                result.artifact,
                stream_callback=_stream_token_callback(stream),
            )
            brief = composed.response_text
            brief_blocks = [] if streamed_response_is_valid(composed.metadata) else _response_text_blocks(brief)
            composed = _composer_result_with_streaming_metadata(composed, chunk_count=len(brief_blocks))
            self._persist_decision_response_composer(result.artifact, composed)
        except Exception as exc:
            _stream_fail(stream, f"error: {exc}")
            return
        self._record_run(result)
        if streamed_response_is_valid(composed.metadata):
            _stream_write_text(stream, "\n\n")
        elif streamed_response_was_displayed(composed.metadata):
            stream.write_block("\nI need to correct that response after validating it:")
        for block in brief_blocks:
            stream.write_block(block)
        stream.write_block(self._artifacts_text(result))
        stream.finish("Ready.")
        self._set_pending_decision(result.artifact)

    def _refine_decision(
        self,
        refinement: str,
        *,
        workspace_context: Mapping[str, Any] | None = None,
        workspace_perception: Mapping[str, Any] | None = None,
        url_context: Mapping[str, Any] | None = None,
        url_perception: Mapping[str, Any] | None = None,
        delegated_perception_context: Mapping[str, Any] | None = None,
        delegated_perception: Mapping[str, Any] | None = None,
    ) -> None:
        stream = TUIStreamWriter(
            console=self.console,
            output_stream=self.output_stream,
            status_title="SPICE",
        ).start()
        try:
            config = load_workspace_config(self.project_root).to_payload()
            _stream_status(stream, "Revisiting the decision...", _runtime_model_detail(config))
            route = None
            if (
                workspace_context is None
                and workspace_perception is None
                and url_context is None
                and url_perception is None
                and delegated_perception_context is None
                and delegated_perception is None
            ):
                route = route_semantic_input_from_runtime_config(
                    refinement,
                    self._active_decision_frame(),
                    config=config,
                )
                route, route_policy, gate = self._merge_runtime_perception_route(refinement, route)
                if self._block_for_pre_run_evidence_gate(gate, stream=stream):
                    return
                if gate.should_run_workspace_perception or gate.action == PRE_RUN_EVIDENCE_RUN_WORKSPACE_PERCEPTION:
                    _stream_status(stream, _workspace_evidence_status_label(), _runtime_model_detail(config))
                    workspace_step = self._run_workspace_perception_step(
                        query=route.workspace_query or refinement,
                        trigger="refine_decision",
                        config=config,
                        route_policy=route_policy,
                    )
                    workspace_context = _workspace_context_from_step(workspace_step)
                    workspace_perception = _workspace_artifact_from_step(workspace_step)
                gate = evaluate_pre_run_evidence_gate(
                    route_policy,
                    workspace_context=workspace_context,
                    url_context=url_context,
                    delegated_perception_context=delegated_perception_context,
                )
                if self._block_for_pre_run_evidence_gate(gate, stream=stream):
                    return
                if (
                    gate.action != PRE_RUN_EVIDENCE_RUN_URL_PERCEPTION
                    and self._block_if_required_evidence_is_still_missing(gate, stream=stream)
                ):
                    return
                if gate.should_run_url_perception or gate.action == PRE_RUN_EVIDENCE_RUN_URL_PERCEPTION:
                    _stream_status(stream, _url_evidence_status_label(), _runtime_model_detail(config))
                    url_step = self._run_url_perception_step(
                        text=refinement,
                        urls=route.urls,
                        query=route.url_query or refinement,
                        trigger="refine_decision",
                    )
                    url_context = _url_context_from_step(url_step)
                    url_perception = _url_artifact_from_step(url_step)
                gate = evaluate_pre_run_evidence_gate(
                    route_policy,
                    workspace_context=workspace_context,
                    url_context=url_context,
                    delegated_perception_context=delegated_perception_context,
                )
                if self._block_if_required_evidence_is_still_missing(gate, stream=stream):
                    return
                escalation = self._delegated_escalation_for_route(
                    route,
                    config=config,
                    workspace_context=workspace_context,
                    workspace_perception=workspace_perception,
                    url_context=url_context,
                    url_perception=url_perception,
                )
                if self._should_pause_for_delegated_escalation(escalation):
                    stream.finish(_delegated_escalation_finish_label(escalation))
                    self._open_investigation_consent_from_escalation(
                        escalation,
                        route_payload=route.to_payload(),
                        user_input=refinement,
                        trigger="refine_decision",
                        workspace_perception=workspace_perception,
                        url_perception=url_perception,
                    )
                    return
            result = refine_decision(
                refinement,
                project_root=self.project_root,
                session_id=self.result.session_id,
                use_bars=self.use_bars,
                persist=self.persist,
                full_loop_preview=self.full_loop_preview,
                workspace_context=workspace_context,
                workspace_perception=workspace_perception,
                url_context=url_context,
                url_perception=url_perception,
                delegated_perception_context=delegated_perception_context,
                delegated_perception=delegated_perception,
            )
            _stream_status(stream, "Composing updated response...", _runtime_model_detail(config))
            composed = self._compose_decision_response_result(
                result.artifact,
                stream_callback=_stream_token_callback(stream),
            )
            brief = composed.response_text
            brief_blocks = [] if streamed_response_is_valid(composed.metadata) else _response_text_blocks(brief)
            composed = _composer_result_with_streaming_metadata(composed, chunk_count=len(brief_blocks))
            self._persist_decision_response_composer(result.artifact, composed)
        except Exception as exc:
            _stream_fail(stream, f"error: {exc}")
            return
        self._record_refine(result)
        if streamed_response_is_valid(composed.metadata):
            _stream_write_text(stream, "\n\n")
        elif streamed_response_was_displayed(composed.metadata):
            stream.write_block("\nI need to correct that response after validating it:")
        for block in brief_blocks:
            stream.write_block(block)
        stream.write_block(self._refine_artifacts_text(result))
        stream.finish("Ready.")
        self._set_pending_decision(result.artifact)

    def _stream_response_text(self, text: str, *, finish_label: str = "Ready.") -> None:
        self._stream_response_blocks(_response_text_blocks(text), finish_label=finish_label)

    def _stream_response_blocks(self, blocks: list[str], *, finish_label: str = "Ready.") -> None:
        stream = TUIStreamWriter(
            console=self.console,
            output_stream=self.output_stream,
            status_title="SPICE",
            use_status=False,
        ).start()
        for block in blocks:
            stream.write_block(block)
        stream.finish(finish_label)

    def _print_decision_brief(self, artifact: dict[str, Any]) -> None:
        self.print(self._decision_brief_text(artifact))

    def _decision_brief_text(self, artifact: dict[str, Any]) -> str:
        return self._compose_decision_response_result(artifact).response_text

    def _compose_decision_response_result(
        self,
        artifact: dict[str, Any],
        *,
        stream_callback: Any | None = None,
    ) -> ComposerResult:
        try:
            config = load_workspace_config(self.project_root).to_payload()
            context_payload = build_composer_context_payload(
                project_root=self.project_root,
                session_id=self.result.session_id,
                latest_artifact=artifact,
            )
            composed = compose_decision_response_from_runtime_config(
                config=config,
                artifact=artifact,
                context_payload=context_payload,
                stream_callback=stream_callback,
            )
            if isinstance(composed, ComposerResult):
                return composed
            response_text = str(getattr(composed, "response_text", "") or "")
            if response_text:
                return ComposerResult(
                    enabled=True,
                    status=str(getattr(composed, "status", "") or "composed"),
                    response_text=response_text,
                    deterministic_text=str(getattr(composed, "deterministic_text", "") or response_text),
                    composer_kind=str(getattr(composed, "composer_kind", "") or "decision_response"),
                    raw_output=str(getattr(composed, "raw_output", "") or ""),
                    fallback_reason=str(getattr(composed, "fallback_reason", "") or ""),
                    error=str(getattr(composed, "error", "") or ""),
                    facts=dict(getattr(composed, "facts", {}) or {}),
                    metadata=dict(getattr(composed, "metadata", {}) or {}),
                )
            raise ValueError("decision response composer returned no response text")
        except Exception as exc:
            text = _fallback_decision_brief_text(_mapping(artifact.get("decision_brief")), exc)
            return ComposerResult(
                enabled=True,
                status="fallback",
                response_text=text,
                deterministic_text=text,
                composer_kind="decision_response",
                error=str(exc),
                fallback_reason="composer_exception",
                facts={"decision_id": str(artifact.get("decision_id") or "")},
                metadata={"composer_schema_version": "spice.decision_response_composer.v1"},
            )

    def _execution_response_text(self, artifact: dict[str, Any]) -> str:
        return self._compose_execution_response_result(artifact).response_text

    def _compose_execution_response_result(
        self,
        artifact: dict[str, Any],
        *,
        stream_callback: Any | None = None,
    ) -> ComposerResult:
        try:
            config = load_workspace_config(self.project_root).to_payload()
            context_payload = build_composer_context_payload(
                project_root=self.project_root,
                session_id=self.result.session_id,
            )
            composed = compose_execution_response_from_runtime_config(
                config=config,
                execution_artifact=artifact,
                context_payload=context_payload,
                stream_callback=stream_callback,
            )
            if isinstance(composed, ComposerResult):
                return composed
            response_text = str(getattr(composed, "response_text", "") or "")
            if response_text:
                return ComposerResult(
                    enabled=True,
                    status=str(getattr(composed, "status", "") or "composed"),
                    response_text=response_text,
                    deterministic_text=str(getattr(composed, "deterministic_text", "") or response_text),
                    composer_kind=str(getattr(composed, "composer_kind", "") or "execution_response"),
                    raw_output=str(getattr(composed, "raw_output", "") or ""),
                    fallback_reason=str(getattr(composed, "fallback_reason", "") or ""),
                    error=str(getattr(composed, "error", "") or ""),
                    facts=dict(getattr(composed, "facts", {}) or {}),
                    metadata=dict(getattr(composed, "metadata", {}) or {}),
                )
            raise ValueError("execution response composer returned no response text")
        except Exception as exc:
            facts = execution_response_facts(execution_artifact=artifact)
            text = render_execution_response_fallback(facts)
            return ComposerResult(
                enabled=True,
                status="fallback",
                response_text=text,
                deterministic_text=text,
                composer_kind="execution_response",
                error=str(exc),
                fallback_reason="composer_exception",
                facts=facts,
                metadata={"composer_schema_version": "spice.execution_response_composer.v1"},
            )

    def _execution_error_response_text(self, error_artifact: dict[str, Any]) -> str:
        return self._compose_execution_error_response_result(error_artifact).response_text

    def _compose_execution_error_response_result(
        self,
        error_artifact: dict[str, Any],
        *,
        stream_callback: Any | None = None,
    ) -> ComposerResult:
        try:
            config = load_workspace_config(self.project_root).to_payload()
            context_payload = build_composer_context_payload(
                project_root=self.project_root,
                session_id=self.result.session_id,
            )
            composed = compose_execution_response_from_runtime_config(
                config=config,
                error_artifact=error_artifact,
                context_payload=context_payload,
                stream_callback=stream_callback,
            )
            if isinstance(composed, ComposerResult):
                return composed
            response_text = str(getattr(composed, "response_text", "") or "")
            if response_text:
                return ComposerResult(
                    enabled=True,
                    status=str(getattr(composed, "status", "") or "composed"),
                    response_text=response_text,
                    deterministic_text=str(getattr(composed, "deterministic_text", "") or response_text),
                    composer_kind=str(getattr(composed, "composer_kind", "") or "execution_response"),
                    raw_output=str(getattr(composed, "raw_output", "") or ""),
                    fallback_reason=str(getattr(composed, "fallback_reason", "") or ""),
                    error=str(getattr(composed, "error", "") or ""),
                    facts=dict(getattr(composed, "facts", {}) or {}),
                    metadata=dict(getattr(composed, "metadata", {}) or {}),
                )
            raise ValueError("execution response composer returned no response text")
        except Exception as exc:
            facts = execution_response_facts(error_artifact=error_artifact)
            text = render_execution_response_fallback(facts)
            return ComposerResult(
                enabled=True,
                status="fallback",
                response_text=text,
                deterministic_text=text,
                composer_kind="execution_response",
                error=str(exc),
                fallback_reason="composer_exception",
                facts=facts,
                metadata={"composer_schema_version": "spice.execution_response_composer.v1"},
            )

    def _persist_decision_response_composer(self, artifact: dict[str, Any], composed: ComposerResult) -> None:
        payload = _composer_result_payload(composed)
        artifact["response_composer"] = payload
        artifact["conversation_response"] = {
            "response_text": composed.response_text,
            "summary": _conversation_response_summary(composed.response_text),
            "composer_status": composed.status,
            "composer_kind": composed.composer_kind,
        }
        try:
            store = self._store()
            run_id = str(artifact.get("run_id") or "")
            if run_id:
                store.save_run(run_id, artifact)
            turn_id = str(artifact.get("conversation_turn_id") or "")
            if turn_id:
                turn = store.load_conversation_turn(turn_id)
                metadata = _mapping(turn.get("metadata"))
                metadata["decision_response"] = payload
                metadata["response_summary"] = _conversation_response_summary(composed.response_text)
                turn["metadata"] = metadata
                artifact["conversation_turn"] = turn
                store.save_conversation_turn(turn_id, turn)
        except Exception:
            return

    def _persist_execution_response_composer(self, artifact: dict[str, Any], composed: ComposerResult) -> None:
        payload = _composer_result_payload(composed)
        artifact["execution_response_composer"] = payload
        artifact["conversation_response"] = {
            "response_text": composed.response_text,
            "summary": _conversation_response_summary(composed.response_text),
            "composer_status": composed.status,
            "composer_kind": composed.composer_kind,
        }
        try:
            store = self._store()
            outcome_id = str(artifact.get("outcome_id") or "")
            if outcome_id:
                outcome = store.load_outcome(outcome_id)
                outcome["execution_response_composer"] = payload
                store.save_outcome(outcome_id, outcome)
            run_id = str(artifact.get("run_id") or "")
            if run_id:
                run = store.load_run(run_id)
                run["execution_response_composer"] = payload
                execution_payload = _mapping(run.get("dry_run_execution"))
                if execution_payload and str(execution_payload.get("outcome_id") or "") == outcome_id:
                    execution_payload["execution_response_composer"] = payload
                    run["dry_run_execution"] = execution_payload
                run["conversation_response"] = {
                    "response_text": composed.response_text,
                    "summary": _conversation_response_summary(composed.response_text),
                    "composer_status": composed.status,
                    "composer_kind": composed.composer_kind,
                }
                store.save_run(run_id, run)
        except Exception:
            return

    def _write_execution_conversation_turn(
        self,
        artifact: dict[str, Any],
        *,
        response_text: str,
        failed: bool,
        composer_result: ComposerResult | None = None,
    ) -> str:
        if not self.persist:
            return ""
        try:
            store = self._store()
            created = datetime.now(timezone.utc)
            facts = execution_response_facts(
                error_artifact=artifact if failed else None,
                execution_artifact=artifact if not failed else None,
            )
            approval_id = str(facts.get("approval_id") or artifact.get("approval_id") or "")
            approval_context = self._approval_context_for_conversation(approval_id)
            decision_id = str(facts.get("decision_id") or approval_context.get("decision_id") or "")
            candidate_id = str(facts.get("candidate_id") or approval_context.get("candidate_id") or "")
            run_id = str(artifact.get("run_id") or approval_context.get("run_id") or "")
            outcome_id = str(facts.get("outcome_id") or "")
            execution_id = str(facts.get("execution_id") or "")
            turn = build_conversation_turn(
                user_input=f"execute {approval_id}".strip(),
                route="execution_request",
                session_id=self.result.session_id,
                created_at=created,
                source_decision_id=decision_id or None,
                source_candidate_id=candidate_id or None,
                source_run_id=run_id or None,
                source_approval_id=approval_id or None,
                source_execution_id=execution_id or None,
                source_outcome_id=outcome_id or None,
                artifact_refs=_execution_conversation_artifact_refs(
                    store,
                    artifact,
                    approval_id=approval_id,
                    decision_id=decision_id,
                    run_id=run_id,
                    outcome_id=outcome_id,
                ),
                metadata={
                    "generated_by": "spice.runtime.tui.shell",
                    "execution_response": {
                        "action": "execution_result",
                        "status": str(facts.get("execution_status") or ""),
                        "executor_provider": str(facts.get("executor_provider") or ""),
                        "task_status": str(facts.get("task_status") or ""),
                        "protocol_status": str(facts.get("protocol_status") or ""),
                        "response_text": response_text,
                        "summary": _conversation_response_summary(response_text),
                        "failed": failed,
                        **(
                            {"composer_result": _composer_result_payload(composer_result)}
                            if composer_result is not None
                            else {}
                        ),
                    },
                    "execution_result": {
                        "approval_id": approval_id,
                        "decision_id": decision_id,
                        "candidate_id": candidate_id,
                        "execution_id": execution_id,
                        "outcome_id": outcome_id,
                        "executor_provider": str(facts.get("executor_provider") or ""),
                        "execution_status": str(facts.get("execution_status") or ""),
                        "task_status": str(facts.get("task_status") or ""),
                        "protocol_status": str(facts.get("protocol_status") or ""),
                        "memory_written": bool(facts.get("memory_written")),
                        "state_updated": bool(facts.get("state_updated")),
                        "error": str(facts.get("error") or ""),
                        "technical_error": str(facts.get("technical_error") or ""),
                        "failure_kind": str(facts.get("failure_kind") or ""),
                    },
                },
            )
            save_conversation_turn(store, turn)
            self._append_conversation_turn_to_session(turn.turn_id, now=created)
            return turn.turn_id
        except Exception:
            return ""

    def _approval_context_for_conversation(self, approval_id: str) -> dict[str, Any]:
        if not approval_id:
            return {}
        try:
            return self._store().load_approval(approval_id)
        except Exception:
            return {}

    def _append_conversation_turn_to_session(self, turn_id: str, *, now: datetime) -> None:
        if not turn_id:
            return
        store = self._store()
        session = load_or_create_session(store, session_id=self.result.session_id, now=now)
        payload = session.to_payload()
        turn_ids = [str(item) for item in payload.get("conversation_turn_ids", []) if item]
        if turn_id not in turn_ids:
            turn_ids.append(turn_id)
        payload["conversation_turn_ids"] = turn_ids
        payload["updated_at"] = _datetime_timestamp(now)
        store.save_session(session.session_id, payload)

    def _perceive(self, value: str) -> None:
        try:
            options = _parse_perceive_args(value)
            result = perceive_once(
                project_root=self.project_root,
                provider=options.get("provider"),
                poll_url=options.get("poll_url"),
                poll_command=options.get("poll_command"),
                openchronicle_mcp_url=options.get("openchronicle_mcp_url"),
                openchronicle_since_minutes=options.get("openchronicle_since_minutes"),
                openchronicle_context_limit=options.get("openchronicle_context_limit"),
                allow_command_poll=options.get("allow_command_poll"),
                decide_on_change=options.get("decide_on_change"),
                timeout_seconds=options.get("timeout_seconds"),
            )
        except Exception as exc:
            self.print(f"error: {exc}")
            return
        artifact = result.artifact
        run_id = str(artifact.get("run_id") or "")
        if run_id:
            self.result.run_ids.append(run_id)
        self.result.turns += 1
        self.print(render_perception_panel(artifact))
        self.print(
            "\n".join(
                [
                    "Perception artifacts:",
                    f"  perception={result.perception_path}",
                    f"  state={result.state_path}",
                ]
            )
        )

    def _show_state(self) -> None:
        try:
            self.print(render_state_panel(self._store().load_state()))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_context(self, value: str = "") -> None:
        try:
            context = self._compile_debug_decision_context()
            payload = payload_value(context)
            if _context_json_requested(value):
                self.print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
                return
            self.print(_render_context_panel(payload))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_workspace(self, value: str = "") -> None:
        try:
            payload = compile_workspace_debug_payload(
                project_root=self.project_root,
                session_id=self.result.session_id,
            )
            if _context_json_requested(value):
                self.print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
                return
            self.print(render_workspace_debug_text(payload))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_sources(self, value: str = "") -> None:
        try:
            payload = compile_sources_debug_payload(
                project_root=self.project_root,
                session_id=self.result.session_id,
                run_id=_sources_run_id(value),
            )
            if _context_json_requested(value):
                self.print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
                return
            self.print(render_sources_debug_text(payload))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_latest_card(self, value: str = "") -> None:
        try:
            run_payload = self._load_run_for_command(value)
            compare = _mapping(run_payload.get("compare_payload"))
            if not compare:
                self.print("No Decision Card found for the selected run.")
                return
            self.print(
                render_decision_card(
                    compare,
                    use_bars=self.use_bars,
                    width=self._render_width(),
                )
            )
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_latest_why(self, value: str = "") -> None:
        try:
            run_payload = self._load_run_for_command(value)
            self.print(_render_why_summary(_mapping(run_payload.get("compare_payload"))))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_latest_simulation(self, value: str = "") -> None:
        try:
            run_payload = self._load_run_for_command(value)
            self.print(_render_simulation_summary(_mapping(run_payload.get("compare_payload"))))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_latest_json(self, value: str = "") -> None:
        try:
            if _execution_audit_target(value):
                payload = self._load_outcome_for_command(value)
                self.print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
                return
            run_payload = self._load_run_for_command(value)
            self.print(json.dumps(run_payload, ensure_ascii=False, sort_keys=True, indent=2))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_latest_execution_details(self, value: str = "") -> None:
        try:
            artifact = self._load_outcome_for_command(value)
            self.print(render_execution_panel(artifact, json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2)))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_session(self) -> None:
        try:
            session = load_or_create_session(self._store(), session_id=self.result.session_id)
            self.print(render_session_panel(session))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_timeline(self) -> None:
        try:
            session = load_or_create_session(self._store(), session_id=self.result.session_id)
            self.print(render_timeline_panel(build_session_timeline(self._store(), session), session_id=session.session_id))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _load_run_for_command(self, value: str = "") -> dict[str, Any]:
        run_id = value.strip()
        if not run_id:
            session = load_or_create_session(self._store(), session_id=self.result.session_id)
            run_id = str(session.last_run_id or "").strip()
        if not run_id:
            raise ValueError("No previous run is available. Type an intent first.")
        return self._store().load_run(run_id)

    def _load_outcome_for_command(self, value: str = "") -> dict[str, Any]:
        target = value.strip()
        if _latest_execution_alias(target):
            target = ""
        if target.startswith("outcome."):
            return self._store().load_outcome(target)
        if target.startswith("execution.") or target.startswith("exec."):
            return self._load_outcome_by_execution_id(target)
        if target:
            raise ValueError("Expected `execution`, an outcome id, or an execution id.")
        outcome_id = self._latest_outcome_id()
        if not outcome_id:
            raise ValueError("No previous execution outcome is available. Run /execute first.")
        return self._store().load_outcome(outcome_id)

    def _latest_outcome_id(self) -> str:
        store = self._store()
        session = load_or_create_session(store, session_id=self.result.session_id)
        metadata = _dict(session.metadata)
        outcome_id = str(metadata.get("last_outcome_id") or "").strip()
        if outcome_id:
            return outcome_id
        for turn_id in reversed(session.conversation_turn_ids):
            try:
                turn = store.load_conversation_turn(turn_id)
            except FileNotFoundError:
                continue
            outcome_id = str(turn.get("source_outcome_id") or "").strip()
            if outcome_id:
                return outcome_id
        run_id = str(session.last_run_id or "").strip()
        if run_id:
            try:
                run_payload = store.load_run(run_id)
            except FileNotFoundError:
                run_payload = {}
            outcome_id = str(run_payload.get("outcome_id") or "").strip()
            if outcome_id:
                return outcome_id
        outcome_ids = store.list_record_ids("outcomes")
        return outcome_ids[-1] if outcome_ids else ""

    def _load_outcome_by_execution_id(self, execution_id: str) -> dict[str, Any]:
        store = self._store()
        for outcome_id in reversed(store.list_record_ids("outcomes")):
            payload = store.load_outcome(outcome_id)
            if str(payload.get("execution_id") or "") == execution_id:
                return payload
        raise ValueError(f"No outcome found for execution id: {execution_id}")

    def _show_stats(self) -> None:
        try:
            self.print(render_stats_panel(session_stats(self._store())))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _show_approvals(self) -> None:
        try:
            self.print(render_approvals_panel(list_approvals(self._store())))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _open_pending_approval_flow(self, approval_id: str | None = None) -> None:
        if approval_id:
            try:
                approval = load_approval(self._store(), approval_id)
            except Exception as exc:
                self.print(f"error: {exc}")
                return
            if approval.status != "pending":
                self.print(f"Approval {approval_id} is not pending. Current status: {approval.status}.")
                if approval.status == "approved":
                    self.print(f"Run /execute {approval_id} to execute, or /details {approval_id} to inspect it.")
                return
            self._approval_action_menu(approval_id)
            return

        try:
            approvals = self._pending_approvals()
        except Exception as exc:
            self.print(f"error: {exc}")
            return
        if not approvals:
            self.print("No pending approvals.")
            return
        if len(approvals) == 1:
            selected = approvals[0].approval_id
            self.print(f"Pending approval: {selected}")
            self._approval_action_menu(selected)
            return
        selected = self._choose_pending_approval(approvals)
        if selected:
            self._approval_action_menu(selected)

    def _pending_approvals(self) -> list[Any]:
        return list_approvals(self._store(), status="pending")

    def _choose_pending_approval(self, approvals: list[Any]) -> str | None:
        if self._decision_action_picker_available():
            return self._prompt_pending_approval_choice(approvals)
        self.print(_pending_approval_choice_text(approvals))
        return None

    def _prompt_pending_approval_choice(self, approvals: list[Any]) -> str | None:
        rows = [
            (str(index), approval.approval_id, _approval_summary(approval))
            for index, approval in enumerate(approvals, start=1)
        ]
        try:
            raw = self._prompt_inline_choice(
                title="Which pending approval?",
                rows=rows,
                prompt_label="pending",
            )
        except Exception:
            return None
        value = str(raw or "").strip()
        if not value:
            return None
        if value.isdigit():
            index = int(value) - 1
            if 0 <= index < len(approvals):
                return str(approvals[index].approval_id)
        for approval in approvals:
            if value == approval.approval_id:
                return str(approval.approval_id)
        self.print(f"Unknown pending approval selection: {value}")
        return None

    def _approval_action_menu(self, approval_id: str) -> None:
        while True:
            if self._decision_action_picker_available():
                action = self._prompt_decision_action({"approval_id": approval_id})
                if not action:
                    self.print(_decision_next_step_text({"approval_id": approval_id}))
                    return
            else:
                self.print(_decision_next_step_text({"approval_id": approval_id}))
                return
            if self._handle_approval_action(action, approval_id):
                return

    def _show_approval_details(self, approval_id: str) -> None:
        if not approval_id:
            self.print("error: approval id required")
            return
        try:
            self.print(render_approval_details_panel(load_approval(self._store(), approval_id)))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _resolve_approval(self, approval_id: str, *, status: str, reason: str = "") -> bool:
        if not approval_id:
            self.print("error: approval id required")
            return False
        try:
            if status == "approved":
                resolved = approve_approval(self._store(), approval_id)
                self.result.approved_ids.append(approval_id)
            else:
                resolved = reject_approval(self._store(), approval_id, reason=reason)
                self.result.rejected_ids.append(approval_id)
            self._write_approval_evolution_memory(
                resolved.approval.to_payload(),
                status=status,
                reason=reason,
            )
            self.print(render_approval_resolution_panel(resolved))
            self._clear_pending_decision(approval_id)
            return True
        except Exception as exc:
            self.print(f"error: {exc}")
            return False

    def _execute_dry_run(self, approval_id: str) -> None:
        if not approval_id:
            self.print("error: approval id required")
            return
        try:
            execution = execute_dry_run_approval(approval_id, project_root=self.project_root)
            outcome_id = str(execution.artifact.get("outcome_id") or "")
            if outcome_id:
                self.result.dry_run_outcome_ids.append(outcome_id)
            self._write_execution_evolution_memory(execution.artifact)
            self.print(render_execution_panel(execution.artifact, execution.rendered_text))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _execute_configured(self, approval_id: str, *, permission_mode: str | None = None) -> None:
        if not approval_id:
            self.print("error: approval id required")
            return
        stream = TUIStreamWriter(
            console=self.console,
            output_stream=self.output_stream,
            status_title="SPICE EXECUTION",
        ).start()
        try:
            _stream_status(stream, "Checking approval...", f"approval={approval_id}")
            config = load_workspace_config(self.project_root)
            _stream_status(stream, "Resolving executor...", f"approval={approval_id}")
            executor = (
                resolve_executor_runtime_from_config_with_permission(config, permission_mode)
                if permission_mode
                else resolve_executor_runtime_from_config(config)
            )
            if permission_mode is None and executor.permission_enforcement == "command_flag":
                permission_mode = self._confirm_executor_permission_for_approval(approval_id)
                if permission_mode is None:
                    stream.finish("Execution paused.", "permission not granted")
                    return
                _stream_status(
                    stream,
                    "Resolving executor...",
                    f"{executor.executor_id}; permission={permission_mode}",
                )
                executor = resolve_executor_runtime_from_config_with_permission(
                    config,
                    permission_mode,
                )
            elif permission_mode is None and executor.permission_enforcement == "executor_policy":
                permission_mode = self._confirm_executor_permission_for_approval(approval_id)
                if permission_mode is None:
                    stream.finish("Execution paused.", "permission not granted")
                    return
            if executor.status == "unsupported":
                raise ValueError(executor.detail)
            if executor.status != "ready":
                raise ValueError(executor.detail)
            executor_name = _executor_loading_name(executor.executor_id)
            detail = f"{executor.executor_id}; approval={approval_id}"
            _stream_status(stream, f"Handing off to {executor_name}...", detail)
            _stream_status(stream, "Waiting for executor result...", detail)
            execution = self._run_configured_executor(approval_id, executor)
            outcome_id = str(execution.artifact.get("outcome_id") or "")
            _stream_status(stream, "Recording outcome...", outcome_id or f"approval={approval_id}")
            if outcome_id:
                self.result.dry_run_outcome_ids.append(outcome_id)
            self._write_execution_evolution_memory(execution.artifact)
            _stream_status(stream, "Composing response...", _runtime_model_detail(config.to_payload()))
            composed = self._compose_execution_response_result(
                execution.artifact,
                stream_callback=_stream_token_callback(stream),
            )
            response_text = composed.response_text
            response_blocks = [] if streamed_response_is_valid(composed.metadata) else _response_text_blocks(response_text)
            composed = _composer_result_with_streaming_metadata(composed, chunk_count=len(response_blocks))
            self._persist_execution_response_composer(execution.artifact, composed)
            self._write_execution_conversation_turn(
                execution.artifact,
                response_text=response_text,
                failed=False,
                composer_result=composed,
            )
            if streamed_response_is_valid(composed.metadata):
                _stream_write_text(stream, "\n\n")
            elif streamed_response_was_displayed(composed.metadata):
                stream.write_block("\nI need to correct that execution response after validating it:")
            for block in response_blocks:
                stream.write_block(block)
            stream.finish("Execution recorded.")
        except Exception as exc:
            provider = "executor"
            try:
                provider = resolve_executor_runtime_from_config(load_workspace_config(self.project_root)).executor_id
            except Exception:
                pass
            try:
                config_payload = load_workspace_config(self.project_root).to_payload()
            except Exception:
                config_payload = {}
            error_artifact = _execution_error_artifact(
                approval_id=approval_id,
                executor_provider=provider,
                error=exc,
                permission_mode=permission_mode,
            )
            _stream_status(stream, "Composing response...", _runtime_model_detail(config_payload))
            composed = self._compose_execution_error_response_result(
                error_artifact,
                stream_callback=_stream_token_callback(stream),
            )
            response_text = composed.response_text
            response_blocks = [] if streamed_response_is_valid(composed.metadata) else _response_text_blocks(response_text)
            composed = _composer_result_with_streaming_metadata(composed, chunk_count=len(response_blocks))
            self._write_execution_conversation_turn(
                error_artifact,
                response_text=response_text,
                failed=True,
                composer_result=composed,
            )
            stream.failed = True
            if streamed_response_is_valid(composed.metadata):
                _stream_write_text(stream, "\n\n")
            elif streamed_response_was_displayed(composed.metadata):
                stream.write_block("\nI need to correct that execution response after validating it:")
            for block in response_blocks:
                stream.write_block(block)
            stream.finish("Execution failed.")

    def _run_configured_executor(self, approval_id: str, executor: Any) -> Any:
        if executor.executor_id == "dry_run":
            return execute_dry_run_approval(approval_id, project_root=self.project_root)
        if executor.executor_id == "sdep_subprocess":
            return execute_sdep_subprocess_approval(
                approval_id,
                command=executor.command,
                project_root=self.project_root,
            )
        if executor.executor_id == "codex":
            return execute_codex_approval(
                approval_id,
                command=executor.command,
                project_root=self.project_root,
            )
        if executor.executor_id == "claude_code":
            return execute_claude_code_approval(
                approval_id,
                command=executor.command,
                project_root=self.project_root,
            )
        if executor.executor_id == "hermes":
            return execute_hermes_approval(
                approval_id,
                command=executor.command,
                project_root=self.project_root,
            )
        if executor.executor_id == "openclaw":
            return execute_openclaw_approval(
                approval_id,
                command=executor.command,
                project_root=self.project_root,
            )
        raise ValueError(f"Unsupported executor in .spice/config.json: {executor.executor_id!r}.")

    def _record_run(self, result: RunOnceResult) -> None:
        run_id = str(result.artifact.get("run_id") or "")
        if run_id:
            self.result.run_ids.append(run_id)
        self.result.turns += 1

    def _record_refine(self, result: RefineResult) -> None:
        run_id = str(result.artifact.get("run_id") or "")
        if run_id:
            self.result.run_ids.append(run_id)
        self.result.turns += 1

    def _artifacts_text(self, result: RunOnceResult) -> str:
        return _conversation_next_steps_text(has_approval=result.approval_path is not None)

    def _refine_artifacts_text(self, result: RefineResult) -> str:
        return _conversation_next_steps_text(has_approval=result.approval_path is not None)

    def _store(self) -> LocalJsonStore:
        if self.store is None:
            self.store = LocalJsonStore(require_workspace(self.project_root))
        return self.store

    def _memory_provider_or_none(self) -> Any:
        try:
            config = load_workspace_config(self.project_root)
            return load_workspace_memory_provider(self.project_root, config=config)
        except Exception:
            return None

    def _write_evolution_memory(self, record: dict[str, Any]) -> dict[str, Any]:
        provider = self._memory_provider_or_none()
        if provider is None:
            return skipped_general_evolution_memory_writeback(reason="memory_provider_not_configured")
        try:
            return write_general_evolution_memory(provider, record=record)
        except Exception as exc:
            return skipped_general_evolution_memory_writeback(reason=f"write_failed:{exc}")

    def _write_approval_evolution_memory(
        self,
        approval: dict[str, Any],
        *,
        status: str,
        reason: str = "",
    ) -> None:
        approval_id = str(approval.get("approval_id") or "")
        summary = f"Approval {approval_id} {status}".strip()
        self._write_evolution_memory(
            {
                "created_at": str(approval.get("resolved_at") or approval.get("requested_at") or ""),
                "session_id": self.result.session_id,
                "user_input": status,
                "route": "execution_request",
                "route_result": {
                    "route": "execution_request",
                    "action": f"approval_{status}",
                    "approval_id": approval_id,
                    "decision_id": str(approval.get("decision_id") or ""),
                    "candidate_id": str(approval.get("candidate_id") or ""),
                },
                "response_summary": summary,
                "decision_id": str(approval.get("decision_id") or ""),
                "candidate_id": str(approval.get("candidate_id") or ""),
                "approval_id": approval_id,
                "approval": approval,
                "follow_up_type": "approval_resolution",
                "artifact_refs": {
                    "approval": _workspace_relative(self._store().record_path("approval", approval_id))
                    if approval_id
                    else "",
                },
                "metadata": {
                    "generated_by": "spice.runtime.tui.shell",
                    "reason": reason,
                },
            }
        )

    def _write_execution_evolution_memory(self, execution: dict[str, Any]) -> None:
        approval_id = str(execution.get("approval_id") or "")
        outcome = _dict(execution.get("outcome_record"))
        task_status = str(execution.get("task_status") or "")
        protocol_status = str(execution.get("protocol_status") or "")
        self._write_evolution_memory(
            {
                "created_at": str(execution.get("created_at") or ""),
                "session_id": str(execution.get("session_id") or self.result.session_id),
                "user_input": f"execute {approval_id}".strip(),
                "route": "execution_request",
                "route_result": {
                    "route": "execution_request",
                    "action": "execution_result",
                    "approval_id": approval_id,
                    "decision_id": str(execution.get("decision_id") or ""),
                    "candidate_id": str(execution.get("candidate_id") or ""),
                    "outcome_id": str(execution.get("outcome_id") or ""),
                    "task_status": task_status,
                    "protocol_status": protocol_status,
                },
                "response_summary": _execution_response_summary(execution),
                "decision_id": str(execution.get("decision_id") or ""),
                "run_id": str(execution.get("run_id") or ""),
                "trace_ref": str(execution.get("trace_ref") or ""),
                "candidate_id": str(execution.get("candidate_id") or execution.get("selected_candidate_id") or ""),
                "approval_id": approval_id,
                "execution": execution,
                "outcome_id": str(execution.get("outcome_id") or outcome.get("outcome_id") or ""),
                "outcome": outcome,
                "follow_up_type": "execution_result",
                "artifact_refs": _dict(execution.get("store_paths")),
                "metadata": {
                    "generated_by": "spice.runtime.tui.shell",
                    "executor_provider": str(execution.get("executor_provider") or ""),
                },
            }
        )

    def _prompt_text(self) -> str:
        if self.pending_investigation is not None:
            return "investigation> "
        return "decision> " if self.pending_decision is not None else "spice> "

    def _set_pending_decision(self, artifact: dict[str, Any]) -> None:
        approval_id = str(artifact.get("approval_id") or "").strip()
        if not approval_id:
            self.pending_decision = None
            return
        self.pending_decision = {
            "approval_id": approval_id,
            "run_id": str(artifact.get("run_id") or ""),
            "decision_id": str(artifact.get("decision_id") or ""),
            "candidate_id": str(artifact.get("selected_candidate_id") or ""),
        }
        if self._decision_action_picker_available():
            self._show_decision_action_picker()
            return
        self.print(_decision_next_step_text(self.pending_decision))

    def _clear_pending_decision(self, approval_id: str | None = None) -> None:
        if self.pending_decision is None:
            return
        if approval_id is None or self.pending_decision.get("approval_id") == approval_id:
            self.pending_decision = None

    def _handle_decision_feedback(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        approval_id = str((self.pending_decision or {}).get("approval_id") or "")
        command, value = _split_first(text)
        normalized = command.lower()
        if normalized in {"y", "yes"}:
            self._approve_and_execute_pending(approval_id)
            return
        if normalized in {"a", "approve"}:
            self._resolve_approval(approval_id, status="approved")
            return
        if normalized in {"n", "no", "reject"}:
            self._resolve_approval(approval_id, status="rejected", reason=value)
            return
        if normalized in {"d", "detail", "details"}:
            self._show_approval_details(approval_id)
            return
        if normalized in {"q", "skip"}:
            self.print(f"Skipped pending decision: {approval_id}")
            self._clear_pending_decision(approval_id)
            return
        if normalized in {"r", "refine"} and value:
            self._refine_decision(value)
            return
        if normalized in {"r", "refine"}:
            self.print("error: refine requires feedback text")
            return
        resolution = self._resolve_continuation(text)
        if resolution.is_continuation:
            self._handle_continuation_resolution(resolution)
            return
        self._refine_decision(text)

    def _handle_continuation(self, line: str) -> bool:
        active_frame = self._active_decision_frame()
        if not active_frame:
            return False
        try:
            config = load_workspace_config(self.project_root).to_payload()
        except Exception:
            config = {}
        with TUIStatusFlow(
            console=self.console,
            title="SPICE",
            label="Reading the active decision...",
            detail=_runtime_model_detail(config),
        ) as status:
            status.update("Understanding your follow-up...", _runtime_model_detail(config))
            resolution, route_policy, gate = self._resolve_continuation_with_perception(
                line,
                active_frame=active_frame,
                config=config,
            )
            if not resolution.is_continuation:
                return False
            if self._block_for_pre_run_evidence_gate(gate, status=status):
                return True
            workspace_step = None
            url_step = None
            if gate.should_run_workspace_perception or gate.action == PRE_RUN_EVIDENCE_RUN_WORKSPACE_PERCEPTION:
                status.update(_workspace_evidence_status_label(), _runtime_model_detail(config))
                workspace_step = self._run_workspace_perception_step(
                    query=resolution.workspace_query or line,
                    trigger=f"follow_up:{resolution.action}",
                    config=config,
                    route_policy=route_policy,
                )
            gate = evaluate_pre_run_evidence_gate(
                route_policy,
                workspace_context=_workspace_context_from_step(workspace_step),
                url_context=None,
                delegated_perception_context=None,
            )
            if self._block_for_pre_run_evidence_gate(gate, status=status):
                return True
            if (
                gate.action != PRE_RUN_EVIDENCE_RUN_URL_PERCEPTION
                and self._block_if_required_evidence_is_still_missing(gate, status=status)
            ):
                return True
            if gate.should_run_url_perception or gate.action == PRE_RUN_EVIDENCE_RUN_URL_PERCEPTION:
                status.update(_url_evidence_status_label(), _runtime_model_detail(config))
                url_step = self._run_url_perception_step(
                    text=line,
                    urls=resolution.urls,
                    query=resolution.url_query or line,
                    trigger=f"follow_up:{resolution.action}",
                )
            gate = evaluate_pre_run_evidence_gate(
                route_policy,
                workspace_context=_workspace_context_from_step(workspace_step),
                url_context=_url_context_from_step(url_step),
                delegated_perception_context=None,
            )
            if self._block_if_required_evidence_is_still_missing(gate, status=status):
                return True
            escalation = self._delegated_escalation_for_route(
                resolution,
                config=config,
                workspace_context=_workspace_context_from_step(workspace_step),
                workspace_perception=_workspace_artifact_from_step(workspace_step),
                url_context=_url_context_from_step(url_step),
                url_perception=_url_artifact_from_step(url_step),
            )
            if self._should_pause_for_delegated_escalation(escalation):
                status.finish(_delegated_escalation_finish_label(escalation))
                self._open_investigation_consent_from_escalation(
                    escalation,
                    route_payload=resolution.to_payload(),
                    user_input=line,
                    trigger=f"follow_up:{resolution.action}",
                    workspace_perception=_workspace_artifact_from_step(workspace_step),
                    url_perception=_url_artifact_from_step(url_step),
                )
                return True
            status.finish("Ready.")
        self._handle_continuation_resolution(
            resolution,
            workspace_context=_workspace_context_from_step(workspace_step),
            workspace_perception=_workspace_artifact_from_step(workspace_step),
            url_context=_url_context_from_step(url_step),
            url_perception=_url_artifact_from_step(url_step),
            delegated_perception_context=None,
            delegated_perception=None,
        )
        return True

    def _resolve_continuation(
        self,
        line: str,
        *,
        active_frame: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> ContinuationResolution:
        resolution, _, _ = self._resolve_continuation_with_perception(
            line,
            active_frame=active_frame,
            config=config,
        )
        return resolution

    def _resolve_continuation_with_perception(
        self,
        line: str,
        *,
        active_frame: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> tuple[ContinuationResolution, RouteMergePolicy, PreRunEvidenceGateDecision]:
        if config is None:
            try:
                config = load_workspace_config(self.project_root).to_payload()
            except Exception:
                config = {}
        route = route_semantic_input_from_runtime_config(
            line,
            active_frame if active_frame is not None else self._active_decision_frame(),
            config=config,
        )
        route, policy, gate = self._merge_runtime_perception_route(line, route)
        return semantic_route_to_continuation(route), policy, gate

    def _run_workspace_perception_step(
        self,
        *,
        query: str,
        trigger: str,
        config: Mapping[str, Any],
        route_policy: RouteMergePolicy | None = None,
    ) -> RuntimeWorkspacePerceptionResult:
        return run_runtime_workspace_perception_step(
            project_root=self.project_root,
            query=query,
            config=config,
            trigger=trigger,
            store=self._store(),
            persist=self.persist,
            initial_context={
                "session_id": self.result.session_id,
                "active_decision_frame": self._active_decision_frame(),
                "route_merge_policy": route_policy.to_payload() if route_policy is not None else {},
            },
        )

    def _run_url_perception_step(
        self,
        *,
        text: str,
        urls: list[str] | None,
        query: str,
        trigger: str,
    ) -> RuntimeURLPerceptionResult:
        return run_runtime_url_perception_step(
            project_root=self.project_root,
            text=text,
            urls=urls,
            query=query,
            trigger=trigger,
            store=self._store(),
            persist=self.persist,
        )

    def _delegated_escalation_for_route(
        self,
        route: Any,
        *,
        config: Mapping[str, Any],
        workspace_context: Mapping[str, Any] | None = None,
        workspace_perception: Mapping[str, Any] | None = None,
        url_context: Mapping[str, Any] | None = None,
        url_perception: Mapping[str, Any] | None = None,
    ) -> RuntimeEscalationDecision | None:
        try:
            return decide_runtime_escalation(
                route,
                config=config,
                workspace_context=workspace_context,
                workspace_perception=workspace_perception,
                url_context=url_context,
                url_perception=url_perception,
            )
        except Exception:
            return None

    def _should_pause_for_delegated_escalation(
        self,
        escalation: RuntimeEscalationDecision | None,
    ) -> bool:
        if escalation is None:
            return False
        return escalation.action in {
            ESCALATION_CREATE_INVESTIGATION_CONSENT,
            ESCALATION_AWAIT_INVESTIGATION_CONSENT,
            ESCALATION_RUN_DELEGATED_PERCEPTION,
            ESCALATION_BLOCKED,
        }

    def _open_investigation_consent_from_escalation(
        self,
        escalation: RuntimeEscalationDecision | None,
        *,
        route_payload: Mapping[str, Any],
        user_input: str,
        trigger: str,
        workspace_perception: Mapping[str, Any] | None = None,
        url_perception: Mapping[str, Any] | None = None,
    ) -> None:
        if escalation is None:
            return
        if escalation.action == ESCALATION_BLOCKED:
            self.pending_investigation = None
            self.print(_investigation_blocked_text(escalation))
            return
        if escalation.action == ESCALATION_RUN_DELEGATED_PERCEPTION:
            self.pending_investigation = None
            consent_id = str(escalation.consent_id or "").strip()
            if consent_id:
                try:
                    consent = InvestigationConsent.from_payload(
                        self._store().load_investigation_consent(consent_id)
                    )
                    self._run_granted_investigation_handoff(
                        consent,
                        pending={
                            "route_payload": dict(route_payload or {}),
                            "user_input": user_input,
                            "trigger": trigger,
                            "escalation": escalation.to_payload(),
                        },
                    )
                    return
                except Exception as exc:
                    self.print(f"Read-only investigation handoff failed: {exc}")
                    return
            self.print(_investigation_granted_ready_text(escalation))
            return
        if escalation.action == ESCALATION_AWAIT_INVESTIGATION_CONSENT:
            consent_id = str(escalation.consent_id or "").strip()
            if consent_id:
                try:
                    consent = InvestigationConsent.from_payload(
                        self._store().load_investigation_consent(consent_id)
                    )
                    self._set_pending_investigation(
                        consent,
                        escalation=escalation,
                        route_payload=route_payload,
                        user_input=user_input,
                        trigger=trigger,
                    )
                    self.print(_investigation_consent_text(consent, escalation))
                    self._show_investigation_action_picker_if_available()
                    return
                except Exception:
                    pass
            self.print(_investigation_blocked_text(escalation))
            return
        if escalation.action != ESCALATION_CREATE_INVESTIGATION_CONSENT:
            return
        try:
            consent = build_investigation_consent_for_escalation(
                escalation,
                input_context_refs=self._investigation_input_context_refs(
                    workspace_perception=workspace_perception,
                    url_perception=url_perception,
                ),
            )
        except Exception as exc:
            self.pending_investigation = None
            self.print(f"Could not create investigation consent: {exc}")
            return
        if self.persist:
            self._store().save_investigation_consent(consent.consent_id, consent.to_payload())
        turn_id = self._write_investigation_conversation_turn(
            consent,
            escalation=escalation,
            route_payload=route_payload,
            user_input=user_input,
            trigger=trigger,
            status="pending",
        )
        self._set_pending_investigation(
            consent,
            escalation=escalation,
            route_payload=route_payload,
            user_input=user_input,
            trigger=trigger,
            turn_id=turn_id,
        )
        self.result.turns += 1
        self.print(_investigation_consent_text(consent, escalation))
        self._show_investigation_action_picker_if_available()

    def _set_pending_investigation(
        self,
        consent: InvestigationConsent,
        *,
        escalation: RuntimeEscalationDecision | None = None,
        route_payload: Mapping[str, Any] | None = None,
        user_input: str = "",
        trigger: str = "",
        turn_id: str = "",
    ) -> None:
        self.pending_investigation = {
            "consent_id": consent.consent_id,
            "executor_id": consent.executor_id,
            "query": consent.query,
            "trigger": trigger,
            "user_input": user_input,
            "turn_id": turn_id,
            "route_payload": dict(route_payload or {}),
            "escalation": escalation.to_payload() if escalation is not None else {},
        }

    def _handle_investigate_command(self, value: str = "") -> None:
        action, rest = _split_first(value.strip())
        normalized = action.lower()
        if normalized in {"y", "yes", "grant", "approve", "continue", "go"}:
            self._resolve_pending_investigation(status=INVESTIGATION_CONSENT_GRANTED)
            return
        if normalized in {"n", "no", "reject", "cancel"}:
            self._resolve_pending_investigation(
                status=INVESTIGATION_CONSENT_REJECTED,
                reason=rest or "rejected from /investigate",
            )
            return
        if normalized in {"d", "detail", "details"}:
            self._show_pending_investigation_details()
            return
        consent_id = action.strip()
        if consent_id:
            self._show_investigation_consent_details(consent_id)
            return
        if self.pending_investigation is not None:
            if self._show_investigation_action_picker_if_available():
                return
            self._show_pending_investigation_details()
            return
        pending = self._pending_investigation_consents()
        if not pending:
            self.print("No pending read-only investigation consent.")
            return
        consent = pending[-1]
        self._set_pending_investigation(
            consent,
            route_payload={},
            user_input=consent.query,
            trigger="investigate_command",
        )
        self.print(_investigation_consent_text(consent, None))
        self._show_investigation_action_picker_if_available()

    def _handle_investigation_feedback(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        command, value = _split_first(text)
        action = _normalize_investigation_action(command)
        if action == "grant":
            self._resolve_pending_investigation(status=INVESTIGATION_CONSENT_GRANTED)
            return
        if action == "reject":
            self._resolve_pending_investigation(
                status=INVESTIGATION_CONSENT_REJECTED,
                reason=value or "rejected by user",
            )
            return
        if action == "details":
            self._show_pending_investigation_details()
            return
        if action == "skip":
            consent_id = str((self.pending_investigation or {}).get("consent_id") or "")
            self.print(f"Skipped pending read-only investigation consent: {consent_id}")
            self.pending_investigation = None
            return
        self.print(
            "Use up/down then Enter, or type `yes` to allow the read-only investigation, "
            "`no` to reject, `details` to inspect, or `skip` to leave it pending."
        )

    def _show_investigation_action_picker_if_available(self) -> bool:
        if self.pending_investigation is None:
            return False
        if not self._decision_action_picker_available():
            return False
        self._show_investigation_action_picker()
        return True

    def _show_investigation_action_picker(self) -> None:
        while self.pending_investigation is not None:
            action = self._prompt_investigation_action(self.pending_investigation)
            if not action:
                self.print(_investigation_next_step_text(self.pending_investigation))
                return
            if self._handle_investigation_action(action):
                return

    def _prompt_investigation_action(self, pending: dict[str, Any]) -> str:
        consent_id = str(pending.get("consent_id") or "")
        executor_id = str(pending.get("executor_id") or "configured executor")
        rows = [(value, label, shortcut) for value, label, shortcut in _investigation_action_options(executor_id)]
        footer = (
            f"consent_id: {consent_id}\n"
            "scope: read-only investigation; no execution approval"
        )
        try:
            result = self._prompt_inline_choice(
                title="What would you like to do?",
                rows=rows,
                footer=footer,
                prompt_label="investigation",
            )
        except (EOFError, KeyboardInterrupt):
            return ""
        except Exception:
            return ""
        return _normalize_investigation_action(str(result or ""))

    def _handle_investigation_action(self, action: str) -> bool:
        normalized = _normalize_investigation_action(action)
        if normalized == "grant":
            self._resolve_pending_investigation(status=INVESTIGATION_CONSENT_GRANTED)
            return True
        if normalized == "reject":
            reason = self._prompt_free_text("reject reason> ")
            if reason is None:
                self.print("Reject cancelled.")
                return False
            self._resolve_pending_investigation(
                status=INVESTIGATION_CONSENT_REJECTED,
                reason=reason or "rejected by user",
            )
            return True
        if normalized == "details":
            self._show_pending_investigation_details()
            return False
        if normalized == "skip":
            consent_id = str((self.pending_investigation or {}).get("consent_id") or "")
            self.print(f"Skipped pending read-only investigation consent: {consent_id}")
            self.pending_investigation = None
            return True
        return False

    def _resolve_pending_investigation(self, *, status: str, reason: str = "") -> None:
        pending = dict(self.pending_investigation or {})
        consent_id = str(pending.get("consent_id") or "").strip()
        if not consent_id:
            self.print("No pending read-only investigation consent.")
            return
        try:
            consent = InvestigationConsent.from_payload(
                self._store().load_investigation_consent(consent_id)
            )
            resolved = resolve_investigation_consent(
                consent,
                status=status,
                reason=reason,
            )
            if self.persist:
                self._store().save_investigation_consent(consent_id, resolved.to_payload())
            self._write_investigation_conversation_turn(
                resolved,
                escalation_payload=_mapping(pending.get("escalation")),
                route_payload=_mapping(pending.get("route_payload")),
                user_input=str(pending.get("user_input") or ""),
                trigger=str(pending.get("trigger") or "investigation_consent"),
                status=status,
            )
            self.pending_investigation = None
            if status == INVESTIGATION_CONSENT_GRANTED:
                self.print(_investigation_granted_text(resolved))
                self._run_granted_investigation_handoff(resolved, pending=pending)
            else:
                self.print(_investigation_rejected_text(resolved))
        except Exception as exc:
            self.print(f"error: {exc}")

    def _run_granted_investigation_handoff(
        self,
        consent: InvestigationConsent,
        *,
        pending: Mapping[str, Any],
    ) -> None:
        store = self._store()
        route_payload = _mapping(pending.get("route_payload"))
        if not route_payload:
            route_payload = {
                "route": "follow_up",
                "action": "answer_from_decision",
                "context_strategy": "delegated",
                "needs_delegated_perception": True,
                "delegated_perception_query": consent.query,
                "suggested_capabilities": list(
                    _list(_mapping(consent.metadata).get("suggested_capabilities"))
                )
                or ["web_research"],
            }
        escalation_payload = _mapping(pending.get("escalation"))
        if escalation_payload.get("action") != ESCALATION_RUN_DELEGATED_PERCEPTION:
            config_payload = config_with_executor_capability_snapshot(
                load_workspace_config(self.project_root)
            )
            escalation = decide_runtime_escalation(
                route_payload,
                config=config_payload,
                executor_capabilities=_mapping(config_payload.get("executor_capabilities")),
                investigation_consent=consent,
            )
            if escalation.action != ESCALATION_RUN_DELEGATED_PERCEPTION:
                self.print(_investigation_blocked_text(escalation))
                return
            escalation_payload = escalation.to_payload()

        session = load_or_create_session(store, session_id=self.result.session_id)
        frame = self._active_decision_frame()
        workspace_context = latest_workspace_context_from_store(store, session, active_frame=frame)
        url_context = latest_url_context_from_store(store, session, active_frame=frame)
        delegated_context = latest_delegated_perception_context_from_store(
            store,
            session,
            active_frame=frame,
        )
        user_input = str(pending.get("user_input") or consent.query)
        turn_id = str(pending.get("turn_id") or "")
        with TUIStatusFlow(
            console=self.console,
            title="SPICE",
            label="Preparing read-only investigation...",
            detail=consent.executor_id,
        ) as status_flow:
            status_flow.update("Checking executor and permissions...", consent.executor_id)
            status_flow.update("Handing off for read-only investigation...", consent.executor_id)
            result = run_delegated_perception_handoff(
                project_root=self.project_root,
                store=store,
                consent=consent,
                escalation_decision=escalation_payload,
                route_payload=route_payload,
                user_input=user_input,
                active_decision_frame=frame,
                workspace_context=workspace_context or None,
                url_context=url_context or None,
                delegated_perception_context=delegated_context or None,
                input_context_refs=consent.input_context_refs,
                conversation_turn_id=turn_id,
                persist=self.persist,
            )
            status_flow.update("Recording findings...", consent.executor_id)
            status_flow.finish(
                "Investigation recorded."
                if result.status == "completed"
                else "Investigation fallback recorded."
            )
        self.print(_investigation_handoff_result_text(result))
        if result.status != "completed" and not workspace_context:
            fallback = self._run_workspace_perception_step(
                query=consent.query,
                trigger="delegated_perception_fallback",
                config=load_workspace_config(self.project_root).to_payload(),
            )
            self.print(_local_perception_fallback_text(fallback))

    def _pending_investigation_consents(self) -> list[InvestigationConsent]:
        consents: list[InvestigationConsent] = []
        for consent_id in self._store().list_record_ids("investigations"):
            try:
                consent = InvestigationConsent.from_payload(
                    self._store().load_investigation_consent(consent_id)
                )
            except Exception:
                continue
            if consent.status == INVESTIGATION_CONSENT_PENDING:
                consents.append(consent)
        return consents

    def _show_pending_investigation_details(self) -> None:
        consent_id = str((self.pending_investigation or {}).get("consent_id") or "")
        if not consent_id:
            self.print("No pending read-only investigation consent.")
            return
        self._show_investigation_consent_details(consent_id)

    def _show_investigation_consent_details(self, consent_id: str) -> None:
        try:
            consent = InvestigationConsent.from_payload(
                self._store().load_investigation_consent(consent_id)
            )
        except Exception as exc:
            self.print(f"error: {exc}")
            return
        self.print(_investigation_consent_details_text(consent))

    def _investigation_input_context_refs(
        self,
        *,
        workspace_perception: Mapping[str, Any] | None,
        url_perception: Mapping[str, Any] | None,
    ) -> list[str]:
        refs: list[str] = []
        frame = self._active_decision_frame()
        for prefix, value in (
            ("decision", frame.get("decision_id") if frame else ""),
            ("run", frame.get("run_id") if frame else ""),
            ("workspace_perception", _mapping(workspace_perception).get("perception_id")),
            ("url_perception", _mapping(url_perception).get("perception_id")),
        ):
            text = str(value or "").strip()
            if text:
                refs.append(f"{prefix}:{text}")
        return refs

    def _write_investigation_conversation_turn(
        self,
        consent: InvestigationConsent,
        *,
        escalation: RuntimeEscalationDecision | None = None,
        escalation_payload: Mapping[str, Any] | None = None,
        route_payload: Mapping[str, Any] | None = None,
        user_input: str,
        trigger: str,
        status: str,
    ) -> str:
        if not self.persist:
            return ""
        try:
            now = datetime.now(timezone.utc)
            payload = dict(route_payload or {})
            escalation_data = (
                escalation.to_payload()
                if escalation is not None
                else dict(escalation_payload or {})
            )
            turn = build_conversation_turn(
                user_input=user_input or consent.query,
                route=_conversation_route_from_payload(payload, trigger=trigger),
                session_id=self.result.session_id,
                created_at=now,
                artifact_refs={
                    "investigation_consent": _workspace_relative(
                        self._store().record_path("investigation", consent.consent_id)
                    )
                },
                metadata={
                    "generated_by": "spice.runtime.tui.shell",
                    "follow_up_type": "investigation_consent",
                    "investigation_consent": consent.to_payload(),
                    "investigation_status": status,
                    "route_result": payload,
                    "context_strategy": str(
                        payload.get("context_strategy")
                        or escalation_data.get("context_strategy")
                        or ""
                    ),
                    "escalation": escalation_data,
                },
            )
            save_conversation_turn(self._store(), turn)
            self._append_conversation_turn_to_session(turn.turn_id, now=now)
            return turn.turn_id
        except Exception:
            return ""

    def _handle_continuation_resolution(
        self,
        resolution: ContinuationResolution,
        *,
        workspace_context: Mapping[str, Any] | None = None,
        workspace_perception: Mapping[str, Any] | None = None,
        url_context: Mapping[str, Any] | None = None,
        url_perception: Mapping[str, Any] | None = None,
        delegated_perception_context: Mapping[str, Any] | None = None,
        delegated_perception: Mapping[str, Any] | None = None,
    ) -> None:
        action = resolution.action
        if action == "choose_option":
            guardrail = self._validate_active_frame_route(action, candidate_id=resolution.candidate_id)
            if not guardrail.allowed:
                self.print(render_guardrail_message(guardrail))
                return
            self._choose_active_frame_option(resolution)
            return
        if action == "execute_selected":
            guardrail = self._validate_active_frame_route(action, candidate_id=resolution.candidate_id)
            if not guardrail.allowed:
                self.print(render_guardrail_message(guardrail))
                return
            self._execute_active_frame_selected(
                candidate_id=guardrail.candidate_id or resolution.candidate_id,
                user_input=resolution.text,
            )
            return
        if action == "approve_execute":
            guardrail = self._validate_active_frame_route(action, candidate_id=resolution.candidate_id)
            if not guardrail.allowed:
                self.print(render_guardrail_message(guardrail))
                return
            approval_id = self._active_frame_approval_id()
            if approval_id:
                self._approve_and_execute_pending(approval_id)
                return
            self.print("No approval is attached to the current Decision Card. Type `execute selected` to open an execution handoff.")
            return
        if action == "approve_only":
            guardrail = self._validate_active_frame_route(action, candidate_id=resolution.candidate_id)
            if not guardrail.allowed:
                self.print(render_guardrail_message(guardrail))
                return
            approval_id = self._active_frame_approval_id()
            if approval_id:
                self._resolve_approval(approval_id, status="approved")
                return
            self.print("No approval is attached to the current Decision Card. Type `execute selected` to open an execution handoff.")
            return
        if action == "show_details":
            approval_id = self._active_frame_approval_id()
            if approval_id:
                self._show_approval_details(approval_id)
            else:
                self._show_latest_card()
            return
        if action == "explain_why_not":
            self._answer_why_not_follow_up(
                resolution,
                workspace_context=workspace_context,
                workspace_perception=workspace_perception,
                url_context=url_context,
                url_perception=url_perception,
                delegated_perception_context=delegated_perception_context,
                delegated_perception=delegated_perception,
            )
            return
        if action == "plan_candidate":
            self._answer_plan_follow_up(
                resolution,
                workspace_context=workspace_context,
                workspace_perception=workspace_perception,
                url_context=url_context,
                url_perception=url_perception,
                delegated_perception_context=delegated_perception_context,
                delegated_perception=delegated_perception,
            )
            return
        if action in {"answer_from_decision", "compare_alternative", "ask_clarifying_question"}:
            self._answer_general_follow_up(
                resolution,
                workspace_context=workspace_context,
                workspace_perception=workspace_perception,
                url_context=url_context,
                url_perception=url_perception,
                delegated_perception_context=delegated_perception_context,
                delegated_perception=delegated_perception,
            )
            return
        if action == "skip":
            self._mark_active_frame_status("skipped")
            self.print("Skipped current Decision Card.")
            self.pending_decision = None
            return
        if action in {"refine", "refine_decision"}:
            if (
                workspace_context
                or workspace_perception
                or url_context
                or url_perception
                or delegated_perception_context
                or delegated_perception
            ):
                self._refine_decision(
                    resolution.text,
                    workspace_context=workspace_context,
                    workspace_perception=workspace_perception,
                    url_context=url_context,
                    url_perception=url_perception,
                    delegated_perception_context=delegated_perception_context,
                    delegated_perception=delegated_perception,
                )
            else:
                self._refine_decision(resolution.text)
            return
        self.print(f"Could not continue from current Decision Card: {resolution.text}")

    def _validate_active_frame_route(self, action: str, *, candidate_id: str = "") -> Any:
        try:
            config = load_workspace_config(self.project_root).to_payload()
        except Exception:
            config = {}
        return validate_active_frame_route(
            action=action,
            active_frame=self._active_decision_frame(),
            candidate_id=candidate_id,
            config=config,
        )

    def _answer_why_not_follow_up(
        self,
        resolution: ContinuationResolution,
        *,
        workspace_context: Mapping[str, Any] | None = None,
        workspace_perception: Mapping[str, Any] | None = None,
        url_context: Mapping[str, Any] | None = None,
        url_perception: Mapping[str, Any] | None = None,
        delegated_perception_context: Mapping[str, Any] | None = None,
        delegated_perception: Mapping[str, Any] | None = None,
    ) -> None:
        stream: TUIStreamWriter | None = None
        try:
            config = load_workspace_config(self.project_root).to_payload()
            stream = TUIStreamWriter(
                console=self.console,
                output_stream=self.output_stream,
                status_title="SPICE",
            ).start()
            _stream_status(stream, "Explaining the tradeoff...", _runtime_model_detail(config))
            source_run = self._load_run_for_command()
            context_payload = build_composer_context_payload(
                project_root=self.project_root,
                session_id=self.result.session_id,
                latest_artifact=source_run,
            )
            context_payload = _with_workspace_context(context_payload, workspace_context)
            context_payload = _with_url_context(context_payload, url_context)
            context_payload = _with_delegated_perception_context(context_payload, delegated_perception_context)
            result = answer_why_not_candidate(
                store=self._store(),
                session_id=self.result.session_id,
                user_input=resolution.text,
                source_run=source_run,
                candidate_id=resolution.candidate_id,
                config=config,
                context_payload=context_payload,
                memory_provider=self._memory_provider_or_none(),
                stream_callback=_stream_token_callback(stream),
            )
        except Exception as exc:
            if stream is not None:
                _stream_fail(stream, f"error: {exc}")
            else:
                self.print(f"error: {exc}")
            return
        self.result.turns += 1
        self._persist_follow_up_streaming_metadata(_mapping(getattr(result, "artifact", {})))
        composer_metadata = _follow_up_composer_metadata(_mapping(getattr(result, "artifact", {})))
        if streamed_response_is_valid(composer_metadata):
            _stream_write_text(stream, "\n\n")
        else:
            if streamed_response_was_displayed(composer_metadata):
                stream.write_block("\nI need to correct that response after validating it:")
            for block in _response_text_blocks(result.rendered_text):
                stream.write_block(block)
        stream.finish("Ready.")

    def _answer_plan_follow_up(
        self,
        resolution: ContinuationResolution,
        *,
        workspace_context: Mapping[str, Any] | None = None,
        workspace_perception: Mapping[str, Any] | None = None,
        url_context: Mapping[str, Any] | None = None,
        url_perception: Mapping[str, Any] | None = None,
        delegated_perception_context: Mapping[str, Any] | None = None,
        delegated_perception: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            config = load_workspace_config(self.project_root).to_payload()
            with TUIStatusFlow(console=self.console, title="SPICE", label="Drafting the plan...") as status:
                source_run = self._load_run_for_command()
                context_payload = build_composer_context_payload(
                    project_root=self.project_root,
                    session_id=self.result.session_id,
                    latest_artifact=source_run,
                )
                context_payload = _with_workspace_context(context_payload, workspace_context)
                context_payload = _with_url_context(context_payload, url_context)
                context_payload = _with_delegated_perception_context(context_payload, delegated_perception_context)
                result = answer_candidate_plan(
                    store=self._store(),
                    session_id=self.result.session_id,
                    user_input=resolution.text,
                    source_run=source_run,
                    candidate_id=resolution.candidate_id,
                    config=config,
                    context_payload=context_payload,
                    memory_provider=self._memory_provider_or_none(),
                )
                status.finish("Ready.")
        except Exception as exc:
            self.print(f"error: {exc}")
            return
        self.result.turns += 1
        self._persist_follow_up_streaming_metadata(_mapping(getattr(result, "artifact", {})))
        self._stream_response_text(result.rendered_text)

    def _answer_general_follow_up(
        self,
        resolution: ContinuationResolution,
        *,
        workspace_context: Mapping[str, Any] | None = None,
        workspace_perception: Mapping[str, Any] | None = None,
        url_context: Mapping[str, Any] | None = None,
        url_perception: Mapping[str, Any] | None = None,
        delegated_perception_context: Mapping[str, Any] | None = None,
        delegated_perception: Mapping[str, Any] | None = None,
    ) -> None:
        stream: TUIStreamWriter | None = None
        try:
            config = load_workspace_config(self.project_root).to_payload()
            stream = TUIStreamWriter(
                console=self.console,
                output_stream=self.output_stream,
                status_title="SPICE",
            ).start()
            _stream_status(stream, "Composing answer...", _runtime_model_detail(config))
            source_run = self._load_run_for_command()
            context_payload = build_composer_context_payload(
                project_root=self.project_root,
                session_id=self.result.session_id,
                latest_artifact=source_run,
            )
            context_payload = _with_workspace_context(context_payload, workspace_context)
            context_payload = _with_url_context(context_payload, url_context)
            context_payload = _with_delegated_perception_context(context_payload, delegated_perception_context)
            result = answer_general_follow_up(
                store=self._store(),
                session_id=self.result.session_id,
                user_input=resolution.text,
                source_run=source_run,
                action=resolution.action,
                candidate_id=resolution.candidate_id,
                config=config,
                context_payload=context_payload,
                memory_provider=self._memory_provider_or_none(),
                stream_callback=_stream_token_callback(stream),
            )
        except Exception as exc:
            if stream is not None:
                _stream_fail(stream, f"error: {exc}")
            else:
                self.print(f"error: {exc}")
            return
        self.result.turns += 1
        self._persist_follow_up_streaming_metadata(_mapping(getattr(result, "artifact", {})))
        composer_metadata = _follow_up_composer_metadata(_mapping(getattr(result, "artifact", {})))
        if streamed_response_is_valid(composer_metadata):
            _stream_write_text(stream, "\n\n")
        else:
            if streamed_response_was_displayed(composer_metadata):
                stream.write_block("\nI need to correct that response after validating it:")
            for block in _response_text_blocks(result.rendered_text):
                stream.write_block(block)
        stream.finish("Ready.")

    def _persist_follow_up_streaming_metadata(self, artifact: dict[str, Any]) -> None:
        if not artifact:
            return
        composer_metadata = _follow_up_composer_metadata(artifact)
        streaming = dict(composer_metadata.get("streaming") or {})
        if not streaming:
            streaming = _streaming_metadata_for_chunk_count(
                len(_response_text_blocks(str(artifact.get("rendered_text") or "")))
            )
        artifact["streaming"] = dict(streaming)
        evidence = _mapping(artifact.get("evidence"))
        composer = _mapping(evidence.get("composer_result"))
        if composer:
            metadata = _mapping(composer.get("metadata"))
            metadata["streaming"] = dict(streaming)
            composer["metadata"] = metadata
            evidence["composer_result"] = composer
            artifact["evidence"] = evidence
        turn_id = str(artifact.get("turn_id") or "")
        if not turn_id:
            return
        try:
            store = self._store()
            turn = store.load_conversation_turn(turn_id)
            metadata = _mapping(turn.get("metadata"))
            follow_up = _mapping(metadata.get("follow_up_response"))
            follow_up["streaming"] = dict(streaming)
            follow_up_evidence = _mapping(follow_up.get("evidence"))
            follow_up_composer = _mapping(follow_up_evidence.get("composer_result"))
            if follow_up_composer:
                composer_metadata = _mapping(follow_up_composer.get("metadata"))
                composer_metadata["streaming"] = dict(streaming)
                follow_up_composer["metadata"] = composer_metadata
                follow_up_evidence["composer_result"] = follow_up_composer
                follow_up["evidence"] = follow_up_evidence
            metadata["follow_up_response"] = follow_up
            turn["metadata"] = metadata
            store.save_conversation_turn(turn_id, turn)
        except Exception:
            return

    def _choose_active_frame_option(self, resolution: ContinuationResolution) -> None:
        frame = self._active_decision_frame()
        if not frame:
            self.print("No active Decision Card to choose from.")
            return
        updated = update_frame_selected_candidate(frame, resolution.candidate_id)
        if updated == frame:
            self.print(f"Could not find option {resolution.label}.")
            return
        self._save_active_decision_frame(updated)
        selected = updated.get("selected") if isinstance(updated.get("selected"), dict) else {}
        self.pending_decision = None
        title = str(selected.get("title") or selected.get("recommended_action") or resolution.label)
        self.print(
            "\n".join(
                [
                    f"Selected {selected.get('label') or resolution.label}: {title}",
                    f"candidate_id: {selected.get('candidate_id') or resolution.candidate_id}",
                    _selected_candidate_next_action_text(selected, updated),
                ]
            )
        )

    def _execute_active_frame_selected(self, *, candidate_id: str = "", user_input: str = "") -> None:
        approval_id = self._active_frame_approval_id()
        if approval_id:
            self._approve_and_execute_pending(approval_id)
            return
        frame = self._active_decision_frame()
        if not frame:
            self.print("No active Decision Card to execute.")
            return
        try:
            with TUIStatusFlow(
                console=self.console,
                title="SPICE APPROVAL",
                label="Reading the selected option...",
            ) as status:
                status.update("Checking executor and permissions...")
                status.update("Creating pending approval...")
                result = open_execution_approval_from_frame(
                    store=self._store(),
                    session_id=self.result.session_id,
                    user_input=user_input or "execute selected",
                    active_frame=frame,
                    candidate_id=candidate_id,
                    memory_provider=self._memory_provider_or_none(),
                )
                status.finish("Approval ready.")
        except Exception as exc:
            self.print(f"error: {exc}")
            return
        self.result.turns += 1
        self.pending_decision = {
            "approval_id": result.approval_id,
            "run_id": result.run_id,
            "decision_id": result.decision_id,
            "candidate_id": result.candidate_id,
        }
        self.print(result.rendered_text)

    def _active_frame_approval_id(self) -> str:
        if self.pending_decision is not None:
            approval_id = str(self.pending_decision.get("approval_id") or "").strip()
            if approval_id:
                return approval_id
        frame = self._active_decision_frame()
        return str(frame.get("approval_id") or "").strip() if frame else ""

    def _active_decision_frame(self) -> dict[str, Any]:
        try:
            payload = self._store().load_state()
        except Exception:
            return {}
        general = _general_state_payload(payload)
        metadata = general.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        frame = metadata.get("active_decision_frame")
        return dict(frame) if isinstance(frame, dict) else {}

    def _compile_debug_decision_context(self) -> Any:
        store = self._store()
        config = load_workspace_config(self.project_root)
        config_payload = config_with_executor_capability_snapshot(config)
        state_payload = store.load_state()
        world_state = _world_state_from_workspace_payload(state_payload)
        general_state = load_general_state(world_state)
        session = load_or_create_session(store, session_id=self.result.session_id)
        frame = self._active_decision_frame()
        workspace_context = latest_workspace_context_from_store(store, session, active_frame=frame)
        url_context = latest_url_context_from_store(store, session, active_frame=frame)
        delegated_context = latest_delegated_perception_context_from_store(
            store,
            session,
            active_frame=frame,
        )
        compiler = load_workspace_context_compiler(
            self.project_root,
            config=config,
        )
        return compiler.compile_general_decision_context(
            world_state,
            general_state,
            current_intent=_context_current_intent(frame),
            active_decision_frame=frame,
            session=payload_value(session),
            config=config_payload,
            domain="general",
            workspace_context=workspace_context or None,
            url_context=url_context or None,
            delegated_perception_context=delegated_context or None,
        )

    def _save_active_decision_frame(self, frame: dict[str, Any]) -> None:
        if not self.persist:
            return
        store = self._store()
        payload = store.load_state()
        general = _general_state_payload(payload)
        metadata = general.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            general["metadata"] = metadata
        metadata["active_decision_frame"] = frame
        store.save_state(payload)

    def _mark_active_frame_status(self, status: str) -> None:
        frame = self._active_decision_frame()
        if not frame:
            return
        frame["status"] = status
        self._save_active_decision_frame(frame)

    def _show_active_frame_details(self) -> None:
        frame = self._active_decision_frame()
        if not frame:
            self.print("No active Decision Card.")
            return
        selected = frame.get("selected") if isinstance(frame.get("selected"), dict) else {}
        self.print(
            "\n".join(
                [
                    "ACTIVE DECISION FRAME",
                    f"decision_id: {frame.get('decision_id')}",
                    f"selected: {selected.get('label') or ''} {selected.get('title') or ''}".rstrip(),
                    f"candidate_id: {selected.get('candidate_id') or frame.get('selected_candidate_id') or ''}",
                    f"status: {frame.get('status') or 'unknown'}",
                ]
            )
        )

    def _decision_action_picker_available(self) -> bool:
        if self.output_stream is None:
            is_tty = sys.stdin.isatty() and sys.stdout.isatty()
        else:
            is_tty = bool(getattr(self.output_stream, "isatty", lambda: False)())
        return is_tty and _prompt_toolkit_available()

    def _show_decision_action_picker(self) -> None:
        while self.pending_decision is not None:
            action = self._prompt_decision_action(self.pending_decision)
            if not action:
                self.print(_decision_next_step_text(self.pending_decision))
                return
            if self._handle_decision_action(action):
                return

    def _prompt_decision_action(self, pending: dict[str, str]) -> str:
        options = _decision_action_options()
        rows = [(value, label, shortcut) for value, label, shortcut in options]
        try:
            result = self._prompt_inline_choice(
                title="What would you like to do?",
                rows=rows,
                footer=f"approval_id: {pending.get('approval_id', '')}",
                prompt_label="action",
            )
        except (EOFError, KeyboardInterrupt):
            return ""
        except Exception:
            return ""
        return _normalize_decision_action(str(result or ""))

    def _prompt_inline_choice(
        self,
        *,
        title: str,
        rows: list[tuple[str, str, str]],
        prompt_label: str,
        footer: str = "",
    ) -> str:
        try:
            from prompt_toolkit.application import Application
            from prompt_toolkit.formatted_text import FormattedText
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import HSplit, Layout, Window
            from prompt_toolkit.layout.controls import FormattedTextControl
            from prompt_toolkit.styles import Style
        except ImportError:
            return ""

        selected = {"index": 0}
        bindings = KeyBindings()

        @bindings.add("up")
        def _move_up(event: Any) -> None:
            selected["index"] = (selected["index"] - 1) % len(rows)
            event.app.invalidate()

        @bindings.add("down")
        def _move_down(event: Any) -> None:
            selected["index"] = (selected["index"] + 1) % len(rows)
            event.app.invalidate()

        @bindings.add("enter")
        def _accept(event: Any) -> None:
            event.app.exit(result=rows[selected["index"]][0])

        @bindings.add("space")
        def _accept_space(event: Any) -> None:
            event.app.exit(result=rows[selected["index"]][0])

        @bindings.add("escape")
        def _cancel(event: Any) -> None:
            event.app.exit(result="")

        control = FormattedTextControl(
            lambda: FormattedText(
                _inline_choice_fragments(
                    title=title,
                    rows=rows,
                    selected_index=selected["index"],
                    footer=footer,
                    prompt_label=prompt_label,
                )
            ),
            focusable=True,
        )
        app = Application(
            layout=Layout(HSplit([Window(content=control, dont_extend_height=True)]), focused_element=control),
            key_bindings=bindings,
            style=Style.from_dict(
                {
                    "title": "ansiyellow bold",
                    "shortcut": "ansigreen",
                    "selected": "ansigreen bold",
                    "choice": "ansigreen",
                    "hint": "ansibrightblack",
                    "prompt": "ansired bold",
                    "cursor": "ansigreen bold",
                }
            ),
            full_screen=False,
            mouse_support=False,
        )
        return str(app.run() or "")

    def _handle_decision_action(self, action: str) -> bool:
        approval_id = str((self.pending_decision or {}).get("approval_id") or "")
        return self._handle_approval_action(action, approval_id)

    def _handle_approval_action(self, action: str, approval_id: str) -> bool:
        if action == "approve_execute":
            self._approve_and_execute_pending(approval_id)
            return True
        if action == "approve":
            self._resolve_approval(approval_id, status="approved")
            return True
        if action == "reject":
            reason = self._prompt_free_text("reject reason> ")
            if reason is None:
                self.print("Reject cancelled.")
                return False
            self._resolve_approval(approval_id, status="rejected", reason=reason)
            return True
        if action == "refine":
            feedback = self._prompt_free_text("refine> ")
            if not feedback:
                self.print("Refine cancelled.")
                return False
            self._refine_decision(feedback)
            return True
        if action == "details":
            self._show_approval_details(approval_id)
            return False
        if action == "skip":
            self.print(f"Skipped pending decision: {approval_id}")
            self._clear_pending_decision(approval_id)
            return True
        return False

    def _prompt_free_text(self, prompt: str) -> str | None:
        try:
            return str(self.prompt_session.prompt([("class:prompt", prompt)])).strip()
        except (EOFError, KeyboardInterrupt):
            return None

    def _approve_and_execute_pending(self, approval_id: str) -> None:
        if not approval_id:
            self.print("error: no pending approval to execute")
            self.pending_decision = None
            return
        permission_mode = self._confirm_executor_permission_for_approval(approval_id)
        if permission_mode is None:
            return
        if self._resolve_approval(approval_id, status="approved"):
            self._execute_configured(approval_id, permission_mode=permission_mode)

    def _confirm_executor_permission_for_approval(self, approval_id: str) -> str | None:
        store = self._store()
        approval = load_approval(store, approval_id)
        config = load_workspace_config(self.project_root)
        executor = resolve_executor_runtime_from_config(config)
        escalate, requirement = approval_requires_permission_escalation(
            store=store,
            approval=approval,
            current_permission=executor.permission_mode,
        )
        if not escalate:
            return executor.permission_mode
        if executor.permission_enforcement != "command_flag":
            self.print(
                _executor_policy_permission_boundary_text(
                    executor_id=executor.executor_id,
                    current_permission=executor.permission_mode,
                    required_permission=requirement.required_permission,
                    reason=requirement.reason,
                )
            )
            return None
        while True:
            action = self._prompt_permission_escalation(
                approval_id=approval_id,
                executor_id=executor.executor_id,
                current_permission=executor.permission_mode,
                required_permission=requirement.required_permission,
                reason=requirement.reason,
            )
            if action == "yes":
                return requirement.required_permission
            if action == "details":
                self.print(
                    _permission_escalation_details(
                        approval_id=approval_id,
                        executor_id=executor.executor_id,
                        current_permission=executor.permission_mode,
                        required_permission=requirement.required_permission,
                        reason=requirement.reason,
                    )
                )
                continue
            self.print(
                "Execution permission was not escalated. "
                f"Approval remains pending: {approval_id}"
            )
            return None

    def _prompt_permission_escalation(
        self,
        *,
        approval_id: str,
        executor_id: str,
        current_permission: str,
        required_permission: str,
        reason: str,
    ) -> str:
        rows = [
            ("yes", f"Yes, run {executor_id} with {required_permission} for this execution", "y / yes"),
            ("no", "No, keep this approval pending", "n / no"),
            ("details", "Show permission details", "d / details"),
        ]
        footer = (
            f"approval_id: {approval_id}\n"
            f"current: {current_permission}  required: {required_permission}\n"
            f"reason: {reason}"
        )
        if self._decision_action_picker_available():
            try:
                value = self._prompt_inline_choice(
                    title="Higher execution permission required",
                    rows=rows,
                    footer=footer,
                    prompt_label="permission",
                )
                normalized = str(value or "").strip().lower()
                if normalized in {"yes", "no", "details"}:
                    return normalized
            except Exception:
                pass
        self.print(_permission_escalation_text(footer))
        answer = self._prompt_free_text("permission> ")
        normalized = str(answer or "").strip().lower()
        if normalized in {"y", "yes"}:
            return "yes"
        if normalized in {"d", "detail", "details"}:
            return "details"
        return "no"

    def _build_console(self, output_stream: TextIO | None) -> Any:
        try:
            from rich.console import Console
        except ImportError:
            return None
        if output_stream is None:
            return Console(force_terminal=None, legacy_windows=False)
        return Console(file=output_stream, force_terminal=None, legacy_windows=False)

    def _build_prompt_session(self) -> Any:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.styles import Style

        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        return PromptSession(
            history=FileHistory(str(self.history_path)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=WordCompleter(COMMANDS, ignore_case=True),
            style=Style.from_dict({"prompt": "ansired bold"}),
        )


def _prompt_toolkit_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        return False
    return True


def _context_json_requested(value: str) -> bool:
    tokens = [token.strip().lower() for token in shlex.split(value or "")]
    return "--json" in tokens or "json" in tokens


def _sources_run_id(value: str) -> str:
    for token in shlex.split(value or ""):
        normalized = token.strip()
        if not normalized or normalized.lower() in {"--json", "json"}:
            continue
        return normalized
    return ""


def _execution_audit_target(value: str) -> bool:
    target = value.strip()
    return (
        _latest_execution_alias(target)
        or target.startswith("outcome.")
        or target.startswith("execution.")
        or target.startswith("exec.")
    )


def _latest_execution_alias(value: str) -> bool:
    normalized = value.strip().lower().replace("_", "-")
    return normalized in {
        "execution",
        "exec",
        "executor",
        "outcome",
        "result",
        "last-execution",
        "last-outcome",
    }


def _context_current_intent(frame: dict[str, Any]) -> dict[str, Any]:
    raw_input = frame.get("input") if isinstance(frame.get("input"), dict) else {}
    text = str(raw_input.get("text") or "").strip()
    return {
        "text": text,
        "source": str(frame.get("source") or "context_debug"),
        "kind": "context_debug",
        "run_intent_mode": str(frame.get("run_intent_mode") or ""),
        "display_language": str(frame.get("display_language") or ""),
        "decision_id": str(frame.get("decision_id") or ""),
        "run_id": str(frame.get("run_id") or ""),
    }


def _render_context_panel(payload: dict[str, Any]) -> Any:
    try:
        from rich import box
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:
        return _context_text(payload)

    frame = payload.get("active_decision_frame")
    frame_payload = frame if isinstance(frame, dict) else {}
    current_intent = payload.get("current_intent")
    intent_payload = current_intent if isinstance(current_intent, dict) else {}
    executor = payload.get("executor_affordance")
    executor_payload = executor if isinstance(executor, dict) else {}
    executor_capabilities = payload.get("executor_capabilities")
    executor_capabilities_payload = (
        executor_capabilities if isinstance(executor_capabilities, dict) else {}
    )
    session = payload.get("session_summary")
    session_payload = session if isinstance(session, dict) else {}
    workspace = payload.get("workspace_context")
    workspace_payload = workspace if isinstance(workspace, dict) else {}
    url_context = payload.get("url_context")
    url_payload = url_context if isinstance(url_context, dict) else {}
    delegated_context = payload.get("delegated_perception_context")
    delegated_payload = delegated_context if isinstance(delegated_context, dict) else {}
    evidence_context = payload.get("evidence_context")
    evidence_payload = evidence_context if isinstance(evidence_context, dict) else {}

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("field", style=SpiceTheme.DIM, no_wrap=True)
    table.add_column("value")
    table.add_row("context_id", str(payload.get("id") or ""))
    table.add_row("context_type", str(payload.get("context_type") or ""))
    table.add_row("current_intent", _shorten(str(intent_payload.get("text") or ""), 120))
    table.add_row("active_decision", str(frame_payload.get("decision_id") or ""))
    table.add_row("selected", _context_selected_summary(frame_payload))
    table.add_row("recent_decisions", str(len(_list(payload.get("recent_decisions")))))
    table.add_row("recent_approvals", str(len(_list(payload.get("recent_approvals")))))
    table.add_row("recent_outcomes", str(len(_list(payload.get("recent_outcomes")))))
    table.add_row("retrieved_memory", str(len(_list(payload.get("retrieved_memory")))))
    table.add_row("executor", _executor_context_summary(executor_payload))
    table.add_row(
        "executor_capabilities",
        _executor_capabilities_context_summary(executor_capabilities_payload),
    )
    table.add_row("summary", _summary_context_summary(session_payload))
    table.add_row("session", _session_context_summary(session_payload))
    table.add_row("workspace", _workspace_context_summary(workspace_payload))
    table.add_row("url_context", _url_context_summary(url_payload))
    table.add_row("delegated_perception", _delegated_context_summary(delegated_payload))
    table.add_row("evidence", _evidence_context_summary(evidence_payload))
    table.add_row("refs", str(len(_list(payload.get("refs")))))
    return Panel(
        table,
        title="[bold red]COMPILED DECISION CONTEXT[/bold red]",
        subtitle="Use /context --json to inspect the exact payload.",
        border_style=SpiceTheme.PANEL_BORDER,
        box=box.ROUNDED,
    )


def _context_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "COMPILED DECISION CONTEXT",
            f"context_id: {payload.get('id') or ''}",
            f"context_type: {payload.get('context_type') or ''}",
            f"current_intent: {_shorten(str(_mapping(payload.get('current_intent')).get('text') or ''), 120)}",
            f"active_decision: {_mapping(payload.get('active_decision_frame')).get('decision_id') or ''}",
            f"selected: {_context_selected_summary(_mapping(payload.get('active_decision_frame')))}",
            f"recent_decisions: {len(_list(payload.get('recent_decisions')))}",
            f"recent_approvals: {len(_list(payload.get('recent_approvals')))}",
            f"recent_outcomes: {len(_list(payload.get('recent_outcomes')))}",
            f"retrieved_memory: {len(_list(payload.get('retrieved_memory')))}",
            f"executor: {_executor_context_summary(_mapping(payload.get('executor_affordance')))}",
            f"executor_capabilities: {_executor_capabilities_context_summary(_mapping(payload.get('executor_capabilities')))}",
            f"summary: {_summary_context_summary(_mapping(payload.get('session_summary')))}",
            f"session: {_session_context_summary(_mapping(payload.get('session_summary')))}",
            f"workspace: {_workspace_context_summary(_mapping(payload.get('workspace_context')))}",
            f"url_context: {_url_context_summary(_mapping(payload.get('url_context')))}",
            f"delegated_perception: {_delegated_context_summary(_mapping(payload.get('delegated_perception_context')))}",
            f"evidence: {_evidence_context_summary(_mapping(payload.get('evidence_context')))}",
            "Use /context --json to inspect the exact payload.",
        ]
    )


def _render_why_summary(compare_payload: dict[str, Any]) -> str:
    if not compare_payload:
        return "No Decision Card found."
    selected = _mapping(compare_payload.get("selected_recommendation"))
    lines = [
        "WHY THIS DECISION",
        f"selected: {selected.get('title') or 'unknown'}",
        f"candidate_id: {selected.get('candidate_id') or ''}",
    ]
    selection_reason = str(selected.get("selection_reason") or "").strip()
    if selection_reason:
        lines.append(f"selection: {selection_reason}")
    human_summary = str(selected.get("human_summary") or "").strip()
    if human_summary:
        lines.append(f"recommendation: {human_summary}")
    basis = _list(selected.get("decision_basis"))
    if basis:
        lines.append("")
        lines.append("why this won:")
        for item in basis[:3]:
            payload = _mapping(item)
            dimension = str(payload.get("dimension") or payload.get("label") or "factor")
            contribution = payload.get("contribution")
            if contribution is None:
                lines.append(f"- {dimension}")
            else:
                lines.append(f"- {dimension}: {contribution}")
    reasons = _list(compare_payload.get("why_not_the_others"))
    if reasons:
        lines.append("")
        lines.append("why not others:")
        for item in reasons[:3]:
            payload = _mapping(item)
            lines.append(f"- {payload.get('title') or payload.get('candidate_id') or 'candidate'}")
            for reason in _list(payload.get("reasons"))[:2]:
                reason_payload = _mapping(reason)
                text = str(reason_payload.get("reason") or reason_payload.get("summary") or "").strip()
                if text:
                    lines.append(f"  - {text}")
    return "\n".join(lines)


def _render_simulation_summary(compare_payload: dict[str, Any]) -> str:
    candidates = _list(compare_payload.get("candidate_decisions"))
    if not candidates:
        return "No simulation data found."
    lines = ["SIMULATION SUMMARY"]
    rendered = 0
    for candidate in candidates:
        payload = _mapping(candidate)
        simulation = _mapping(payload.get("simulation"))
        if not simulation:
            continue
        rendered += 1
        lines.append("")
        lines.append(f"{payload.get('label') or rendered}. {payload.get('title') or payload.get('candidate_id') or 'candidate'}")
        outcome = str(simulation.get("expected_outcome") or simulation.get("simulated_outcome") or "").strip()
        downside = str(simulation.get("downside") or "").strip()
        success = str(simulation.get("success_signal") or "").strip()
        confidence = simulation.get("confidence")
        if outcome:
            lines.append(f"- expected: {outcome}")
        if downside:
            lines.append(f"- downside: {downside}")
        if success:
            lines.append(f"- success: {success}")
        if confidence is not None:
            lines.append(f"- confidence: {confidence}")
    if rendered == 0:
        lines.append("- no LLM simulation attached to the current visible candidates")
    return "\n".join(lines)


def _context_selected_summary(frame: dict[str, Any]) -> str:
    selected = frame.get("selected") if isinstance(frame.get("selected"), dict) else {}
    label = str(selected.get("label") or "").strip()
    title = str(selected.get("title") or selected.get("recommended_action") or "").strip()
    candidate_id = str(selected.get("candidate_id") or frame.get("selected_candidate_id") or "").strip()
    parts = [part for part in [label, _shorten(title, 80), candidate_id] if part]
    return " | ".join(parts)


def _selected_candidate_next_action_text(
    selected: Mapping[str, Any],
    frame: Mapping[str, Any],
) -> str:
    kind = _selected_candidate_next_action_kind(selected)
    if kind == "executable":
        return "Next: type `execute selected`, `refine that ...`, `details`, or a new intent."
    if kind == "read_only":
        reason = "This option is read-only and has no executor handoff."
    elif kind == "noop":
        reason = "This option records, skips, or postpones work; it has no executor handoff."
    elif kind == "blocked":
        reason = "This option is not ready for an executor handoff."
    else:
        reason = "This option is advisory-only and has no executor handoff."
    candidate_id = str(selected.get("candidate_id") or frame.get("selected_candidate_id") or "").strip()
    suffix = f"\ncandidate_id: {candidate_id}" if candidate_id and kind == "blocked" else ""
    return (
        f"{reason}{suffix}\n"
        "Next: type `refine that ...`, `details`, choose another option, "
        "or `/act <specific executable task>`."
    )


def _selected_candidate_next_action_kind(selected: Mapping[str, Any]) -> str:
    text = _selected_candidate_boundary_text(selected)
    if _candidate_text_is_noop_or_defer(text):
        return "noop"
    if _candidate_text_is_read_only(text):
        return "read_only"

    affordance = _mapping(selected.get("execution_affordance"))
    if not affordance:
        return "advisory"
    if (
        "candidate_execution_requested" in affordance
        and not bool(affordance.get("candidate_execution_requested"))
    ):
        return "advisory"
    approval = _mapping(affordance.get("approval"))
    if bool(
        affordance.get("candidate_executable")
        and affordance.get("executor_available")
        and affordance.get("executable")
        and approval.get("required")
        and approval.get("eligible_for_approval")
    ):
        return "executable"
    if bool(affordance.get("candidate_execution_requested") or affordance.get("blocked")):
        return "blocked"
    return "advisory"


def _selected_candidate_boundary_text(selected: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "action",
        "action_type",
        "intent",
        "title",
        "recommended_action",
        "expected_result",
        "executor_task",
        "required_capability",
    ):
        value = selected.get(key)
        if value:
            parts.append(str(value))
    for item in _list(selected.get("why_now")):
        if item:
            parts.append(str(item))
    return "\n".join(parts).lower()


def _candidate_text_is_noop_or_defer(text: str) -> bool:
    patterns = (
        "time.defer",
        "state.record",
        "record-only",
        "record only",
        "no-op",
        "noop",
        "defer",
        "later",
        "skip",
        "postpone",
        "暂缓",
        "稍后",
        "仅记录",
        "只记录",
        "记录状态",
        "不执行",
        "不要现在发起",
        "先不要现在发起",
    )
    return any(pattern in text for pattern in patterns)


def _candidate_text_is_read_only(text: str) -> bool:
    read_only_terms = (
        "read-only",
        "read_only",
        "read_file",
        "repo_map",
        "search",
        "git_status",
        "git_diff",
        "git_log",
        "read_package_metadata",
        "read_test_structure",
        "read_python_symbol",
        "workspace perception",
        "inspect current implementation",
        "读取",
        "查看当前实现",
        "读 repo",
    )
    state_changing_terms = (
        "write_file",
        "patch",
        "edit",
        "delete",
        "move",
        "install",
        "terminal_command",
        "run test",
        "pytest",
        "修改",
        "写入",
        "删除",
        "安装",
        "执行测试",
    )
    return any(term in text for term in read_only_terms) and not any(
        term in text for term in state_changing_terms
    )


def _executor_context_summary(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("executor") or payload.get("provider") or ""),
        str(payload.get("permission") or payload.get("permission_mode") or ""),
    ]
    available = payload.get("available")
    if available is not None:
        parts.append(f"available={str(bool(available)).lower()}")
    return " ".join(part for part in parts if part).strip()


def _session_context_summary(payload: dict[str, Any]) -> str:
    session_id = str(payload.get("session_id") or "")
    runs = payload.get("runs")
    decisions = payload.get("decisions")
    parts = [session_id]
    if runs is not None:
        parts.append(f"runs={runs}")
    if decisions is not None:
        parts.append(f"decisions={decisions}")
    return " ".join(part for part in parts if part).strip()


def _summary_context_summary(payload: dict[str, Any]) -> str:
    rolling = payload.get("rolling_summary")
    if not isinstance(rolling, dict):
        return "none"
    summary_type = str(rolling.get("summary_type") or "deterministic")
    updated = str(rolling.get("updated_at") or "")
    model = rolling.get("model") if isinstance(rolling.get("model"), dict) else {}
    model_id = str(model.get("model_id") or "")
    parts = [summary_type]
    if model_id:
        parts.append(model_id)
    if updated:
        parts.append(f"updated={updated}")
    return " ".join(parts)


def _workspace_context_summary(payload: dict[str, Any]) -> str:
    if payload.get("perception_id") or payload.get("source") == "workspace_perception":
        budget_used = _mapping(payload.get("budget_used"))
        sufficiency = _mapping(payload.get("sufficiency_check"))
        chars_used = budget_used.get("chars_used")
        total_chars = budget_used.get("total_char_budget")
        char_part = (
            f"chars={chars_used}/{total_chars}"
            if chars_used is not None or total_chars is not None
            else ""
        )
        remaining_gaps = _list(sufficiency.get("remaining_gaps"))
        evidence_sufficiency = _workspace_sufficiency_summary(sufficiency)
        return " ".join(
            part
            for part in [
                "workspace_perception",
                str(payload.get("perception_id") or ""),
                f"depth={payload.get('depth')}" if payload.get("depth") else "",
                f"status={payload.get('exploration_status')}" if payload.get("exploration_status") else "",
                f"rounds={budget_used.get('rounds_used')}" if budget_used.get("rounds_used") is not None else "",
                f"tools={budget_used.get('tool_calls_executed')}" if budget_used.get("tool_calls_executed") is not None else "",
                f"blocked={budget_used.get('tool_calls_blocked')}" if budget_used.get("tool_calls_blocked") is not None else "",
                f"facts={len(_list(payload.get('facts')))}",
                f"files={len(_list(payload.get('files_read')))}",
                char_part,
                f"pressure={budget_used.get('budget_pressure')}" if budget_used.get("budget_pressure") else "",
                f"sufficiency={evidence_sufficiency}" if evidence_sufficiency else "",
                f"gaps={len(remaining_gaps)}" if remaining_gaps else "",
            ]
            if part
        )
    parts = [
        f"memory={payload.get('memory_provider')}"
        if payload.get("memory_provider") is not None
        else "",
        f"compiler={payload.get('context_compiler')}"
        if payload.get("context_compiler") is not None
        else "",
        f"summary={payload.get('memory_summary_provider')}"
        if payload.get("memory_summary_provider") is not None
        else "",
        f"executor={payload.get('executor')}" if payload.get("executor") is not None else "",
    ]
    return " ".join(part for part in parts if part)


def _workspace_sufficiency_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    sufficient = bool(payload.get("sufficient_evidence"))
    can_answer = bool(payload.get("can_answer_user_question"))
    if sufficient and can_answer:
        return "sufficient"
    if can_answer:
        return "partial"
    return "insufficient"


def _url_context_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "none"
    return " ".join(
        part
        for part in [
            "url_perception",
            str(payload.get("perception_id") or ""),
            f"docs={len(_list(payload.get('documents')))}",
            f"facts={len(_list(payload.get('facts')))}",
            f"urls={len(_list(payload.get('urls')))}",
        ]
        if part
    )


def _delegated_context_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "none"
    return " ".join(
        part
        for part in [
            "delegated_perception",
            str(payload.get("perception_id") or ""),
            f"executor={payload.get('executor_id')}" if payload.get("executor_id") else "",
            f"findings={len(_list(payload.get('findings')))}",
            f"sources={len(_list(payload.get('sources')))}",
            f"confidence={payload.get('confidence')}" if payload.get("confidence") else "",
        ]
        if part
    )


def _evidence_context_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "none"
    workspace = _mapping(payload.get("workspace"))
    url = _mapping(payload.get("url"))
    delegated = _mapping(payload.get("delegated"))
    return " ".join(
        part
        for part in [
            f"confidence={payload.get('confidence') or 'none'}",
            f"workspace={workspace.get('source_count') or 0}" if workspace.get("present") else "",
            f"url={url.get('source_count') or 0}" if url.get("present") else "",
            f"delegated={delegated.get('source_count') or 0}" if delegated.get("present") else "",
            f"limitations={len(_list(payload.get('limitations')))}",
        ]
        if part
    ) or "none"


def _executor_capabilities_context_summary(payload: dict[str, Any]) -> str:
    executor_id = str(payload.get("executor_id") or "").strip()
    source = str(payload.get("source") or "").strip()
    capabilities = _list(payload.get("capability_ids"))
    parts = [executor_id, source]
    if capabilities:
        parts.append(f"capabilities={len(capabilities)}")
    return " ".join(part for part in parts if part) or "none"


def _world_state_from_workspace_payload(payload: dict[str, Any]) -> WorldState:
    world_payload = payload.get("world_state")
    if not isinstance(world_payload, dict):
        raise ValueError("Workspace state must contain a world_state object.")
    return WorldState(
        id=str(world_payload.get("id") or "worldstate.local"),
        schema_version=str(world_payload.get("schema_version", "0.1")),
        status=str(world_payload.get("status", "current")),
        entities=_mapping(world_payload.get("entities")),
        relations=_list_of_mappings(world_payload.get("relations")),
        goals=_list_of_mappings(world_payload.get("goals")),
        constraints=_list_of_mappings(world_payload.get("constraints")),
        resources=_mapping(world_payload.get("resources")),
        risks=_list_of_mappings(world_payload.get("risks")),
        signals=_list_of_mappings(world_payload.get("signals")),
        active_intents=_list_of_mappings(world_payload.get("active_intents")),
        recent_outcomes=_list_of_mappings(world_payload.get("recent_outcomes")),
        confidence=_mapping(world_payload.get("confidence")),
        provenance=_mapping(world_payload.get("provenance")),
        domain_state=_mapping(world_payload.get("domain_state")),
    )


def _startup_dashboard(store: LocalJsonStore, config: dict[str, Any]) -> dict[str, Any]:
    state_payload = _safe_load_state(store)
    state_counts = _general_state_counts(state_payload)
    approval_ids = store.list_record_ids("approvals")
    pending_count = 0
    for approval_id in approval_ids:
        try:
            approval = store.load_approval(approval_id)
        except Exception:
            continue
        if approval.get("status") == "pending":
            pending_count += 1
    return {
        "mode": _runtime_mode(config),
        "pending_approvals": pending_count,
        "run_count": len(store.list_record_ids("runs")),
        "decision_count": len(store.list_record_ids("decisions")),
        "outcome_count": len(store.list_record_ids("outcomes")),
        "state_counts": state_counts,
        "executors": _executor_readiness(config),
        "skills": _skill_readiness(),
        "perception": _perception_readiness(config),
    }


def _safe_load_state(store: LocalJsonStore) -> dict[str, Any]:
    try:
        return store.load_state()
    except Exception:
        return {}


def _general_state_counts(state_payload: dict[str, Any]) -> dict[str, int]:
    general = _general_state_payload(state_payload)
    return {
        "observations": len(_items(general, "observations")),
        "intents": len(_items(general, "intents")),
        "work_items": len(_items(general, "work_items")),
        "commitments": len(_items(general, "commitments")),
        "outcomes": len(_items(general, "outcomes")),
        "approvals": len(_items(general, "approvals")),
    }


def _general_state_payload(state_payload: dict[str, Any]) -> dict[str, Any]:
    world = state_payload.get("world_state")
    if not isinstance(world, dict):
        return {}
    domain = world.get("domain_state")
    if not isinstance(domain, dict):
        return {}
    general = domain.get("general_decision")
    return general if isinstance(general, dict) else {}


def _items(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _workspace_context_from_step(
    step: RuntimeWorkspacePerceptionResult | None,
) -> dict[str, Any] | None:
    if step is None or not isinstance(step.context, dict) or not step.context:
        return None
    return dict(step.context)


def _workspace_artifact_from_step(
    step: RuntimeWorkspacePerceptionResult | None,
) -> dict[str, Any] | None:
    if step is None or not isinstance(step.artifact, dict) or not step.artifact:
        return None
    return dict(step.artifact)


def _url_context_from_step(
    step: RuntimeURLPerceptionResult | None,
) -> dict[str, Any] | None:
    if step is None or not isinstance(step.context, dict) or not step.context:
        return None
    return dict(step.context)


def _url_artifact_from_step(
    step: RuntimeURLPerceptionResult | None,
) -> dict[str, Any] | None:
    if step is None or not isinstance(step.artifact, dict) or not step.artifact:
        return None
    return dict(step.artifact)


def _with_workspace_context(
    payload: dict[str, Any],
    workspace_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = dict(workspace_context or {})
    if not context:
        return payload
    merged = dict(payload)
    merged["workspace_context"] = context
    return merged


def _with_url_context(
    payload: dict[str, Any],
    url_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = dict(url_context or {})
    if not context:
        return payload
    merged = dict(payload)
    merged["url_context"] = context
    return merged


def _with_delegated_perception_context(
    payload: dict[str, Any],
    delegated_perception_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = dict(delegated_perception_context or {})
    if not context:
        return payload
    merged = dict(payload)
    merged["delegated_perception_context"] = context
    return merged


def _with_merged_route_context(route: Any, policy: RouteMergePolicy) -> Any:
    payload = policy.to_route_payload()
    updates = {
        "context_strategy": payload.get("context_strategy"),
        "needs_workspace_context": bool(payload.get("needs_workspace_context")),
        "workspace_query": str(payload.get("workspace_query") or ""),
        "needs_url_context": bool(payload.get("needs_url_context")),
        "url_query": str(payload.get("url_query") or ""),
        "urls": list(payload.get("urls") or []),
        "needs_delegated_perception": bool(payload.get("needs_delegated_perception")),
        "delegated_perception_query": str(payload.get("delegated_perception_query") or ""),
        "delegated_perception_reason": str(payload.get("delegated_perception_reason") or ""),
        "suggested_capabilities": list(payload.get("suggested_capabilities") or []),
    }
    route_reason = str(getattr(route, "reason", "") or "")
    policy_reason = str(policy.reason or "")
    if hasattr(route, "reason"):
        updates["reason"] = "; ".join(part for part in (route_reason, policy_reason) if part)
    if hasattr(route, "raw"):
        raw = dict(getattr(route, "raw", {}) or {})
        raw["resource_extraction"] = policy.resource_extraction.to_payload()
        raw["evidence_requirement"] = policy.evidence_requirement.to_payload()
        raw["workspace_scope"] = policy.workspace_scope.to_payload() if policy.workspace_scope is not None else {}
        raw["route_merge_policy"] = policy.to_payload()
        updates["raw"] = raw
    try:
        return replace(route, **updates)
    except Exception:
        merged = dict(payload)
        merged["raw"] = {
            "resource_extraction": policy.resource_extraction.to_payload(),
            "evidence_requirement": policy.evidence_requirement.to_payload(),
            "workspace_scope": policy.workspace_scope.to_payload() if policy.workspace_scope is not None else {},
            "route_merge_policy": policy.to_payload(),
        }
        return merged


def _delegated_escalation_finish_label(escalation: RuntimeEscalationDecision | None) -> str:
    if escalation is None:
        return "Ready."
    if escalation.action == ESCALATION_BLOCKED:
        return "Investigation blocked."
    if escalation.action == ESCALATION_RUN_DELEGATED_PERCEPTION:
        return "Investigation consent granted."
    return "Investigation consent needed."


def _workspace_evidence_status_label() -> str:
    return "Detected repo reference. Reading workspace evidence..."


def _url_evidence_status_label() -> str:
    return "Detected URL. Fetching linked context..."


def _delegated_investigation_question(executor_id: str) -> str:
    executor = _executor_loading_name(str(executor_id or ""))
    return f"This needs deeper external investigation. Ask {executor} to run read-only investigation?"


def _investigation_consent_text(
    consent: InvestigationConsent,
    escalation: RuntimeEscalationDecision | None,
) -> str:
    reason = ""
    if escalation is not None:
        reason = str(escalation.delegated_perception_reason or escalation.reason or "").strip()
    budget = consent.budget.to_payload()
    executor = _executor_loading_name(consent.executor_id)
    lines = [
        _delegated_investigation_question(consent.executor_id),
        (
            f"I can ask {executor} to investigate. "
            "It cannot modify files, execute tasks, install packages, or run tests; it should only return findings and sources."
        ),
        "",
        f"query: {consent.query}",
    ]
    if reason:
        lines.append(f"reason: {reason}")
    lines.extend(
        [
            f"consent_id: {consent.consent_id}",
            f"scope: {consent.scope}; permission: {consent.permission_mode}",
            (
                "budget: "
                f"{budget.get('max_duration_sec')}s, "
                f"{budget.get('max_sources')} sources, "
                f"{budget.get('max_repo_files')} repo files"
            ),
            "",
            "Type `yes` to allow this investigation, `no` to reject, or `details` to inspect the consent.",
        ]
    )
    return "\n".join(lines)


def _investigation_next_step_text(pending: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "What would you like to do?",
            "  ↑↓ navigate   ENTER/SPACE select   ESC cancel",
            "",
            "→ (●) Allow read-only investigation  y / yes",
            "  (○) Reject                         n / no",
            "  (○) Show details                   d / details",
            "  (○) Skip for now                   q / skip",
            "",
            f"consent_id: {pending.get('consent_id', '')}",
            "action>",
        ]
    )


def _investigation_consent_details_text(consent: InvestigationConsent) -> str:
    budget = consent.budget.to_payload()
    return "\n".join(
        [
            "READ-ONLY INVESTIGATION CONSENT",
            f"consent_id: {consent.consent_id}",
            f"status: {consent.status}",
            f"executor: {consent.executor_id}",
            f"query: {consent.query}",
            f"scope: {consent.scope}",
            f"permission_mode: {consent.permission_mode}",
            f"expires_at: {consent.expires_at}",
            f"allowed_actions: {', '.join(consent.allowed_actions)}",
            f"denied_actions: {', '.join(consent.denied_actions)}",
            (
                "budget: "
                f"duration={budget.get('max_duration_sec')}s, "
                f"sources={budget.get('max_sources')}, "
                f"repo_files={budget.get('max_repo_files')}, "
                f"tokens={budget.get('max_tokens')}"
            ),
            "This is not execution approval. It only authorizes a read-only investigation.",
        ]
    )


def _investigation_blocked_text(escalation: RuntimeEscalationDecision) -> str:
    reason = str(escalation.blocked_reason or escalation.reason or "Delegated investigation is blocked.")
    return "\n".join(
        [
            "Read-only investigation is not available for this turn.",
            f"reason: {reason}",
            f"executor: {escalation.executor_id or 'unknown'}",
            "No execution approval was created.",
        ]
    )


def _investigation_granted_text(consent: InvestigationConsent) -> str:
    executor = _executor_loading_name(consent.executor_id)
    return "\n".join(
        [
            f"Investigation consent granted: {consent.consent_id}",
            f"{executor} is authorized for read-only investigation only.",
            "No files can be modified and no execution approval was created.",
            "Next runtime step can hand this consent to delegated perception and record findings in /sources.",
        ]
    )


def _investigation_rejected_text(consent: InvestigationConsent) -> str:
    return "\n".join(
        [
            f"Investigation consent rejected: {consent.consent_id}",
            "I will not call an external executor for this read-only investigation.",
        ]
    )


def _investigation_granted_ready_text(escalation: RuntimeEscalationDecision) -> str:
    return "\n".join(
        [
            "Read-only investigation consent is already granted.",
            f"executor: {escalation.executor_id or 'unknown'}",
            f"query: {escalation.delegated_perception_query or ''}",
            "Delegated perception can run under the granted consent; no execution approval was created.",
        ]
    )


def _investigation_handoff_result_text(result: RuntimeDelegatedPerceptionHandoffResult) -> str:
    artifact = _mapping(result.perception.artifact)
    report = _mapping(result.executor_report)
    executor = str(artifact.get("executor_id") or report.get("executor_id") or "executor")
    findings = _list(artifact.get("findings"))
    sources = _list(artifact.get("sources"))
    limitations = _list(artifact.get("limitations"))
    if result.status == "completed":
        lines = [
            (
                f"{executor} returned {len(findings)} finding(s) and "
                f"{len(sources)} source(s) from a read-only investigation."
            ),
            "I recorded the result as delegated perception. Use `/sources` to inspect the evidence.",
            "No execution approval or execution outcome was created.",
        ]
    else:
        reason = result.error or "; ".join(str(item) for item in limitations if str(item))
        lines = [
            f"Read-only delegated investigation did not complete via {executor}.",
            f"reason: {reason or 'executor returned no usable findings'}",
            "I recorded a failed delegated perception artifact and kept the execution boundary closed.",
            "No execution approval or execution outcome was created.",
        ]
    perception_id = str(artifact.get("perception_id") or "")
    report_id = str(report.get("report_id") or "")
    if perception_id:
        lines.append(f"perception_id: {perception_id}")
    if report_id:
        lines.append(f"executor_report: {report_id}")
    return "\n".join(lines)


def _local_perception_fallback_text(result: RuntimeWorkspacePerceptionResult) -> str:
    if result.status in {"written", "preview"}:
        artifact = _mapping(result.artifact)
        return "\n".join(
            [
                "I fell back to local workspace perception.",
                f"workspace_perception: {artifact.get('perception_id') or ''}",
                "Use `/workspace` or `/sources` to inspect what was read.",
            ]
        )
    return "\n".join(
        [
            "Local workspace perception fallback was not able to add more context.",
            f"reason: {result.error or result.status}",
        ]
    )


def _conversation_route_from_payload(payload: Mapping[str, Any], *, trigger: str) -> str:
    route = str(payload.get("route") or "").strip()
    if route in {"new_decision", "follow_up", "command", "execution_request"}:
        return route
    if trigger.startswith("follow_up"):
        return "follow_up"
    if trigger.startswith("refine"):
        return "follow_up"
    return "new_decision"


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _decision_next_step_text(pending: dict[str, str]) -> str:
    lines = [
        "Decision prompt shortcuts (type one at decision>):",
        "  y / yes                         approve and execute with the configured executor",
        "  a / approve                     approve only",
        "  n <reason> / reject <reason>    reject",
        "  r <feedback> / refine <feedback> refine and regenerate the Decision Card",
        "  d / details                     show approval details",
        "  q / skip                        skip this decision for now",
        "",
        "Examples:",
        "  decision> y",
        "  decision> reject too risky right now",
        "  decision> refine execute directly; do not split",
        f"approval_id: {pending.get('approval_id', '')}",
    ]
    return "\n".join(lines)


def _fallback_decision_brief_text(brief: dict[str, Any], error: Exception) -> str:
    selected = _mapping(brief.get("selected"))
    execution = _mapping(brief.get("execution"))
    title = str(selected.get("title") or "the selected option").strip()
    recommendation = str(selected.get("recommendation") or "").strip()
    execution_summary = str(execution.get("summary") or "advisory only").strip()
    lines = [
        f"I'd choose {title}.",
    ]
    if recommendation:
        lines.extend(["", recommendation])
    lines.extend(
        [
            "",
            f"Execution: {execution_summary}",
            "",
            "Next:",
            "  details  expand the full Decision Card",
            "  why      show why-not comparison",
            "  sim      show simulation notes",
            "  execute  request approval-gated execution",
            "  refine   adjust the decision",
        ]
    )
    return "\n".join(lines)


def _fallback_execution_response_text(artifact: dict[str, Any], error: Exception) -> str:
    facts = execution_response_facts(execution_artifact=artifact)
    return render_execution_response_fallback(facts)


def _fallback_execution_error_response_text(error_artifact: dict[str, Any], error: Exception) -> str:
    facts = execution_response_facts(error_artifact=error_artifact)
    return render_execution_response_fallback(facts)


def _execution_error_artifact(
    *,
    approval_id: str,
    executor_provider: str,
    error: Exception,
    permission_mode: str | None = None,
) -> dict[str, Any]:
    technical_error = str(error)
    failure_kind = classify_execution_error(technical_error)
    user_error = user_facing_execution_error(technical_error)
    artifact: dict[str, Any] = {
        "execution_status": "failed",
        "approval_id": approval_id,
        "executor_provider": executor_provider or "executor",
        "task_status": "failed",
        "error": user_error,
        "technical_error": technical_error,
        "failure_kind": failure_kind,
        "permission": {"mode": permission_mode or ""},
        "next_actions": ["details", "retry", "refine"],
    }
    if failure_kind == "approval_request_mismatch":
        artifact.update(
            {
                "executor_called": False,
                "real_executor_called": False,
                "sdep_request_sent": False,
                "executed": False,
                "next_actions": ["details", "refine", "choose executable task"],
            }
        )
    return artifact


def _conversation_next_steps_text(*, has_approval: bool = False) -> str:
    execute = "/execute continues the pending approval" if has_approval else "/execute requests approval-gated execution"
    return (
        "Card is folded. Use /details for the audit card, /why for the tradeoff, "
        f"/sim for simulation, {execute}, /refine to adjust, or /json for the raw artifact."
    )


def _response_text_blocks(text: str) -> list[str]:
    stripped = str(text or "").strip()
    if not stripped:
        return []
    blocks: list[str] = []
    current: list[str] = []
    for line in stripped.splitlines():
        if line.strip():
            current.append(line.rstrip())
            continue
        if current:
            blocks.append("\n".join(current).strip())
            current = []
    if current:
        blocks.append("\n".join(current).strip())
    return blocks or [stripped]


def _streaming_metadata_for_chunk_count(chunk_count: int) -> dict[str, Any]:
    return {
        "mode": "block_display",
        "chunk_count": max(0, int(chunk_count)),
        "source": "validated_composer_result",
    }


def _composer_result_with_streaming_metadata(result: ComposerResult, *, chunk_count: int) -> ComposerResult:
    metadata = dict(result.metadata)
    if "streaming" not in metadata:
        metadata["streaming"] = _streaming_metadata_for_chunk_count(chunk_count)
    return replace(result, metadata=metadata)


def _follow_up_composer_metadata(artifact: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _mapping(artifact.get("evidence"))
    composer = _mapping(evidence.get("composer_result"))
    return _mapping(composer.get("metadata"))


def _stream_status(stream: Any, label: str, detail: str = "") -> None:
    status = getattr(stream, "status", None)
    if callable(status):
        status(label, detail)


def _stream_write_text(stream: Any, text: str) -> None:
    write = getattr(stream, "write", None)
    if callable(write):
        write(text)
        return
    write_block = getattr(stream, "write_block", None)
    if callable(write_block):
        write_block(text)


def _stream_fail(stream: Any, text: str) -> None:
    fail = getattr(stream, "fail", None)
    if callable(fail):
        fail(text)
        return
    write_block = getattr(stream, "write_block", None)
    if callable(write_block) and text:
        write_block(text)
    finish = getattr(stream, "finish", None)
    if callable(finish):
        finish("Failed.")


def _stream_token_callback(stream: Any) -> Any:
    return lambda text: _stream_write_text(stream, text)


def _decision_action_options() -> list[tuple[str, str, str]]:
    return [
        ("approve_execute", "Approve and execute with configured executor", "y / yes"),
        ("approve", "Approve only", "a / approve"),
        ("reject", "Reject", "n / reject"),
        ("refine", "Refine with feedback", "r / refine"),
        ("details", "Show details", "d / details"),
        ("skip", "Skip for now", "q / skip"),
    ]


def _investigation_action_options(executor_id: str) -> list[tuple[str, str, str]]:
    executor = _executor_loading_name(executor_id)
    return [
        ("grant", f"Allow read-only investigation via {executor}", "y / yes"),
        ("reject", "Reject", "n / no"),
        ("details", "Show consent details", "d / details"),
        ("skip", "Skip for now", "q / skip"),
    ]


def _normalize_investigation_action(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"grant", "allow", "approve", "continue", "go", "ok", "y", "yes", "好", "可以", "继续"}:
        return "grant"
    if normalized in {"reject", "deny", "cancel", "n", "no", "取消", "不了"}:
        return "reject"
    if normalized in {"d", "detail", "details"}:
        return "details"
    if normalized in {"q", "quit", "skip"}:
        return "skip"
    return normalized


def _decision_action_menu_text(pending: dict[str, str], options: list[tuple[str, str, str]]) -> Any:
    try:
        from rich import box
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:
        lines = [
            "Decision Action",
            f"approval_id: {pending.get('approval_id', '')}",
            "Use up/down then Enter, or type a shortcut.",
        ]
        lines.extend(f"  {shortcut:<12} {label}" for _, label, shortcut in options)
        return "\n".join(lines)

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style=SpiceTheme.DIM, no_wrap=True)
    table.add_column(style=SpiceTheme.CANDIDATE)
    for _, label, shortcut in options:
        table.add_row(shortcut, label)
    return Panel(
        table,
        title="[bold red]DECISION ACTION[/bold red]",
        subtitle=f"approval_id: {pending.get('approval_id', '')}",
        border_style=SpiceTheme.PANEL_BORDER,
        box=box.ROUNDED,
    )


def _pending_approval_choice_text(approvals: list[Any]) -> Any:
    try:
        from rich import box
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:
        lines = ["Pending approvals:"]
        for index, approval in enumerate(approvals, start=1):
            lines.append(f"{index}. {approval.approval_id} - {_approval_summary(approval)}")
        lines.append("Select approval with up/down then Enter, or type a number.")
        return "\n".join(lines)

    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("#", style=SpiceTheme.DIM, no_wrap=True)
    table.add_column("approval_id", style=SpiceTheme.DIM)
    table.add_column("summary")
    for index, approval in enumerate(approvals, start=1):
        table.add_row(str(index), approval.approval_id, _approval_summary(approval))
    return Panel(
        table,
        title="[bold red]PENDING APPROVALS[/bold red]",
        subtitle="Use up/down then Enter, or type a number.",
        border_style=SpiceTheme.PANEL_BORDER,
        box=box.ROUNDED,
    )


def _inline_choice_fragments(
    *,
    title: str,
    rows: list[tuple[str, str, str]],
    selected_index: int,
    footer: str = "",
    prompt_label: str = "",
) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = [
        ("class:title", f"{title}\n"),
        ("class:hint", "  ↑↓ navigate   ENTER/SPACE select   ESC cancel\n\n"),
    ]
    for index, (shortcut, label, detail) in enumerate(rows):
        selected = index == selected_index
        prefix = "→ (●)" if selected else "  (○)"
        style = "class:selected" if selected else "class:choice"
        fragments.append((style, f"{prefix} {label}"))
        if detail:
            fragments.append(("class:shortcut", f"  {detail}"))
        elif shortcut:
            fragments.append(("class:shortcut", f"  {shortcut}"))
        fragments.append(("", "\n"))
    if footer:
        fragments.extend([("", "\n"), ("class:hint", f"{footer}\n")])
    if prompt_label:
        fragments.extend([("class:prompt", f"{prompt_label}> "), ("class:cursor", "█")])
    return fragments


def _approval_summary(approval: Any) -> str:
    candidate = str(getattr(approval, "candidate_id", "") or "candidate unknown")
    prompt = str(getattr(approval, "prompt", "") or "").strip()
    if prompt:
        first_line = prompt.splitlines()[0].strip()
        if first_line:
            return first_line[:80]
    return candidate[:80]


def _execution_response_summary(execution: dict[str, Any]) -> str:
    status = str(execution.get("task_status") or execution.get("protocol_status") or "unknown")
    outcome_id = str(execution.get("outcome_id") or "")
    approval_id = str(execution.get("approval_id") or "")
    if outcome_id:
        return f"Execution {status}; outcome {outcome_id}"
    if approval_id:
        return f"Execution {status}; approval {approval_id}"
    return f"Execution {status}"


def _execution_conversation_artifact_refs(
    store: LocalJsonStore,
    artifact: dict[str, Any],
    *,
    approval_id: str,
    decision_id: str,
    run_id: str,
    outcome_id: str,
) -> dict[str, str]:
    refs = {
        key: str(value)
        for key, value in _dict(artifact.get("store_paths")).items()
        if isinstance(key, str) and isinstance(value, str) and value
    }
    if approval_id and "approval" not in refs:
        refs["approval"] = _workspace_relative(store.record_path("approval", approval_id))
    if decision_id and "decision" not in refs:
        refs["decision"] = _workspace_relative(store.record_path("decision", decision_id))
    if run_id and "run" not in refs:
        refs["run"] = _workspace_relative(store.record_path("run", run_id))
    if outcome_id and "outcome" not in refs:
        refs["outcome"] = _workspace_relative(store.record_path("outcome", outcome_id))
    return refs


def _conversation_response_summary(text: str) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= 360:
        return compact
    return compact[:357].rstrip() + "..."


def _composer_result_payload(result: ComposerResult) -> dict[str, Any]:
    if hasattr(result, "to_payload"):
        payload = result.to_payload()
        return payload if isinstance(payload, dict) else {}
    return {
        "schema_version": COMPOSER_RESULT_SCHEMA_VERSION,
        "composer_kind": str(getattr(result, "composer_kind", "") or ""),
        "enabled": bool(getattr(result, "enabled", False)),
        "status": str(getattr(result, "status", "") or ""),
        "response_text": str(getattr(result, "response_text", "") or ""),
        "deterministic_text": str(getattr(result, "deterministic_text", "") or ""),
        "model_provider": str(getattr(result, "model_provider", "") or ""),
        "model_id": str(getattr(result, "model_id", "") or ""),
        "request_id": str(getattr(result, "request_id", "") or ""),
        "error": str(getattr(result, "error", "") or ""),
        "raw_output": str(getattr(result, "raw_output", "") or ""),
        "fallback_reason": str(getattr(result, "fallback_reason", "") or ""),
        "facts": dict(getattr(result, "facts", {}) or {}),
        "metadata": dict(getattr(result, "metadata", {}) or {}),
    }


def _datetime_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _workspace_relative(path: Path) -> str:
    parts = path.parts
    if ".spice" in parts:
        index = parts.index(".spice")
        return str(Path(*parts[index:]))
    return str(path)


def _normalize_decision_action(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "y": "approve_execute",
        "yes": "approve_execute",
        "approve_execute": "approve_execute",
        "approve+execute": "approve_execute",
        "a": "approve",
        "approve": "approve",
        "n": "reject",
        "no": "reject",
        "reject": "reject",
        "r": "refine",
        "refine": "refine",
        "d": "details",
        "detail": "details",
        "details": "details",
        "q": "skip",
        "skip": "skip",
    }
    return aliases.get(normalized, normalized)


def _permission_escalation_text(footer: str) -> str:
    return "\n".join(
        [
            "Higher execution permission required",
            footer,
            "",
            "Choose:",
            "  y / yes      escalate and execute",
            "  n / no       keep pending",
            "  d / details  show details",
        ]
    )


def _permission_escalation_details(
    *,
    approval_id: str,
    executor_id: str,
    current_permission: str,
    required_permission: str,
    reason: str,
) -> str:
    return "\n".join(
        [
            "Execution permission details",
            f"approval_id: {approval_id}",
            f"executor: {executor_id}",
            f"current_permission: {current_permission}",
            f"required_permission: {required_permission}",
            f"reason: {reason}",
            "",
            "If approved, Spice uses the higher permission only for this execution.",
        ]
    )


def _executor_policy_permission_boundary_text(
    *,
    executor_id: str,
    current_permission: str,
    required_permission: str,
    reason: str,
) -> str:
    executor = _executor_loading_name(executor_id)
    lines = [
        "Execution permission is controlled by the executor policy.",
        (
            f"This approval requires {required_permission}, but Spice is configured for "
            f"{current_permission} with {executor}."
        ),
        f"reason: {reason}",
        "",
        "Spice will not change the executor's own policy automatically.",
    ]
    if executor_id == "openclaw":
        lines.extend(
            [
                "For OpenClaw, inspect or change policy outside Spice:",
                "  openclaw exec-policy show --json",
                "  openclaw sandbox explain --json",
                "  openclaw exec-policy preset cautious",
                "",
                "After the policy and .spice executor_permission_mode match this request, retry the approval.",
            ]
        )
    else:
        lines.append("Update the executor policy or Spice executor_permission_mode, then retry the approval.")
    return "\n".join(lines)


def _runtime_mode(config: dict[str, Any]) -> str:
    executor = str(config.get("executor") or "dry_run")
    llm = str(config.get("llm_provider") or "deterministic")
    if executor == "dry_run" and llm == "deterministic":
        return "decision + dry-run"
    if executor == "dry_run":
        return "LLM decision + dry-run"
    executor_name = _executor_loading_name(executor)
    if llm == "deterministic":
        return f"decision + {executor_name} handoff"
    return f"LLM decision + {executor_name} handoff"


def _decision_status_label(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized == "act":
        return "Thinking through the execution decision..."
    if normalized == "advise":
        return "Thinking through the decision..."
    if normalized == "refine":
        return "Revisiting the decision..."
    return "Thinking through the decision..."


def _runtime_model_detail(config: dict[str, Any]) -> str:
    provider = str(config.get("llm_provider") or "deterministic").strip()
    model = str(config.get("llm_model") or "").strip()
    if provider and provider != "deterministic" and model:
        return f"{provider}/{model}"
    if provider and provider != "deterministic":
        return provider
    return "deterministic runtime"


def _executor_loading_name(executor_id: str) -> str:
    normalized = executor_id.strip().lower()
    return {
        "dry_run": "dry-run executor",
        "sdep_subprocess": "SDEP executor",
        "codex": "Codex",
        "claude_code": "Claude Code",
        "hermes": "Hermes",
        "openclaw": "OpenClaw",
    }.get(normalized, normalized or "executor")


def _executor_readiness(config: dict[str, Any]) -> list[dict[str, str]]:
    try:
        configured_config = SpiceWorkspaceConfig.from_payload(config)
    except Exception:
        configured_config = SpiceWorkspaceConfig()
    configured = str(config.get("executor") or "dry_run")
    items: list[dict[str, str]] = []
    for executor in ["dry_run", "sdep_subprocess", "codex", "claude_code", "hermes", "openclaw"]:
        if executor == "dry_run":
            status = "ready"
        elif configured == executor:
            runtime = resolve_executor_runtime_from_config(configured_config)
            status = "configured" if runtime.status == "ready" else runtime.detail
        else:
            status = "not_configured"
        items.append({"name": executor, "status": status})
    return items


def _skill_readiness() -> list[dict[str, str]]:
    return [
        {"name": "item.triage", "status": "ready"},
        {"name": "artifact.draft", "status": "ready"},
        {"name": "task.split", "status": "ready"},
        {"name": "intent.execute", "status": "ready"},
        {"name": "capability.use", "status": "ready"},
    ]


def _perception_readiness(config: dict[str, Any]) -> list[dict[str, str]]:
    configured = str(config.get("perception_provider") or "manual")
    poll_ready = bool(
        str(config.get("perception_poll_url") or "").strip()
        or str(config.get("perception_poll_command") or "").strip()
    )
    open_chronicle_url = str(config.get("openchronicle_mcp_url") or "").strip()
    return [
        {"name": "manual", "status": "ready"},
        {
            "name": "poll",
            "status": "configured" if configured == "poll" and poll_ready else "needs poll source",
        },
        {
            "name": "open_chronicle",
            "status": "configured" if configured == "open_chronicle" and open_chronicle_url else "needs MCP endpoint",
        },
    ]


def _split_command(line: str) -> tuple[str, str]:
    return split_slash_command(line)


def _split_first(value: str) -> tuple[str, str]:
    parts = value.split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""


def _parse_perceive_args(value: str) -> dict[str, Any]:
    tokens = shlex.split(value)
    options: dict[str, Any] = {
        "provider": None,
        "poll_url": None,
        "poll_command": None,
        "openchronicle_mcp_url": None,
        "openchronicle_since_minutes": None,
        "openchronicle_context_limit": None,
        "allow_command_poll": None,
        "decide_on_change": None,
        "timeout_seconds": None,
    }
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--provider":
            options["provider"] = _next_value(tokens, index, token)
            index += 2
            continue
        if token == "--poll-url":
            options["poll_url"] = _next_value(tokens, index, token)
            index += 2
            continue
        if token == "--poll-command":
            options["poll_command"] = _next_value(tokens, index, token)
            index += 2
            continue
        if token == "--allow-command-poll":
            options["allow_command_poll"] = True
            index += 1
            continue
        if token == "--decide-on-change":
            options["decide_on_change"] = True
            index += 1
            continue
        if token == "--openchronicle-mcp-url":
            options["openchronicle_mcp_url"] = _next_value(tokens, index, token)
            index += 2
            continue
        if token == "--openchronicle-since-minutes":
            options["openchronicle_since_minutes"] = _positive_int(
                _next_value(tokens, index, token),
                token,
            )
            index += 2
            continue
        if token == "--openchronicle-context-limit":
            options["openchronicle_context_limit"] = _positive_int(
                _next_value(tokens, index, token),
                token,
            )
            index += 2
            continue
        if token == "--timeout":
            options["timeout_seconds"] = _positive_int(_next_value(tokens, index, token), token)
            index += 2
            continue
        raise ValueError(f"unknown /perceive option: {token}")
    return options


def _next_value(tokens: list[str], index: int, option: str) -> str:
    next_index = index + 1
    if next_index >= len(tokens) or tokens[next_index].startswith("--"):
        raise ValueError(f"{option} requires a value")
    return tokens[next_index]


def _positive_int(value: str, option: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{option} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{option} must be positive")
    return parsed
