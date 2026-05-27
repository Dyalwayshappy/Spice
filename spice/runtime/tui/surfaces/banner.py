from __future__ import annotations

import shutil
from typing import Any

from spice.runtime.tui.theme import SpiceTheme


SPICE_LOGO = r"""
 ███████╗██████╗ ██╗ ██████╗███████╗
 ██╔════╝██╔══██╗██║██╔════╝██╔════╝
 ███████╗██████╔╝██║██║     █████╗
 ╚════██║██╔═══╝ ██║██║     ██╔══╝
 ███████║██║     ██║╚██████╗███████╗
 ╚══════╝╚═╝     ╚═╝ ╚═════╝╚══════╝
""".strip("\n")

SPICE_LOGO_WIDTH = max(len(line) for line in SPICE_LOGO.splitlines())
SPICE_LOGO_MIN_TERMINAL_WIDTH = SPICE_LOGO_WIDTH + 10


def render_banner(
    config: dict[str, Any],
    session_payload: dict[str, Any],
    *,
    version: str = "0.1.0",
    dashboard: dict[str, Any] | None = None,
    width: int | None = None,
) -> Any:
    dashboard = dashboard or {}
    terminal_width = _terminal_width(width)
    try:
        from rich import box
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        return _plain_banner(config, session_payload, version=version, dashboard=dashboard)

    header = _banner_header(Text, terminal_width)

    meta = Table.grid(padding=(0, 2))
    meta.add_column(style=SpiceTheme.DIM)
    meta.add_column()
    meta.add_column(style=SpiceTheme.DIM)
    meta.add_column()
    meta.add_row("session:", str(session_payload.get("session_id") or "session.default"), "mode:", str(dashboard.get("mode") or _runtime_mode(config)))
    meta.add_row("executor:", str(config.get("executor") or "dry_run"), "approval:", f"{int(dashboard.get('pending_approvals') or 0)} pending")
    meta.add_row("llm:", _llm_label(config), "recent decisions:", str(dashboard.get("decision_count") or 0))
    meta.add_row("perception:", str(config.get("perception_provider") or "manual"), "state:", _state_label(dashboard))

    executors = _status_table(
        Table,
        "executor",
        _list_items(dashboard, "executors"),
    )
    skills = _status_table(
        Table,
        "skill",
        _list_items(dashboard, "skills"),
    )
    perception = _status_table(
        Table,
        "perception",
        _list_items(dashboard, "perception"),
    )

    next_steps = Text()
    pending_approvals = int(dashboard.get("pending_approvals") or 0)
    if pending_approvals:
        next_steps.append(f"Pending approvals: {pending_approvals}\n", style=SpiceTheme.WARNING)
        next_steps.append("Run ", style=SpiceTheme.DIM)
        next_steps.append("/pending", style=SpiceTheme.SUCCESS)
        next_steps.append(" to continue.\n", style=SpiceTheme.DIM)
    next_steps.append("Try: ", style=SpiceTheme.DIM)
    next_steps.append("I have a failing test, a pending PR review, and a meeting in 45 minutes", style=SpiceTheme.SUCCESS)
    next_steps.append("\n     /doctor  /approvals  /perceive --decide-on-change", style=SpiceTheme.DIM)

    return Panel(
        Group(
            header,
            meta,
            Panel(
                Group(executors, skills, perception),
                title="[bold red]RUNTIME READINESS[/bold red]",
                border_style=SpiceTheme.PANEL_BORDER,
                box=box.ROUNDED,
            ),
            next_steps,
        ),
        title=f"[bold red]Spice Decision Runtime v{version}[/bold red]",
        border_style=SpiceTheme.PANEL_BORDER,
        box=box.ROUNDED,
        padding=(1, 2),
    )


