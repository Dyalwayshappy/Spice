from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spice.decision import (
    DEFAULT_LOCAL_DECISION_PROFILE,
    DEFAULT_LOCAL_SUPPORT_PROFILE,
    DecisionGuidanceSupport,
    explain_decision_guidance,
    format_decision_guidance_explanation,
    init_decision_profile,
)
from spice.decision.compare import render_compare_json, render_compare_text
from spice.decision.compare_payload import load_compare_payload
from spice.decision.compare_rich import render_compare_rich
from spice.entry.assist import (
    ASSIST_MAX_TRIES_DEFAULT,
    capture_brief,
    resolve_assist_model,
    run_assist_session,
    write_assist_artifacts,
)
from spice.entry.init_domain import run_init_domain, run_init_domain_from_spec
from spice.entry.quickstart import (
    QUICKSTART_DEFAULT_OUTPUT,
    QUICKSTART_LLM_DEFAULT_OUTPUT,
    IntegratedQuickstartReport,
    QuickstartReport,
    run_integrated_quickstart,
    run_quickstart,
)
from spice.runtime import (
    LocalJsonStore,
    archive_session,
    approve_approval,
    build_executor_status,
    build_session_timeline,
    configure_workspace_llm,
    compile_workspace_decision_context_payload,
    delete_session,
    execute_claude_code_approval,
    execute_codex_approval,
    execute_dry_run_approval,
    execute_hermes_approval,
    execute_openclaw_approval,
    execute_sdep_subprocess_approval,
    load_workspace_config,
    list_sessions,
    list_approvals,
    load_approval,
    perceive_once,
    perceive_watch,
    reject_approval,
    refine_decision,
    render_approval_details,
    render_approval_list,
    render_approval_resolution,
    run_interactive_shell,
    render_executor_doctor,
    render_executor_list,
    render_session_current,
    render_session_delete_result,
    render_session_list,
    render_session_resume,
    render_session_search,
    render_session_stats,
    render_session_timeline,
    render_doctor_report,
    render_decision_context_text,
    require_workspace,
    resolve_executor_runtime_from_config,
    run_once,
    run_doctor,
    run_setup_wizard,
    search_sessions,
    session_stats,
    set_workspace_active_session,
    setup_workspace,
    run_tui_shell,
    update_workspace_config,
    workspace_paths,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice",
        description="Spice entry tooling.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser(
        "setup",
        help="Initialize a local .spice workspace.",
    )
    setup.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root where .spice/ should be created (default: current directory).",
    )
    setup.add_argument(
        "--force",
        action="store_true",
        help="Overwrite default workspace files that already exist.",
    )
    setup.add_argument(
        "--defaults",
        action="store_true",
        help="Skip the interactive setup wizard and write default local settings.",
    )
    setup.set_defaults(handler=_handle_setup)

    run = subparsers.add_parser(
        "run",
        help="Run Spice against a manual intent.",
    )
    run.add_argument(
        "--once",
        type=str,
        default=None,
        help="Run one manual-intent decision cycle.",
    )
    run.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    run.add_argument(
        "--session-id",
        default=None,
        help=(
            "Session id to use for run --once or the interactive shell. "
            "Defaults to the workspace active session."
        ),
    )
    run.add_argument(
        "--json",
        action="store_true",
        help="Print the run artifact as JSON instead of the readable decision card.",
    )
    run.add_argument(
        "--no-bars",
        action="store_true",
        help="Disable terminal score bars in the rendered decision card.",
    )
    run.add_argument(
        "--rich",
        action="store_true",
        help="Render the Decision Card with Rich-lite panels when available.",
    )
    run.add_argument(
        "--plain",
        action="store_true",
        help="When running interactively, force the plain text shell instead of the TUI shell.",
    )
    run.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not update .spice/state/state.json; still save run and decision artifacts.",
    )
    run.add_argument(
        "--full-loop-preview",
        action="store_true",
        help=(
            "Include the read-only skill/context/SDEP handoff preview. "
            "This is the default for run --once and is kept for compatibility."
        ),
    )
    run.add_argument(
        "--decision-only",
        action="store_true",
        help=(
            "Stop after the Decision Card instead of rendering the full read-only "
            "approval/skill/context/SDEP handoff preview."
        ),
    )
    run_mode = run.add_mutually_exclusive_group()
    run_mode.add_argument(
        "--act",
        action="store_true",
        help="Treat the input as an executable intent and require an execution-handoff candidate.",
    )
    run_mode.add_argument(
        "--advise",
        action="store_true",
        help="Treat the input as advisory and stop at the Decision Card.",
    )
    run.set_defaults(handler=_handle_run)

    shell = subparsers.add_parser(
        "shell",
        help="Launch the interactive Spice shell.",
    )
    shell.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    shell.add_argument(
        "--session-id",
        default=None,
        help="Session id to use. Defaults to the workspace active session.",
    )
    shell.add_argument(
        "--plain",
        action="store_true",
        help="Force the plain text shell instead of the Rich/prompt_toolkit shell.",
    )
    shell.add_argument(
        "--no-bars",
        action="store_true",
        help="Disable score bars in rendered decision cards.",
    )
    shell.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not update .spice/state/state.json; still save run and decision artifacts.",
    )
    shell_mode = shell.add_mutually_exclusive_group()
    shell_mode.add_argument(
        "--act",
        action="store_true",
        help="Default shell intents require an execution-handoff candidate.",
    )
    shell_mode.add_argument(
        "--advise",
        action="store_true",
        help="Default shell intents are advisory and stop at the Decision Card.",
    )
    shell.set_defaults(handler=_handle_shell)

    decide = subparsers.add_parser(
        "decide",
        help="Make one Spice decision for a manual intent.",
    )
    decide.add_argument("intent", help="Manual intent to turn into a Spice decision.")
    decide.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    decide.add_argument(
        "--session-id",
        default=None,
        help="Session id to use. Defaults to the workspace active session.",
    )
    decide.add_argument(
        "--json",
        action="store_true",
        help="Print the run artifact as JSON instead of the readable decision card.",
    )
    decide.add_argument(
        "--no-bars",
        action="store_true",
        help="Disable terminal score bars in the rendered decision card.",
    )
    decide.add_argument(
        "--rich",
        action="store_true",
        help="Render the Decision Card with Rich-lite panels when available.",
    )
    decide.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not update .spice/state/state.json; still save run and decision artifacts.",
    )
    decide.add_argument(
        "--decision-only",
        action="store_true",
        help=(
            "Stop after the Decision Card instead of rendering the full read-only "
            "approval/skill/context/SDEP handoff preview."
        ),
    )
    decide_mode = decide.add_mutually_exclusive_group()
    decide_mode.add_argument(
        "--act",
        action="store_true",
        help="Treat the input as an executable intent and require an execution-handoff candidate.",
    )
    decide_mode.add_argument(
        "--advise",
        action="store_true",
        help="Treat the input as advisory and stop at the Decision Card.",
    )
    decide.set_defaults(handler=_handle_decide)

    refine = subparsers.add_parser(
        "refine",
        help="Refine the latest decision card with user feedback.",
    )
    refine.add_argument("refinement", help="Feedback or option to add to the previous decision.")
    refine.add_argument(
        "--run-id",
        default=None,
        help="Run id to refine. Defaults to the active session's latest run.",
    )
    refine.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    refine.add_argument(
        "--session-id",
        default=None,
        help="Session id to use. Defaults to the workspace active session.",
    )
    refine.add_argument(
        "--json",
        action="store_true",
        help="Print the refine artifact as JSON instead of text.",
    )
    refine.add_argument(
        "--no-bars",
        action="store_true",
        help="Disable terminal score bars in the rendered decision card.",
    )
    refine.add_argument(
        "--rich",
        action="store_true",
        help="Render the updated Decision Card with Rich-lite panels when available.",
    )
    refine.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not update .spice/state/state.json; still save refine artifacts.",
    )
    refine.add_argument(
        "--decision-only",
        action="store_true",
        help="Stop after the updated Decision Card instead of rendering the full handoff preview.",
    )
    refine_mode = refine.add_mutually_exclusive_group()
    refine_mode.add_argument(
        "--act",
        action="store_true",
        help="Evaluate only execution-handoff candidates after refinement.",
    )
    refine_mode.add_argument(
        "--advise",
        action="store_true",
        help="Evaluate refinement as advisory and stop at the Decision Card.",
    )
    refine.set_defaults(handler=_handle_refine)

    session = subparsers.add_parser(
        "session",
        help="Inspect local Spice decision sessions.",
    )
    session_subparsers = session.add_subparsers(dest="session_command", required=True)
    session_list = session_subparsers.add_parser(
        "list",
        help="List local decision loop sessions.",
    )
    session_list.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_list.add_argument(
        "--json",
        action="store_true",
        help="Print sessions as JSON instead of text.",
    )
    session_list.add_argument(
        "--all",
        action="store_true",
        help="Include archived sessions.",
    )
    session_list.set_defaults(handler=_handle_session_list)

    session_current = session_subparsers.add_parser(
        "current",
        help="Show the workspace active session.",
    )
    session_current.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_current.add_argument(
        "--json",
        action="store_true",
        help="Print the current session as JSON instead of text.",
    )
    session_current.set_defaults(handler=_handle_session_current)

    session_switch = session_subparsers.add_parser(
        "switch",
        help="Switch the workspace active session.",
    )
    session_switch.add_argument("session_id", help="Session id to make active.")
    session_switch.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_switch.add_argument(
        "--json",
        action="store_true",
        help="Print the switched session as JSON instead of text.",
    )
    session_switch.set_defaults(handler=_handle_session_switch)

    session_resume = session_subparsers.add_parser(
        "resume",
        help="Show a resumable summary for a local decision loop session.",
    )
    session_resume.add_argument("session_id", help="Session id to inspect.")
    session_resume.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_resume.add_argument(
        "--json",
        action="store_true",
        help="Print the session record as JSON instead of text.",
    )
    session_resume.add_argument(
        "--start",
        action="store_true",
        help="Resume this session directly in the interactive shell.",
    )
    session_resume.add_argument(
        "--no-bars",
        action="store_true",
        help="Disable terminal score bars when --start enters the shell.",
    )
    session_resume.set_defaults(handler=_handle_session_resume)

    session_show = session_subparsers.add_parser(
        "show",
        help="Show a local decision loop session without starting the shell.",
    )
    session_show.add_argument("session_id", help="Session id to inspect.")
    session_show.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_show.add_argument(
        "--json",
        action="store_true",
        help="Print the session record as JSON instead of text.",
    )
    session_show.set_defaults(handler=_handle_session_resume)

    session_archive = session_subparsers.add_parser(
        "archive",
        help="Mark a session archived without deleting artifacts.",
    )
    session_archive.add_argument("session_id", help="Session id to archive.")
    session_archive.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_archive.add_argument(
        "--json",
        action="store_true",
        help="Print the archived session as JSON instead of text.",
    )
    session_archive.set_defaults(handler=_handle_session_archive)

    session_timeline = session_subparsers.add_parser(
        "timeline",
        help="Show a session decision timeline.",
    )
    session_timeline.add_argument("session_id", help="Session id to inspect.")
    session_timeline.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_timeline.add_argument(
        "--json",
        action="store_true",
        help="Print timeline entries as JSON instead of text.",
    )
    session_timeline.set_defaults(handler=_handle_session_timeline)

    session_search = session_subparsers.add_parser(
        "search",
        help="Search session decision summaries and rendered run text.",
    )
    session_search.add_argument("keyword", help="Keyword to search for.")
    session_search.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_search.add_argument(
        "--all",
        action="store_true",
        help="Include archived sessions.",
    )
    session_search.add_argument(
        "--json",
        action="store_true",
        help="Print search matches as JSON instead of text.",
    )
    session_search.set_defaults(handler=_handle_session_search)

    session_stats_parser = session_subparsers.add_parser(
        "stats",
        help="Show aggregate local session statistics.",
    )
    session_stats_parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Print stats as JSON instead of text.",
    )
    session_stats_parser.set_defaults(handler=_handle_session_stats)

    session_delete = session_subparsers.add_parser(
        "delete",
        help="Delete a session record, optionally including linked artifacts.",
    )
    session_delete.add_argument("session_id", help="Session id to delete.")
    session_delete.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    session_delete.add_argument(
        "--cascade",
        action="store_true",
        help="Also delete linked run, decision, approval, and outcome artifacts.",
    )
    session_delete.add_argument(
        "--force",
        action="store_true",
        help="Required for --cascade.",
    )
    session_delete.add_argument(
        "--json",
        action="store_true",
        help="Print delete result as JSON instead of text.",
    )
    session_delete.set_defaults(handler=_handle_session_delete)

    approval = subparsers.add_parser(
        "approval",
        help="Inspect and resolve local Spice approvals.",
    )
    approval_subparsers = approval.add_subparsers(dest="approval_command", required=True)
    approval_list = approval_subparsers.add_parser(
        "list",
        help="List local approval checkpoints.",
    )
    approval_list.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    approval_list.add_argument(
        "--status",
        default=None,
        help="Optional approval status filter, such as pending or approved.",
    )
    approval_list.add_argument(
        "--json",
        action="store_true",
        help="Print approvals as JSON instead of text.",
    )
    approval_list.set_defaults(handler=_handle_approval_list)

    approval_show = approval_subparsers.add_parser(
        "show",
        help="Show one approval checkpoint.",
    )
    approval_show.add_argument("approval_id", help="Approval id to inspect.")
    approval_show.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    approval_show.add_argument(
        "--json",
        action="store_true",
        help="Print approval as JSON instead of text.",
    )
    approval_show.set_defaults(handler=_handle_approval_show)

    approval_details = approval_subparsers.add_parser(
        "details",
        help="Alias for approval show.",
    )
    approval_details.add_argument("approval_id", help="Approval id to inspect.")
    approval_details.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    approval_details.add_argument(
        "--json",
        action="store_true",
        help="Print approval as JSON instead of text.",
    )
    approval_details.set_defaults(handler=_handle_approval_show)

    approval_approve = approval_subparsers.add_parser(
        "approve",
        help="Approve a pending checkpoint without executing it.",
    )
    approval_approve.add_argument("approval_id", help="Approval id to approve.")
    approval_approve.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    approval_approve.add_argument("--reason", default="", help="Optional approval reason.")
    approval_approve.add_argument(
        "--json",
        action="store_true",
        help="Print resolution result as JSON instead of text.",
    )
    approval_approve.set_defaults(handler=_handle_approval_approve)

    approval_reject = approval_subparsers.add_parser(
        "reject",
        help="Reject a pending checkpoint without executing it.",
    )
    approval_reject.add_argument("approval_id", help="Approval id to reject.")
    approval_reject.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    approval_reject.add_argument("--reason", default="", help="Optional rejection reason.")
    approval_reject.add_argument(
        "--json",
        action="store_true",
        help="Print resolution result as JSON instead of text.",
    )
    approval_reject.set_defaults(handler=_handle_approval_reject)

    execute = subparsers.add_parser(
        "execute",
        help="Execute an approved decision using the workspace default executor.",
        usage=(
            "spice execute <approval_id> [--workspace PATH] [--timeout SECONDS] [--json]\n"
            "             spice execute dry-run <approval_id> [--workspace PATH] [--json]\n"
            "             spice execute codex <approval_id> [--command CMD] [--workspace PATH] "
            "[--timeout SECONDS] [--json]\n"
            "             spice execute claude-code <approval_id> [--command CMD] [--workspace PATH] "
            "[--timeout SECONDS] [--json]\n"
            "             spice execute hermes <approval_id> [--command CMD] [--workspace PATH] "
            "[--timeout SECONDS] [--json]\n"
            "             spice execute openclaw <approval_id> [--command CMD] [--workspace PATH] "
            "[--timeout SECONDS] [--json]\n"
            "             spice execute sdep <approval_id> --command CMD [--workspace PATH] "
            "[--timeout SECONDS] [--json]"
        ),
        epilog=(
            "By default, Spice reads .spice/config.json and dispatches to the configured "
            "executor. Use 'dry-run', 'codex', 'claude-code', 'hermes', 'openclaw', "
            "or 'sdep' to explicitly override the configured executor."
        ),
    )
    execute.add_argument(
        "execute_args",
        nargs=argparse.REMAINDER,
        help=argparse.SUPPRESS,
    )
    execute.set_defaults(handler=_handle_execute_dispatch)

    executor = subparsers.add_parser(
        "executor",
        help="Inspect local executor configuration and CLI availability.",
    )
    executor_subparsers = executor.add_subparsers(dest="executor_command", required=True)
    executor_list = executor_subparsers.add_parser(
        "list",
        help="List supported executors and local CLI discovery status.",
    )
    executor_list.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    executor_list.add_argument("--json", action="store_true", help="Print executor status as JSON.")
    executor_list.set_defaults(handler=_handle_executor_list)

    executor_doctor = executor_subparsers.add_parser(
        "doctor",
        help="Diagnose the configured executor runtime.",
    )
    executor_doctor.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    executor_doctor.add_argument("--json", action="store_true", help="Print executor doctor as JSON.")
    executor_doctor.set_defaults(handler=_handle_executor_doctor)

    perceive = subparsers.add_parser(
        "perceive",
        help="Pull external signals into General state without triggering decision or execution.",
    )
    perceive.add_argument(
        "--provider",
        default=None,
        choices=["open_chronicle", "poll"],
        help="Perception provider to run (default: workspace perception_provider).",
    )
    perceive.add_argument(
        "--once",
        action="store_true",
        help="Run one perception poll. This is the default unless --watch is provided.",
    )
    perceive.add_argument(
        "--watch",
        action="store_true",
        help="Run foreground polling until interrupted.",
    )
    perceive.add_argument("--poll-url", default=None, help="URL to poll with stdlib urllib.")
    perceive.add_argument(
        "--poll-command",
        default=None,
        help="Command to poll. Requires --allow-command-poll.",
    )
    perceive.add_argument(
        "--allow-command-poll",
        action="store_true",
        help="Explicitly allow command polling. Uses shell=False.",
    )
    perceive.add_argument(
        "--openchronicle-mcp-url",
        default=None,
        help="Open Chronicle MCP endpoint (default: workspace openchronicle_mcp_url).",
    )
    perceive.add_argument(
        "--openchronicle-since-minutes",
        type=int,
        default=None,
        help="Open Chronicle recent_activity lookback window in minutes.",
    )
    perceive.add_argument(
        "--openchronicle-context-limit",
        type=int,
        default=None,
        help="Open Chronicle current_context/recent_activity item limit.",
    )
    perceive.add_argument(
        "--decide-on-change",
        action="store_true",
        help="When poll output changes, generate a Decision Card and pending approval. Never executes.",
    )
    perceive.add_argument(
        "--poll-interval",
        type=int,
        default=None,
        help="Foreground watch interval in seconds.",
    )
    perceive.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="URL/command poll timeout in seconds.",
    )
    perceive.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    perceive.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    perceive.add_argument(
        "--json",
        action="store_true",
        help="Print perception artifact as JSON instead of text.",
    )
    perceive.set_defaults(handler=_handle_perceive)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check local Spice workspace health.",
    )
    doctor.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        help="Print doctor report as JSON instead of text.",
    )
    doctor.set_defaults(handler=_handle_doctor)

    context = subparsers.add_parser(
        "context",
        help="Show the compiled decision context sent to model-facing runtime steps.",
    )
    context.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    context.add_argument(
        "--session-id",
        default=None,
        help="Session id to compile context for. Defaults to the workspace active session.",
    )
    context.add_argument(
        "--json",
        action="store_true",
        help="Print the exact compiled context payload as JSON.",
    )
    context.set_defaults(handler=_handle_context)

    config = subparsers.add_parser(
        "config",
        help="Inspect or update local Spice workspace config.",
    )
    config_subparsers = config.add_subparsers(dest="config_command", required=True)
    config_show = config_subparsers.add_parser(
        "show",
        help="Show .spice/config.json.",
    )
    config_show.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    config_show.add_argument(
        "--json",
        action="store_true",
        help="Print workspace config as JSON instead of text.",
    )
    config_show.set_defaults(handler=_handle_config_show)

    config_set = config_subparsers.add_parser(
        "set",
        help="Set one workspace config key.",
    )
    config_set.add_argument(
        "key",
        help="Config key, such as executor, executor_command, or workspace_perception.depth.",
    )
    config_set.add_argument("value", help="Config value.")
    config_set.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    config_set.add_argument(
        "--json",
        action="store_true",
        help="Print updated workspace config as JSON instead of text.",
    )
    config_set.set_defaults(handler=_handle_config_set)

    config_enable_llm = config_subparsers.add_parser(
        "enable-llm",
        help="Configure LLM candidate expansion and simulation.",
    )
    config_enable_llm.add_argument(
        "--provider",
        required=True,
        choices=["anthropic", "deepseek", "deterministic", "mimo", "openai", "openrouter", "subprocess"],
        help="LLM provider to use.",
    )
    config_enable_llm.add_argument(
        "--model",
        default="",
        help="Model id for the selected provider, such as gpt-4o-mini.",
    )
    config_enable_llm.add_argument(
        "--no-candidate-expand",
        action="store_true",
        help="Leave llm_candidate_expand disabled.",
    )
    config_enable_llm.add_argument(
        "--no-simulation",
        action="store_true",
        help="Leave llm_simulation disabled.",
    )
    config_enable_llm.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    config_enable_llm.add_argument(
        "--json",
        action="store_true",
        help="Print updated workspace config as JSON instead of text.",
    )
    config_enable_llm.set_defaults(handler=_handle_config_enable_llm)

    quickstart = subparsers.add_parser(
        "quickstart",
        help="Run the Spice quickstart flow.",
    )
    quickstart.add_argument(
        "--output",
        type=Path,
        default=QUICKSTART_DEFAULT_OUTPUT,
        help=(
            "Output directory for the core example scaffold "
            "(default: .spice/quickstart)."
        ),
    )
    quickstart.add_argument(
        "--llm-output",
        type=Path,
        default=QUICKSTART_LLM_DEFAULT_OUTPUT,
        help=(
            "Output directory for the LLM-ready example runtime "
            "(default: .spice/quickstart_llm)."
        ),
    )
    quickstart.add_argument(
        "--decision-profile",
        type=Path,
        default=DEFAULT_LOCAL_DECISION_PROFILE,
        help=(
            "Local decision.md path for the full quickstart "
            "(default: .spice/decision/decision.md)."
        ),
    )
    quickstart.add_argument(
        "--support-output",
        type=Path,
        default=DEFAULT_LOCAL_SUPPORT_PROFILE,
        help=(
            "Reference support JSON path for the full quickstart "
            "(default: .spice/decision/support/default_support.json)."
        ),
    )
    quickstart.add_argument(
        "--force",
        action="store_true",
        help="Replace existing quickstart output paths.",
    )
    quickstart.add_argument(
        "--no-run",
        action="store_true",
        help="Generate files and artifacts but skip executing run_demo.py.",
    )
    quickstart.add_argument(
        "--core-only",
        action="store_true",
        help="Run only the deterministic core-loop quickstart.",
    )
    quickstart.set_defaults(handler=_handle_quickstart)

    decision_parser = subparsers.add_parser(
        "decision",
        help="Inspect decision.md guidance.",
    )
    decision_subparsers = decision_parser.add_subparsers(
        dest="decision_command",
        required=True,
    )
    decision_init = decision_subparsers.add_parser(
        "init",
        help="Copy the bundled default decision profile into this project.",
    )
    decision_init.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_LOCAL_DECISION_PROFILE,
        help="Local decision profile path (default: .spice/decision/decision.md).",
    )
    decision_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing local decision profile and copied support reference.",
    )
    decision_init.add_argument(
        "--no-support",
        action="store_true",
        help="Do not copy the reference support JSON used for explain/demo/debug flows.",
    )
    decision_init.set_defaults(handler=_handle_decision_init)

    decision_explain = decision_subparsers.add_parser(
        "explain",
        help="Validate and explain a decision.md file.",
    )
    decision_explain.add_argument(
        "path",
        type=Path,
        help="Path to decision.md.",
    )
    decision_explain.add_argument(
        "--support-json",
        type=Path,
        default=None,
        help=(
            "Optional JSON file declaring score_dimensions, constraint_ids, "
            "and tradeoff_rule_ids supported by the active policy/domain adapter."
        ),
    )
    decision_explain.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of the concise text report.",
    )
    decision_explain.set_defaults(handler=_handle_decision_explain)

    decision_compare = decision_subparsers.add_parser(
        "compare",
        help="Render a human-readable decision comparison artifact.",
    )
    decision_compare.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to a decision comparison JSON artifact.",
    )
    decision_compare.add_argument(
        "--json",
        action="store_true",
        help="Print normalized JSON instead of text output.",
    )
    decision_compare.add_argument(
        "--no-bars",
        action="store_true",
        help="Disable terminal score bars in text output.",
    )
    decision_compare.add_argument(
        "--show-execution",
        action="store_true",
        help="Show the downstream execution boundary section in text output.",
    )
    decision_compare.set_defaults(handler=_handle_decision_compare)

    init_parser = subparsers.add_parser(
        "init",
        help="Initialize new artifacts from DomainSpec templates.",
    )
    init_subparsers = init_parser.add_subparsers(dest="init_command", required=True)
    init_domain = init_subparsers.add_parser(
        "domain",
        help="Interactively create a runnable Spice domain scaffold.",
    )
    init_domain.add_argument("name", help="Domain project folder name.")
    init_domain.add_argument(
        "--from-spec",
        type=Path,
        default=None,
        help="Use an existing DomainSpec JSON file instead of interactive prompts.",
    )
    init_domain.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: ./<name>).",
    )
    init_domain.add_argument(
        "--force",
        action="store_true",
        help="Replace existing output directory.",
    )
    init_domain.add_argument(
        "--no-run",
        action="store_true",
        help="Generate scaffold and artifacts but skip executing run_demo.py.",
    )
    init_domain.add_argument(
        "--with-llm",
        action="store_true",
        help=(
            "Generate scaffold with optional domain-level LLM decision/simulation wiring. "
            "This is template-level activation only (DomainSpec schema is unchanged)."
        ),
    )
    init_domain.add_argument(
        "--assist",
        action="store_true",
        help="Draft DomainSpec from a natural-language brief via LLM-assisted flow.",
    )
    init_domain.add_argument(
        "--assist-brief-file",
        type=Path,
        default=None,
        help="Read assist brief text from file.",
    )
    init_domain.add_argument(
        "--assist-stdin",
        action="store_true",
        help="Read assist brief from stdin (terminate with END line).",
    )
    init_domain.add_argument(
        "--assist-model",
        type=str,
        default=None,
        help=(
            "Model override for assist drafting. "
            "Use 'deterministic' to force deterministic provider; "
            "otherwise value is treated as a subprocess command "
            "(example: \"ollama run qwen2.5\")."
        ),
    )
    init_domain.add_argument(
        "--assist-max-tries",
        type=int,
        default=ASSIST_MAX_TRIES_DEFAULT,
        help=f"Max draft retries for invalid assist output (default: {ASSIST_MAX_TRIES_DEFAULT}).",
    )
    init_domain.set_defaults(handler=_handle_init_domain)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = _normalize_argv(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["shell"]
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return int(handler(args))


def _normalize_argv(argv: list[str]) -> list[str]:
    return list(argv)


def _execute_default_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice execute",
        description="Execute an approval using the workspace default executor.",
    )
    parser.add_argument("approval_id", help="Approved approval id to execute.")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Subprocess timeout in seconds when executor=sdep_subprocess (default: 120).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print execution artifact as JSON instead of text.",
    )
    return parser


def _execute_dry_run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice execute dry-run",
        description="Run the approved handoff through the local dry-run executor bridge.",
    )
    parser.add_argument("approval_id", help="Approved approval id to dry-run.")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print dry-run execution artifact as JSON instead of text.",
    )
    return parser


def _execute_sdep_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice execute sdep",
        description="Send an approved planned SDEP request to a local subprocess executor.",
    )
    parser.add_argument("approval_id", help="Approved approval id to execute.")
    parser.add_argument(
        "--command",
        required=True,
        help="Subprocess command, for example: python -m spice.runtime.sdep_echo_executor",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Subprocess timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print SDEP subprocess execution artifact as JSON instead of text.",
    )
    return parser


def _execute_codex_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice execute codex",
        description="Run an approved SDEP handoff through a local Codex command.",
    )
    parser.add_argument("approval_id", help="Approved approval id to execute with Codex.")
    parser.add_argument(
        "--command",
        default="codex",
        help="Codex command to run. The task/context prompt is passed on stdin (default: codex).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Codex command timeout in seconds (default: 600).",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print Codex execution artifact as JSON instead of text.",
    )
    return parser


def _execute_claude_code_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice execute claude-code",
        description="Run an approved SDEP handoff through a local Claude Code command.",
    )
    parser.add_argument("approval_id", help="Approved approval id to execute with Claude Code.")
    parser.add_argument(
        "--command",
        default="claude",
        help="Claude Code command to run. The task/context prompt is passed on stdin (default: claude).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Claude Code command timeout in seconds (default: 600).",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print Claude Code execution artifact as JSON instead of text.",
    )
    return parser