def _plain_banner(
    config: dict[str, Any],
    session_payload: dict[str, Any],
    *,
    version: str,
    dashboard: dict[str, Any],
) -> str:
    lines = [
        f"Spice Decision Runtime v{version}",
        f"session: {session_payload.get('session_id') or 'session.default'}",
        f"executor: {config.get('executor') or 'dry_run'}",
        f"llm: {_llm_label(config)}",
        f"perception: {config.get('perception_provider') or 'manual'}",
        f"mode: {dashboard.get('mode') or _runtime_mode(config)}",
        f"pending approvals: {int(dashboard.get('pending_approvals') or 0)}",
        f"recent decisions: {int(dashboard.get('decision_count') or 0)}",
        f"state: {_state_label(dashboard)}",
        "",
        "Available Executors",
    ]
    lines.extend(f"- {item['name']}: {item['status']}" for item in _list_items(dashboard, "executors"))
    lines.append("")
    lines.append("Available Skills")
    lines.extend(f"- {item['name']}: {item['status']}" for item in _list_items(dashboard, "skills"))
    lines.append("")
    lines.append("Perception")
    lines.extend(f"- {item['name']}: {item['status']}" for item in _list_items(dashboard, "perception"))
    lines.extend(
        [
            "",
            *(
                [
                    f"Pending approvals: {int(dashboard.get('pending_approvals') or 0)}",
                    "Run /pending to continue.",
                    "",
                ]
                if int(dashboard.get("pending_approvals") or 0)
                else []
            ),
            "Try: I have a failing test, a pending PR review, and a meeting in 45 minutes",
            "Type an intent or /help for commands",
        ]
    )
    return "\n".join(lines)


def _banner_header(Text: Any, terminal_width: int) -> Any:
    header = Text()
    if terminal_width >= SPICE_LOGO_MIN_TERMINAL_WIDTH:
        header.append(SPICE_LOGO, style=SpiceTheme.BRAND)
        return header
    header.append("SPICE", style=SpiceTheme.BRAND)
    header.append(" Decision Runtime", style=SpiceTheme.SUCCESS)
    header.append("  compact banner", style=SpiceTheme.DIM)
    return header


def _terminal_width(width: int | None) -> int:
    if isinstance(width, int) and width > 0:
        return width
    return shutil.get_terminal_size((100, 24)).columns


def _status_table(Table: Any, label: str, items: list[dict[str, str]]) -> Any:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(label, style=SpiceTheme.DIM)
    table.add_column("status")
    if not items:
        table.add_row(f"Available {label.title()}s", "none")
        return table
    table.add_row(f"Available {label.title()}s", "")
    for item in items:
        status = item.get("status") or "unknown"
        style = _status_style(status)
        table.add_row(f"- {item.get('name') or 'unknown'}", f"[{style}]{status}[/{style}]")
    return table


def _status_style(status: str) -> str:
    if status in {"ready", "configured"}:
        return SpiceTheme.SUCCESS
    if status.startswith("needs") or status in {"manual", "not_configured"}:
        return SpiceTheme.WARNING
    return SpiceTheme.DIM


def _runtime_mode(config: dict[str, Any]) -> str:
    executor = str(config.get("executor") or "dry_run")
    llm = str(config.get("llm_provider") or "deterministic")
    if executor == "dry_run" and llm == "deterministic":
        return "decision + dry-run"
    if executor == "dry_run":
        return "LLM decision + dry-run"
    executor_name = _executor_name(executor)
    if llm == "deterministic":
        return f"decision + {executor_name} handoff"
    return f"LLM decision + {executor_name} handoff"


def _executor_name(executor_id: str) -> str:
    normalized = executor_id.strip().lower()
    return {
        "sdep_subprocess": "SDEP executor",
        "codex": "Codex",
        "claude_code": "Claude Code",
        "hermes": "Hermes",
        "openclaw": "OpenClaw",
    }.get(normalized, normalized or "executor")


def _llm_label(config: dict[str, Any]) -> str:
    provider = str(config.get("llm_provider") or "deterministic")
    model = str(config.get("llm_model") or "").strip()
    return f"{provider}/{model}" if model else provider


def _state_label(dashboard: dict[str, Any]) -> str:
    counts = dashboard.get("state_counts")
    if not isinstance(counts, dict):
        return "0 work items, 0 outcomes"
    return (
        f"{int(counts.get('work_items') or 0)} work items, "
        f"{int(counts.get('outcomes') or 0)} outcomes"
    )


def _list_items(dashboard: dict[str, Any], key: str) -> list[dict[str, str]]:
    value = dashboard.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