def _execute_hermes_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice execute hermes",
        description="Run an approved SDEP handoff through a local Hermes command.",
    )
    parser.add_argument("approval_id", help="Approved approval id to execute with Hermes.")
    parser.add_argument(
        "--command",
        default="hermes chat -Q",
        help=(
            "Hermes command to run. `hermes chat` receives the task/context prompt "
            "as `-q QUERY`; custom commands receive stdin (default: hermes chat -Q)."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Hermes command timeout in seconds (default: 600).",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print Hermes execution artifact as JSON instead of text.",
    )
    return parser


def _execute_openclaw_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice execute openclaw",
        description="Run an approved SDEP handoff through a local OpenClaw command.",
    )
    parser.add_argument("approval_id", help="Approved approval id to execute with OpenClaw.")
    parser.add_argument(
        "--command",
        default="openclaw agent --json --message",
        help=(
            "OpenClaw command to run. `openclaw agent` receives the task/context prompt "
            "as `--message MESSAGE`; custom commands receive stdin "
            "(default: openclaw agent --json --message)."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="OpenClaw command timeout in seconds (default: 600).",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Project root containing .spice/ (default: current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print OpenClaw execution artifact as JSON instead of text.",
    )
    return parser


def _print_cli_error(
    command: str,
    error: object,
    *,
    workspace: Path | None = None,
    suggestions: list[str] | None = None,
) -> None:
    message = str(error) or error.__class__.__name__
    print(f"{command} failed: {message}", file=sys.stderr)
    next_steps = suggestions if suggestions is not None else _suggestions_for_error(
        command,
        message,
        workspace=workspace,
    )
    if next_steps:
        print("Next:", file=sys.stderr)
        for step in next_steps:
            print(f"  - {step}", file=sys.stderr)


def _suggestions_for_error(
    command: str,
    message: str,
    *,
    workspace: Path | None = None,
) -> list[str]:
    text = message.lower()
    workspace_flag = _workspace_flag(workspace)

    if "spice workspace is not initialized" in text or "run `spice setup` first" in text:
        return [f"Run `spice setup{workspace_flag}` first."]
    if ".spice/config.json" in text and "no such file" in text:
        return [f"Run `spice setup{workspace_flag}` first."]
    if "no such file or directory" in text:
        return ["Check that the input path exists and retry the command."]
    if "local json store file does not exist" in text:
        if "approval" in command or "/approvals/" in text or "approval." in text:
            return [
                f"Run `spice approval list{workspace_flag}` to find available approvals.",
                "If no approval exists, run `spice decide \"...\" --act` first.",
            ]
        if "session" in command or "/sessions/" in text:
            return [
                f"Run `spice session list{workspace_flag}` to find available sessions.",
                f"Use `spice session current{workspace_flag}` to see the active session.",
            ]
        return [f"Run `spice setup{workspace_flag}` first, then retry the command."]
    if "requires executor_command" in text:
        return [
            "For Codex, Claude Code, Hermes, or OpenClaw, set `executor` and `executor_permission_mode`; Spice will resolve the command.",
            "For custom SDEP subprocesses, set `executor_command` or run `spice execute sdep <approval_id> --command \"python -m spice.runtime.sdep_echo_executor\"`.",
        ]
    if "unsupported executor" in text:
        return ["Set `executor` to `dry_run`, `codex`, `claude_code`, `hermes`, `openclaw`, or `sdep_subprocess` in .spice/config.json."]
    if "command poll is disabled" in text:
        return [
            "Pass `--allow-command-poll` for this command.",
            "Or run `spice config set perception_allow_command_poll true` to opt in for the workspace.",
        ]
    if "poll provider requires" in text:
        return [
            "Provide `--poll-url <url>` or `--poll-command <command>`.",
            "Or set `perception_poll_url` / `perception_poll_command` in .spice/config.json.",
        ]
    if "open chronicle mcp endpoint not reachable" in text:
        return [
            "Start Open Chronicle with `openchronicle start`.",
            "Or set `openchronicle_mcp_url` to the reachable MCP endpoint.",
        ]
    if "unsupported perception provider" in text:
        return ["Set `perception_provider` to `poll` or `open_chronicle`, or pass `--provider poll`."]
    if "unknown config key" in text:
        return ["Run `spice config show` to inspect supported workspace config keys."]
    if "llm_model is required" in text:
        return [
            f"Run `spice config enable-llm --provider openai --model gpt-4o-mini{workspace_flag}`.",
            "Or choose another provider/model pair supported by your API key.",
        ]
    if "invalid executor" in text:
        return [
            "Use `spice config set executor dry_run`, `spice config set executor codex`, `spice config set executor claude_code`, `spice config set executor hermes`, `spice config set executor openclaw`, or `spice config set executor sdep_subprocess`."
        ]
    if "session does not exist" in text:
        return [f"Run `spice session list{workspace_flag}` to find available sessions."]
    if "must be approved" in text or "not pending" in text:
        return [
            f"Check status with `spice approval show <approval_id>{workspace_flag}`.",
            f"Approve a pending item with `spice approval approve <approval_id>{workspace_flag}`.",
        ]
    if "no run artifact found" in text:
        return [
            "This approval is not linked to a saved run artifact.",
            f"Create a new executable handoff with `spice decide \"...\" --act{workspace_flag}`.",
        ]
    if "cannot be combined" in text:
        return ["Remove one of the conflicting flags and retry."]
    if "--json requires --once" in text:
        return [f"Use `spice run --once \"...\" --json{workspace_flag}`."]
    if "approval id required" in text:
        return [f"Run `spice approval list{workspace_flag}` to find an approval id."]
    if "keyword must be non-empty" in text:
        return [f"Use `spice session search <keyword>{workspace_flag}`."]
    if "no prior run found for refinement" in text:
        return [f"Run `spice decide \"...\"{workspace_flag}` first, then `spice refine \"...\"`."]
    if "parent run does not contain candidates" in text:
        return ["Refine a saved Spice run artifact that contains candidate decisions."]
    return []


def _workspace_flag(workspace: Path | None) -> str:
    if workspace is None:
        return ""
    rendered = str(workspace)
    if not rendered or rendered == ".":
        return ""
    return f" --workspace {rendered}"


def _handle_setup(args: argparse.Namespace) -> int:
    try:
        if not bool(args.defaults) and sys.stdin.isatty():
            run_setup_wizard(
                project_root=args.workspace,
                force=bool(args.force),
                input_stream=sys.stdin,
                output_stream=sys.stdout,
            )
            return 0
        report = setup_workspace(
            project_root=args.workspace,
            force=bool(args.force),
        )
        print("Spice workspace initialized.")
        print(f"workspace={report.workspace}")
        print(f"created={len(report.created)}")
        print(f"existing={len(report.existing)}")
        print(f"overwritten={len(report.overwritten)}")
        print()
        print("Next steps:")
        print(f"  edit {report.workspace / 'decision.md'}")
        print("  spice doctor")
        print("  spice config show")
        print("  spice shell")
        print("  spice decide \"Review this repo and suggest the safest next action\"")
        print("  spice decide \"Fix the failing test\" --act")
        print("  spice decide \"What should I do next?\" --advise")
        print("  spice run")
        print("  spice approval list")
        print("  spice execute <approval_id>")
        print("  spice session list")
        print("  spice session resume session.default --start")
        print("  spice run --once \"...\" --decision-only --no-bars")
        return 0
    except Exception as exc:
        _print_cli_error("setup", exc, workspace=args.workspace)
        return 1


def _handle_doctor(args: argparse.Namespace) -> int:
    try:
        report = run_doctor(args.workspace)
        if bool(args.json):
            print(json.dumps(report.to_payload(), indent=2, sort_keys=True))
        else:
            print(render_doctor_report(report))
        return 0 if report.status in {"ok", "warn"} else 1
    except Exception as exc:
        _print_cli_error("doctor", exc, workspace=args.workspace)
        return 1


def _handle_context(args: argparse.Namespace) -> int:
    try:
        payload = compile_workspace_decision_context_payload(
            project_root=args.workspace,
            session_id=args.session_id,
        )
        if bool(args.json):
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_decision_context_text(payload))
        return 0
    except Exception as exc:
        _print_cli_error("context", exc, workspace=args.workspace)
        return 1


def _handle_executor_list(args: argparse.Namespace) -> int:
    try:
        status = build_executor_status(args.workspace)
        if bool(args.json):
            print(json.dumps(status, indent=2, sort_keys=True))
        else:
            print(render_executor_list(status))
        return 0
    except Exception as exc:
        _print_cli_error("executor list", exc, workspace=args.workspace)
        return 1


def _handle_executor_doctor(args: argparse.Namespace) -> int:
    try:
        status = build_executor_status(args.workspace)
        if bool(args.json):
            print(json.dumps(status, indent=2, sort_keys=True))
        else:
            print(render_executor_doctor(status))
        runtime = status.get("configured_runtime")
        if isinstance(runtime, dict) and runtime.get("status") in {"ready"}:
            return 0
        return 1
    except Exception as exc:
        _print_cli_error("executor doctor", exc, workspace=args.workspace)
        return 1


def _handle_config_show(args: argparse.Namespace) -> int:
    try:
        require_workspace(args.workspace)
        config = load_workspace_config(args.workspace)
        payload = _workspace_config_payload_with_resolved_runtime(config)
        if bool(args.json):
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(_render_workspace_config(payload))
        return 0
    except Exception as exc:
        _print_cli_error("config show", exc, workspace=args.workspace)
        return 1


def _workspace_config_payload_with_resolved_runtime(config: object) -> dict[str, object]:
    payload = config.to_payload()
    payload["resolved_executor_runtime"] = resolve_executor_runtime_from_config(config).to_payload()
    return payload


def _handle_config_set(args: argparse.Namespace) -> int:
    try:
        config = update_workspace_config(args.workspace, args.key, args.value)
        payload = config.to_payload()
        if bool(args.json):
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Set {args.key} = {_lookup_config_payload_value(payload, args.key)}")
        return 0
    except Exception as exc:
        _print_cli_error("config set", exc, workspace=args.workspace)
        return 1


def _handle_config_enable_llm(args: argparse.Namespace) -> int:
    try:
        config = configure_workspace_llm(
            args.workspace,
            provider=args.provider,
            model=args.model,
            candidate_expand=not bool(args.no_candidate_expand),
            simulation=not bool(args.no_simulation),
        )
        payload = config.to_payload()
        if bool(args.json):
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("LLM features configured.")
            print(f"llm_provider={config.llm_provider}")
            print(f"llm_model={config.llm_model or '<default>'}")
            print(f"llm_candidate_expand={config.llm_candidate_expand}")
            print(f"llm_simulation={config.llm_simulation}")
            print(f"memory_summary_provider={config.memory_summary_provider}")
            env_name = _llm_api_key_env_name(config.llm_provider)
            if env_name:
                print()
                print(f"Next: export {env_name}=<key>")
                print(f"Then: spice doctor{_workspace_flag(args.workspace)}")
        return 0
    except Exception as exc:
        _print_cli_error("config enable-llm", exc, workspace=args.workspace)
        return 1


def _llm_api_key_env_name(provider: str) -> str:
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "mimo": "XIAOMI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(provider, "")


def _lookup_config_payload_value(payload: dict[str, object], key: str) -> object:
    current: object = payload
    for part in key.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part, "")
    return current


def _render_workspace_config(payload: dict[str, object]) -> str:
    keys = [
        "llm_provider",
        "llm_model",
        "llm_api_key_env",
        "llm_candidate_expand",
        "llm_simulation",
        "executor",
        "executor_permission_mode",
        "executor_command",
        "permission_mode",
        "perception_provider",
        "perception_poll_url",
        "perception_poll_command",
        "perception_poll_interval",
        "perception_poll_timeout",
        "perception_allow_command_poll",
        "openchronicle_mcp_url",
        "openchronicle_since_minutes",
        "openchronicle_context_limit",
        "perception_trigger_mode",
        "workspace_perception.depth",
        "workspace_perception.max_rounds",
        "workspace_perception.max_tool_calls",
        "workspace_perception.max_files_read",
        "workspace_perception.total_char_budget",
        "store",
        "active_session_id",
    ]
    width = max(len(key) for key in keys) + 2
    lines = ["Spice Workspace Config", ""]
    for key in keys:
        value = _lookup_config_payload_value(payload, key)
        rendered = "" if value is None else str(value)
        lines.append(f"{key.ljust(width, '.')} {rendered}")
    runtime = payload.get("resolved_executor_runtime")
    if isinstance(runtime, dict):
        runtime_keys = [
            "executor_id",
            "transport",
            "command",
            "command_source",
            "command_found",
            "real_executor",
            "sends_sdep_request",
            "status",
        ]
        runtime_width = max(len(key) for key in runtime_keys) + 2
        lines.extend(["", "Resolved Executor Runtime", ""])
        for key in runtime_keys:
            value = runtime.get(key)
            rendered = "" if value is None else str(value)
            lines.append(f"{key.ljust(runtime_width, '.')} {rendered}")
    lines.extend(
        [
            "",
            "Enable LLM material:",
            "  spice config enable-llm --provider openai --model gpt-4o-mini",
            "  spice config enable-llm --provider openrouter --model openai/gpt-4o-mini",
        ]
    )
    return "\n".join(lines)


def _handle_run(args: argparse.Namespace) -> int:
    if args.once is None:
        if bool(args.json):
            _print_cli_error(
                "run",
                "--json requires --once in the interactive shell preview.",
                workspace=args.workspace,
            )
            return 2
        if bool(args.act) and bool(args.decision_only):
            _print_cli_error(
                "run",
                "--act cannot be combined with --decision-only.",
                workspace=args.workspace,
            )
            return 2
        try:
            session_id = _resolve_session_id(args.workspace, getattr(args, "session_id", None))
            run_tui_shell(
                project_root=args.workspace,
                session_id=session_id,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
                plain=bool(getattr(args, "plain", False)) or not sys.stdin.isatty(),
                use_bars=not bool(args.no_bars),
                persist=not bool(args.no_persist),
                full_loop_preview=not bool(args.decision_only),
                run_intent_mode="act"
                if bool(args.act)
                else "advise"
                if bool(args.advise)
                else "auto",
            )
            return 0
        except Exception as exc:
            _print_cli_error("run", exc, workspace=args.workspace)
            return 1
    if bool(args.act) and bool(args.decision_only):
        _print_cli_error(
            "run",
            "--act cannot be combined with --decision-only.",
            workspace=args.workspace,
        )
        return 2
    try:
        _run_once_from_args(args, str(args.once))
        return 0
    except Exception as exc:
        _print_cli_error("run", exc, workspace=args.workspace)
        return 1


def _handle_shell(args: argparse.Namespace) -> int:
    try:
        session_id = _resolve_session_id(args.workspace, getattr(args, "session_id", None))
        run_tui_shell(
            project_root=args.workspace,
            session_id=session_id,
            plain=bool(args.plain) or not sys.stdin.isatty(),
            input_stream=sys.stdin,
            output_stream=sys.stdout,
            use_bars=not bool(args.no_bars),
            persist=not bool(args.no_persist),
            full_loop_preview=True,
            run_intent_mode="act"
            if bool(args.act)
            else "advise"
            if bool(args.advise)
            else "auto",
        )
        return 0
    except Exception as exc:
        _print_cli_error("shell", exc, workspace=args.workspace)
        return 1


def _handle_decide(args: argparse.Namespace) -> int:
    if bool(args.act) and bool(args.decision_only):
        _print_cli_error(
            "decide",
            "--act cannot be combined with --decision-only.",
            workspace=args.workspace,
        )
        return 2
    try:
        _run_once_from_args(args, str(args.intent))
        return 0
    except Exception as exc:
        _print_cli_error("decide", exc, workspace=args.workspace)
        return 1


def _handle_refine(args: argparse.Namespace) -> int:
    if bool(args.act) and bool(args.decision_only):
        _print_cli_error(
            "refine",
            "--act cannot be combined with --decision-only.",
            workspace=args.workspace,
        )
        return 2
    try:
        session_id = _resolve_session_id(args.workspace, getattr(args, "session_id", None))
        result = refine_decision(
            str(args.refinement),
            project_root=args.workspace,
            session_id=session_id,
            run_id=args.run_id,
            use_bars=not bool(args.no_bars),
            persist=not bool(args.no_persist),
            full_loop_preview=not bool(args.decision_only),
            run_intent_mode="act"
            if bool(args.act)
            else "advise"
            if bool(args.advise)
            else None,
        )
        if bool(args.json):
            print(json.dumps(result.artifact, indent=2, sort_keys=True))
        else:
            if bool(getattr(args, "rich", False)):
                print(
                    render_compare_rich(
                        result.artifact["compare_payload"],
                        use_bars=not bool(args.no_bars),
                    )
                )
            else:
                print(result.rendered_text)
            print()
            print("Artifacts:")
            print(f"  run={result.run_path}")
            print(f"  decision={result.decision_path}")
            if result.approval_path is not None:
                print(f"  approval={result.approval_path}")
            print(f"  session={result.session_path}")
            print(f"  state={result.state_path}")
        return 0
    except Exception as exc:
        _print_cli_error("refine", exc, workspace=args.workspace)
        return 1


def _run_once_from_args(args: argparse.Namespace, intent: str) -> None:
    session_id = _resolve_session_id(args.workspace, getattr(args, "session_id", None))
    result = run_once(
        intent,
        project_root=args.workspace,
        use_bars=not bool(args.no_bars),
        persist=not bool(args.no_persist),
        session_id=session_id,
        full_loop_preview=not bool(args.decision_only),
        run_intent_mode="act"
        if bool(args.act)
        else "advise"
        if bool(args.advise)
        else "auto",
    )
    if bool(args.json):
        print(json.dumps(result.artifact, indent=2, sort_keys=True))
    else:
        if bool(getattr(args, "rich", False)):
            print(
                render_compare_rich(
                    result.artifact["compare_payload"],
                    use_bars=not bool(args.no_bars),
                )
            )
        else:
            print(result.rendered_text)
        print()
        print("Artifacts:")
        print(f"  run={result.run_path}")
        print(f"  decision={result.decision_path}")
        if result.approval_path is not None:
            print(f"  approval={result.approval_path}")
        print(f"  session={result.session_path}")
        print(f"  state={result.state_path}")


def _handle_session_list(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        sessions = list_sessions(store, include_archived=bool(getattr(args, "all", False)))
        if bool(args.json):
            print(json.dumps([session.to_payload() for session in sessions], indent=2, sort_keys=True))
        else:
            print(render_session_list(sessions, include_archived=bool(getattr(args, "all", False))))
        return 0
    except Exception as exc:
        _print_cli_error("session list", exc, workspace=args.workspace)
        return 1


def _handle_session_current(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        session_id = load_workspace_config(args.workspace).active_session_id
        try:
            session = store.load_session(session_id)
            from spice.runtime import SessionRecord

            record = SessionRecord.from_payload(session)
        except FileNotFoundError:
            record = None
        if bool(args.json):
            print(
                json.dumps(
                    {
                        "active_session_id": session_id,
                        "session": record.to_payload() if record else None,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(render_session_current(session_id, record))
        return 0
    except Exception as exc:
        _print_cli_error("session current", exc, workspace=args.workspace)
        return 1


def _handle_session_switch(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        session = store.load_session(args.session_id)
        from spice.runtime import SessionRecord

        record = SessionRecord.from_payload(session)
        if record.status == "archived":
            _print_cli_error(
                "session switch",
                "cannot switch to an archived session.",
                workspace=args.workspace,
                suggestions=[
                    f"Run `spice session list --all{_workspace_flag(args.workspace)}` to inspect archived sessions.",
                    "Switch to an active session or create a new one with `spice run --session-id <id>`.",
                ],
            )
            return 2
        set_workspace_active_session(args.workspace, record.session_id)
        if bool(args.json):
            print(
                json.dumps(
                    {
                        "active_session_id": record.session_id,
                        "session": record.to_payload(),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"SPICE SESSION SWITCHED\nactive_session_id: {record.session_id}")
        return 0
    except Exception as exc:
        _print_cli_error("session switch", exc, workspace=args.workspace)
        return 1


def _handle_session_resume(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        session = store.load_session(args.session_id)
        from spice.runtime import SessionRecord

        record = SessionRecord.from_payload(session)
        if bool(getattr(args, "start", False)):
            if bool(args.json):
                _print_cli_error(
                    "session resume",
                    "--json cannot be combined with --start.",
                    workspace=args.workspace,
                )
                return 2
            run_interactive_shell(
                project_root=args.workspace,
                session_id=record.session_id,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
                use_bars=not bool(getattr(args, "no_bars", False)),
            )
            return 0
        if bool(args.json):
            print(json.dumps(record.to_payload(), indent=2, sort_keys=True))
        else:
            print(render_session_resume(record))
        return 0
    except Exception as exc:
        _print_cli_error("session resume", exc, workspace=args.workspace)
        return 1


def _handle_session_archive(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        record = archive_session(store, args.session_id)
        if load_workspace_config(args.workspace).active_session_id == record.session_id:
            set_workspace_active_session(args.workspace, "session.default")
        if bool(args.json):
            print(json.dumps(record.to_payload(), indent=2, sort_keys=True))
        else:
            print("SPICE SESSION ARCHIVED")
            print(f"session_id: {record.session_id}")
            print(f"status: {record.status}")
        return 0
    except Exception as exc:
        _print_cli_error("session archive", exc, workspace=args.workspace)
        return 1


def _handle_session_timeline(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        from spice.runtime import SessionRecord

        record = SessionRecord.from_payload(store.load_session(args.session_id))
        entries = build_session_timeline(store, record)
        if bool(args.json):
            print(json.dumps([entry.to_payload() for entry in entries], indent=2, sort_keys=True))
        else:
            print(render_session_timeline(entries))
        return 0
    except Exception as exc:
        _print_cli_error("session timeline", exc, workspace=args.workspace)
        return 1


def _handle_session_search(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        matches = search_sessions(
            store,
            args.keyword,
            include_archived=bool(getattr(args, "all", False)),
        )
        if bool(args.json):
            print(json.dumps([match.to_payload() for match in matches], indent=2, sort_keys=True))
        else:
            print(render_session_search(matches, args.keyword))
        return 0
    except Exception as exc:
        _print_cli_error("session search", exc, workspace=args.workspace)
        return 1


def _handle_session_stats(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        stats = session_stats(store)
        if bool(args.json):
            print(json.dumps(stats, indent=2, sort_keys=True))
        else:
            print(render_session_stats(stats))
        return 0
    except Exception as exc:
        _print_cli_error("session stats", exc, workspace=args.workspace)
        return 1


def _handle_session_delete(args: argparse.Namespace) -> int:
    try:
        if bool(args.cascade) and not bool(args.force):
            _print_cli_error(
                "session delete",
                "--cascade requires --force.",
                workspace=args.workspace,
                suggestions=["Add `--force` if you intentionally want to delete linked artifacts."],
            )
            return 2
        store = _local_store(args.workspace)
        result = delete_session(store, args.session_id, cascade=bool(args.cascade))
        current = load_workspace_config(args.workspace).active_session_id
        if current == args.session_id:
            set_workspace_active_session(args.workspace, "session.default")
        if bool(args.json):
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(render_session_delete_result(result))
        return 0
    except Exception as exc:
        _print_cli_error("session delete", exc, workspace=args.workspace)
        return 1


def _handle_approval_list(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        approvals = list_approvals(store, status=args.status)
        if bool(args.json):
            print(json.dumps([approval.to_payload() for approval in approvals], indent=2, sort_keys=True))
        else:
            print(render_approval_list(approvals))
        return 0
    except Exception as exc:
        _print_cli_error("approval list", exc, workspace=args.workspace)
        return 1


def _handle_approval_show(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        approval = load_approval(store, args.approval_id)
        if bool(args.json):
            print(json.dumps(approval.to_payload(), indent=2, sort_keys=True))
        else:
            print(render_approval_details(approval))
        return 0
    except Exception as exc:
        _print_cli_error("approval show", exc, workspace=args.workspace)
        return 1


def _handle_approval_approve(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        result = approve_approval(store, args.approval_id, reason=args.reason)
        if bool(args.json):
            print(json.dumps(result.to_payload(), indent=2, sort_keys=True))
        else:
            print(render_approval_resolution(result))
        return 0
    except Exception as exc:
        _print_cli_error("approval approve", exc, workspace=args.workspace)
        return 1


def _handle_approval_reject(args: argparse.Namespace) -> int:
    try:
        store = _local_store(args.workspace)
        result = reject_approval(store, args.approval_id, reason=args.reason)
        if bool(args.json):
            print(json.dumps(result.to_payload(), indent=2, sort_keys=True))
        else:
            print(render_approval_resolution(result))
        return 0
    except Exception as exc:
        _print_cli_error("approval reject", exc, workspace=args.workspace)
        return 1


def _handle_execute_dispatch(args: argparse.Namespace) -> int:
    execute_args = list(getattr(args, "execute_args", []) or [])
    if not execute_args:
        _execute_default_parser().print_help(sys.stderr)
        return 2

    execute_mode = "default"
    if execute_args[0] in {"dry-run", "codex", "claude-code", "hermes", "openclaw", "sdep"}:
        execute_mode = execute_args.pop(0)
    elif execute_args[0] == "default":
        print(
            "execute default is no longer needed; use `spice execute <approval_id>`.",
            file=sys.stderr,
        )
        return 2

    if execute_mode == "dry-run":
        parser = _execute_dry_run_parser()
        handler = _handle_execute_dry_run
    elif execute_mode == "codex":
        parser = _execute_codex_parser()
        handler = _handle_execute_codex
    elif execute_mode == "claude-code":
        parser = _execute_claude_code_parser()
        handler = _handle_execute_claude_code
    elif execute_mode == "hermes":
        parser = _execute_hermes_parser()
        handler = _handle_execute_hermes
    elif execute_mode == "openclaw":
        parser = _execute_openclaw_parser()
        handler = _handle_execute_openclaw
    elif execute_mode == "sdep":
        parser = _execute_sdep_parser()
        handler = _handle_execute_sdep
    else:
        parser = _execute_default_parser()
        handler = _handle_execute_default

    try:
        parsed_args = parser.parse_args(execute_args)
    except SystemExit as exc:
        return int(exc.code or 0)
    return handler(parsed_args)


def _handle_execute_dry_run(args: argparse.Namespace) -> int:
    try:
        result = execute_dry_run_approval(
            args.approval_id,
            project_root=args.workspace,
        )
        _print_execution_result(result, json_output=bool(args.json))
        return 0
    except Exception as exc:
        _print_cli_error("execute dry-run", exc, workspace=args.workspace)
        return 1


def _handle_execute_default(args: argparse.Namespace) -> int:
    try:
        config = load_workspace_config(args.workspace)
        executor = resolve_executor_runtime_from_config(config)
        if executor.status == "unsupported":
            raise ValueError(executor.detail)
        if executor.status != "ready":
            raise ValueError(executor.detail)
        if executor.executor_id == "dry_run":
            result = execute_dry_run_approval(args.approval_id, project_root=args.workspace)
        elif executor.executor_id == "codex":
            result = execute_codex_approval(
                args.approval_id,
                command=executor.command,
                project_root=args.workspace,
                timeout_seconds=int(args.timeout),
            )
        elif executor.executor_id == "claude_code":
            result = execute_claude_code_approval(
                args.approval_id,
                command=executor.command,
                project_root=args.workspace,
                timeout_seconds=int(args.timeout),
            )
        elif executor.executor_id == "hermes":
            result = execute_hermes_approval(
                args.approval_id,
                command=executor.command,
                project_root=args.workspace,
                timeout_seconds=int(args.timeout),
            )
        elif executor.executor_id == "openclaw":
            result = execute_openclaw_approval(
                args.approval_id,
                command=executor.command,
                project_root=args.workspace,
                timeout_seconds=int(args.timeout),
            )
        elif executor.executor_id == "sdep_subprocess":
            result = execute_sdep_subprocess_approval(
                args.approval_id,
                command=executor.command,
                project_root=args.workspace,
                timeout_seconds=int(args.timeout),
            )
        else:
            raise ValueError(
                f"Unsupported executor in .spice/config.json: {executor.executor_id!r}. "
                "Supported values: dry_run, codex, claude_code, hermes, openclaw, sdep_subprocess."
            )
        _print_execution_result(result, json_output=bool(args.json))
        return 0
    except Exception as exc:
        _print_cli_error("execute", exc, workspace=args.workspace)
        return 1


def _handle_execute_sdep(args: argparse.Namespace) -> int:
    try:
        result = execute_sdep_subprocess_approval(
            args.approval_id,
            command=args.command,
            project_root=args.workspace,
            timeout_seconds=int(args.timeout),
        )
        _print_execution_result(result, json_output=bool(args.json))
        return 0
    except Exception as exc:
        _print_cli_error("execute sdep", exc, workspace=args.workspace)
        return 1


def _handle_execute_codex(args: argparse.Namespace) -> int:
    try:
        result = execute_codex_approval(
            args.approval_id,
            command=args.command,
            project_root=args.workspace,
            timeout_seconds=int(args.timeout),
        )
        _print_execution_result(result, json_output=bool(args.json))
        return 0
    except Exception as exc:
        _print_cli_error("execute codex", exc, workspace=args.workspace)
        return 1


def _handle_execute_claude_code(args: argparse.Namespace) -> int:
    try:
        result = execute_claude_code_approval(
            args.approval_id,
            command=args.command,
            project_root=args.workspace,
            timeout_seconds=int(args.timeout),
        )
        _print_execution_result(result, json_output=bool(args.json))
        return 0
    except Exception as exc:
        _print_cli_error("execute claude-code", exc, workspace=args.workspace)
        return 1


def _handle_execute_hermes(args: argparse.Namespace) -> int:
    try:
        result = execute_hermes_approval(
            args.approval_id,
            command=args.command,
            project_root=args.workspace,
            timeout_seconds=int(args.timeout),
        )
        _print_execution_result(result, json_output=bool(args.json))
        return 0
    except Exception as exc:
        _print_cli_error("execute hermes", exc, workspace=args.workspace)
        return 1


def _handle_execute_openclaw(args: argparse.Namespace) -> int:
    try:
        result = execute_openclaw_approval(
            args.approval_id,
            command=args.command,
            project_root=args.workspace,
            timeout_seconds=int(args.timeout),
        )
        _print_execution_result(result, json_output=bool(args.json))
        return 0
    except Exception as exc:
        _print_cli_error("execute openclaw", exc, workspace=args.workspace)
        return 1


def _handle_perceive(args: argparse.Namespace) -> int:
    try:
        if bool(args.watch):
            results = perceive_watch(
                project_root=args.workspace,
                provider=args.provider,
                poll_url=args.poll_url,
                poll_command=args.poll_command,
                openchronicle_mcp_url=args.openchronicle_mcp_url,
                openchronicle_since_minutes=args.openchronicle_since_minutes,
                openchronicle_context_limit=args.openchronicle_context_limit,
                allow_command_poll=bool(args.allow_command_poll) or None,
                decide_on_change=bool(args.decide_on_change) or None,
                timeout_seconds=args.timeout,
                interval_seconds=args.poll_interval,
                max_iterations=args.max_iterations,
            )
            payload = {
                "path_type": "runtime_perception_watch",
                "generated_by": "spice.entry.cli",
                "iteration_count": len(results),
                "artifacts": [result.artifact for result in results],
            }
            if bool(args.json):
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for result in results:
                    print(result.rendered_text)
                    print()
            return 0
        result = perceive_once(
            project_root=args.workspace,
            provider=args.provider,
            poll_url=args.poll_url,
            poll_command=args.poll_command,
            openchronicle_mcp_url=args.openchronicle_mcp_url,
            openchronicle_since_minutes=args.openchronicle_since_minutes,
            openchronicle_context_limit=args.openchronicle_context_limit,
            allow_command_poll=bool(args.allow_command_poll) or None,
            decide_on_change=bool(args.decide_on_change) or None,
            timeout_seconds=args.timeout,
        )
        if bool(args.json):
            print(json.dumps(result.artifact, indent=2, sort_keys=True))
        else:
            print(result.rendered_text)
            print()
            print("Artifacts:")
            print(f"  perception={result.perception_path}")
            print(f"  state={result.state_path}")
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _print_cli_error("perceive", exc, workspace=args.workspace)
        return 1


def _print_execution_result(result: object, *, json_output: bool) -> None:
    artifact = getattr(result, "artifact")
    if json_output:
        print(json.dumps(artifact, indent=2, sort_keys=True))
        return
    print(getattr(result, "rendered_text"))
    print()
    print("Artifacts:")
    print(f"  run={getattr(result, 'run_path')}")
    print(f"  outcome={getattr(result, 'outcome_path')}")
    session_path = getattr(result, "session_path")
    if session_path is not None:
        print(f"  session={session_path}")
    print(f"  state={getattr(result, 'state_path')}")


def _resolve_session_id(workspace: Path, explicit_session_id: str | None) -> str:
    if explicit_session_id:
        return explicit_session_id
    paths = workspace_paths(workspace)
    if not paths.config.exists():
        raise FileNotFoundError(
            f"Spice workspace is not initialized. Missing: {paths.config}. Run `spice setup` first."
        )
    return load_workspace_config(workspace).active_session_id


def _local_store(workspace: Path) -> LocalJsonStore:
    paths = workspace_paths(workspace)
    missing = [path for path in (paths.config, paths.state) if not path.exists()]
    if missing:
        rendered = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            f"Spice workspace is not initialized. Missing: {rendered}. Run `spice setup` first."
        )
    return LocalJsonStore(paths)


def _handle_quickstart(args: argparse.Namespace) -> int:
    output_dir: Path = args.output
    llm_output_dir: Path = args.llm_output
    decision_profile: Path = args.decision_profile
    support_output: Path = args.support_output
    force = bool(args.force)
    no_run = bool(args.no_run)
    core_only = bool(args.core_only)
    try:
        if core_only:
            report = run_quickstart(
                output_dir=output_dir,
                force=force,
                no_run=no_run,
            )
            _print_core_quickstart_report(report)
            return 0

        report = run_integrated_quickstart(
            output_dir=output_dir,
            llm_output_dir=llm_output_dir,
            decision_profile_path=decision_profile,
            support_output_path=support_output,
            force=force,
            no_run=no_run,
        )
        _print_integrated_quickstart_report(report)
        return 0
    except Exception as exc:
        _print_cli_error("quickstart", exc)
        return 1


def _print_core_quickstart_report(report: QuickstartReport) -> None:
    print("[1/6] Load built-in DomainSpec ... OK")
    print("[2/6] Validate DomainSpec ... OK (schema_version=spice.domain_spec.v1)")
    print("[3/6] Render deterministic scaffold ... OK")
    print(
        "[4/6] Write scaffold ... OK "
        f"({len(report.scaffold_files)} files -> {report.output_dir})"
    )
    if report.demo_ran:
        print(
            "[5/6] Run generated demo ... OK "
            f"(command={' '.join(report.demo_command)})"
        )
        _print_last_cycle(report.last_cycle)
    else:
        print("[5/6] Run generated demo ... SKIPPED (--no-run)")
    print(
        "[6/6] Write artifacts ... OK "
        f"({report.stdout_log_path.parent / 'quickstart_summary.json'})"
    )
    print()
    print("Core quickstart complete.")
    print(f"Inspect generated scaffold: {report.output_dir}")
    print(f"Reference DomainSpec: {report.domain_spec_path}")
    print("Next step: run `spice quickstart` for decision.md + model wiring.")


def _print_integrated_quickstart_report(report: IntegratedQuickstartReport) -> None:
    core = report.core_report
    profile = report.decision_profile_report
    llm = report.llm_report
    explain = report.decision_explain_report
    validation = explain.get("validation", {})
    validation_status = str(validation.get("status", "unknown"))

    print("[1/10] Load built-in example DomainSpec ... OK")
    print("[2/10] Generate core example scaffold ... OK " f"({core.output_dir})")
    if core.demo_ran:
        print("[3/10] Run core example demo ... OK")
        _print_last_cycle(core.last_cycle)
    else:
        print("[3/10] Run core example demo ... SKIPPED (--no-run)")
    print("[4/10] Initialize decision.md ... OK " f"({profile.profile_path})")
    if profile.support_path is not None:
        print(
            "[5/10] Copy support reference ... OK "
            f"({profile.support_path}; explain/debug only)"
        )
    else:
        print("[5/10] Copy support reference ... SKIPPED")
    print("[6/10] Validate decision.md ... OK " f"(status={validation_status})")
    print("[7/10] Generate LLM-ready example runtime ... OK " f"({llm.output_dir})")
    if llm.demo_ran:
        print("[8/10] Run LLM-ready example demo ... OK")
        _print_last_cycle(llm.last_cycle)
    else:
        print("[8/10] Run LLM-ready example demo ... SKIPPED (--no-run)")
    print(
        "[9/10] Write artifacts ... OK "
        f"({core.stdout_log_path.parent / 'integrated_quickstart_summary.json'})"
    )
    print("[10/10] Print next commands ... OK")
    print()
    print("Quickstart complete.")
    print("Generated example domain runtime:")
    print(f"  core_example={core.output_dir}")
    print(f"  llm_ready_example={llm.output_dir}")
    print(f"  decision_profile={profile.profile_path}")
    if profile.support_path is not None:
        print(f"  support_reference={profile.support_path}")
    print()
    print("Use OpenRouter with the example runtime:")
    print('  export OPENROUTER_API_KEY="your-openrouter-api-key"')
    print('  export SPICE_DOMAIN_MODEL="openrouter:anthropic/claude-3.5-sonnet"')
    print(f"  python {llm.output_dir / 'run_demo.py'}")
    print()
    print("Use a local/custom subprocess model:")
    print(f'  SPICE_DOMAIN_MODEL="ollama run qwen2.5" python {llm.output_dir / "run_demo.py"}')
    print()
    print("Validate and explain decision.md:")
    if profile.support_path is not None:
        print(
            f"  spice decision explain {profile.profile_path} "
            f"--support-json {profile.support_path}"
        )
    else:
        print(f"  spice decision explain {profile.profile_path}")
    print()
    print("Real projects define their own DomainSpec/domain adapter.")
    print("This quickstart uses the bundled example domain to show the full Spice boundary.")


def _print_last_cycle(last_cycle: dict[str, object] | None) -> None:
    if last_cycle is None:
        return
    action_id = str(last_cycle.get("decision_action", ""))
    planned_operation = str(last_cycle.get("planned_operation", ""))
    executed_operation = str(last_cycle.get("execution_operation", ""))
    print(f"domain_action_id={action_id}")
    print(f"planned_execution_operation={planned_operation}")
    print(f"executed_operation={executed_operation}")


def _handle_decision_explain(args: argparse.Namespace) -> int:
    try:
        support_source = str(args.support_json) if args.support_json is not None else ""
        support = (
            _load_decision_guidance_support(args.support_json)
            if args.support_json is not None
            else None
        )
        report = explain_decision_guidance(args.path, support=support)
        if support_source:
            report["support_contract"]["source"] = support_source
            report["support_contract"]["role"] = (
                "explain/debug input; runtime authority should come from the active policy/domain adapter"
            )
        if bool(args.json):
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_decision_guidance_explanation(report))
            if support_source:
                print()
                print(
                    "Support note: --support-json is for explain/debug. "
                    "Runtime capability should come from the active policy/domain adapter."
                )
        return 0
    except Exception as exc:
        _print_cli_error("decision explain", exc)
        return 1


def _handle_decision_compare(args: argparse.Namespace) -> int:
    try:
        payload = load_compare_payload(args.input)
        if bool(args.json):
            print(render_compare_json(payload))
        else:
            print(
                render_compare_text(
                    payload,
                    show_execution=bool(args.show_execution),
                    use_bars=not bool(args.no_bars),
                )
            )
        return 0
    except Exception as exc:
        _print_cli_error("decision compare", exc)
        return 1


def _handle_decision_init(args: argparse.Namespace) -> int:
    try:
        report = init_decision_profile(
            output=args.output,
            force=bool(args.force),
            include_support=not bool(args.no_support),
        )
        print("Decision profile initialized.")
        print(f"profile_path={report.profile_path}")
        if report.support_path is not None:
            print(f"support_reference_path={report.support_path}")
            print(
                "support_reference_role=explain/debug only; runtime support comes from the active policy/domain adapter"
            )
        print()
        print("Next steps:")
        if report.support_path is not None:
            print(
                "  python -m spice.entry decision explain "
                f"{report.profile_path} --support-json {report.support_path}"
            )
        else:
            print(f"  python -m spice.entry decision explain {report.profile_path}")
        print("  Use guided_policy_from_profile(base_policy, profile_path) in Python runtime code.")
        return 0
    except Exception as exc:
        _print_cli_error("decision init", exc)
        return 1


def _load_decision_guidance_support(path: Path) -> DecisionGuidanceSupport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("support JSON must be an object.")
    return DecisionGuidanceSupport.from_dict(payload)


def _handle_init_domain(args: argparse.Namespace) -> int:
    output_dir: Path = args.output if args.output is not None else Path(args.name)
    force = bool(args.force)
    no_run = bool(args.no_run)
    from_spec = args.from_spec
    assist = bool(args.assist)
    assist_brief_file = args.assist_brief_file
    assist_stdin = bool(args.assist_stdin)
    assist_model = args.assist_model
    assist_max_tries = max(1, int(args.assist_max_tries))
    with_llm = bool(args.with_llm)

    if assist and from_spec is not None:
        _print_cli_error(
            "init domain",
            "--assist cannot be combined with --from-spec.",
            suggestions=["Use either `--assist` or `--from-spec`, not both."],
        )
        return 1
    if assist_brief_file is not None and assist_stdin:
        _print_cli_error(
            "init domain",
            "use either --assist-brief-file or --assist-stdin, not both.",
            suggestions=["Choose one brief input source and retry."],
        )
        return 1

    try:
        if assist:
            print("[1/7] Capture domain brief ...")
            brief = capture_brief(
                brief_file=assist_brief_file,
                use_stdin=assist_stdin,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
            )
            if not brief.strip():
                raise RuntimeError("Assist brief is empty.")

            model, model_backend = resolve_assist_model(model=assist_model)
            print(f"[2/7] Draft DomainSpec via assist model ... ({model_backend})")
            session = run_assist_session(
                domain_name=str(args.name),
                brief=brief,
                draft_service=model,
                model_backend=model_backend,
                max_tries=assist_max_tries,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
            )
            print("[3/7] Validate accepted DomainSpec ... OK (schema_version=spice.domain_spec.v1)")
            print("[4/7] Render deterministic scaffold ... OK")
            report = run_init_domain_from_spec(
                spec=session.accepted_spec,
                output_dir=output_dir,
                force=force,
                no_run=no_run,
                with_llm=with_llm,
                interactive=False,
                from_spec_path=None,
            )
            assist_summary_path = write_assist_artifacts(
                artifacts_root=report.stdout_log_path.parent,
                session=session,
            )
            print(
                "[5/7] Write scaffold ... OK "
                f"({len(report.scaffold_files)} files -> {report.output_dir})"
            )
            if report.demo_ran:
                print(
                    "[6/7] Run generated demo ... OK "
                    f"(command={' '.join(report.demo_command)})"
                )
                if report.last_cycle is not None:
                    action_id = str(report.last_cycle.get("decision_action", ""))
                    planned_operation = str(report.last_cycle.get("planned_operation", ""))
                    executed_operation = str(report.last_cycle.get("execution_operation", ""))
                    print(f"domain_action_id={action_id}")
                    print(f"planned_execution_operation={planned_operation}")
                    print(f"executed_operation={executed_operation}")
            else:
                print("[6/7] Run generated demo ... SKIPPED (--no-run)")
            print(
                "[7/7] Write artifacts ... OK "
                f"({assist_summary_path}, {report.stdout_log_path.parent / 'init_summary.json'})"
            )
            print()
            print("Domain init (--assist) complete.")
            print(f"Inspect generated scaffold: {report.output_dir}")
            print(f"Reference DomainSpec: {report.domain_spec_path}")
            return 0

        mode = "from-spec" if from_spec is not None else "interactive"
        print(f"[1/6] Build DomainSpec ({mode}) ...")
        report = run_init_domain(
            name=str(args.name),
            output_dir=output_dir,
            force=force,
            no_run=no_run,
            with_llm=with_llm,
            from_spec=from_spec,
            input_stream=sys.stdin,
            output_stream=sys.stdout,
        )
        print("[2/6] Validate DomainSpec ... OK (schema_version=spice.domain_spec.v1)")
        print("[3/6] Render deterministic scaffold ... OK")
        print(
            "[4/6] Write scaffold ... OK "
            f"({len(report.scaffold_files)} files -> {report.output_dir})"
        )
        if report.demo_ran:
            print(
                "[5/6] Run generated demo ... OK "
                f"(command={' '.join(report.demo_command)})"
            )
            if report.last_cycle is not None:
                action_id = str(report.last_cycle.get("decision_action", ""))
                planned_operation = str(report.last_cycle.get("planned_operation", ""))
                executed_operation = str(report.last_cycle.get("execution_operation", ""))
                print(f"domain_action_id={action_id}")
                print(f"planned_execution_operation={planned_operation}")
                print(f"executed_operation={executed_operation}")
        else:
            print("[5/6] Run generated demo ... SKIPPED (--no-run)")
        print(
            "[6/6] Write artifacts ... OK "
            f"({report.stdout_log_path.parent / 'init_summary.json'})"
        )
        print()
        print("Domain init complete.")
        print(f"Inspect generated scaffold: {report.output_dir}")
        print(f"Reference DomainSpec: {report.domain_spec_path}")
        print("Tip: run spice quickstart first if you want a prebuilt reference scaffold.")
        return 0
    except Exception as exc:
        _print_cli_error("init domain", exc)
        return 1
