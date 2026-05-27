from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spice.decision.general.types import payload_value
from spice.runtime.workspace import SpiceWorkspaceConfig


@dataclass(frozen=True, slots=True)
class ExecutorRuntimeSpec:
    executor_id: str
    transport: str
    default_command: str = ""
    permission_commands: dict[str, str] = field(default_factory=dict)
    permission_enforcement: str = "not_applicable"
    command_required: bool = False
    approval_required: bool = True
    real_executor: bool = False
    sends_sdep_request: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return payload_value(self)


@dataclass(frozen=True, slots=True)
class ResolvedExecutorRuntime:
    requested_executor_id: str
    executor_id: str
    transport: str
    command: str
    command_argv: tuple[str, ...] = ()
    command_source: str = "none"
    permission_mode: str = "workspace_write"
    permission_enforcement: str = "not_applicable"
    command_required: bool = False
    command_found: bool = False
    command_path: str = ""
    approval_required: bool = True
    real_executor: bool = False
    sends_sdep_request: bool = False
    status: str = "ready"
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return payload_value(self)


_EXECUTOR_RUNTIME_SPECS: dict[str, ExecutorRuntimeSpec] = {
    "dry_run": ExecutorRuntimeSpec(
        executor_id="dry_run",
        transport="local_dry_run",
        command_required=False,
        real_executor=False,
        sends_sdep_request=False,
        metadata={
            "description": "Local dry-run executor that previews the approved handoff.",
        },
    ),
    "sdep_subprocess": ExecutorRuntimeSpec(
        executor_id="sdep_subprocess",
        transport="sdep_subprocess",
        command_required=True,
        real_executor=False,
        sends_sdep_request=True,
        metadata={
            "description": "Generic SDEP subprocess transport.",
        },
    ),
    "codex": ExecutorRuntimeSpec(
        executor_id="codex",
        transport="sdep_subprocess_wrapper",
        default_command="codex exec --skip-git-repo-check --sandbox workspace-write -",
        permission_enforcement="command_flag",
        permission_commands={
            "read_only": "codex exec --skip-git-repo-check --sandbox read-only -",
            "workspace_write": "codex exec --skip-git-repo-check --sandbox workspace-write -",
            "danger_full_access": (
                "codex exec --skip-git-repo-check "
                "--dangerously-bypass-approvals-and-sandbox -"
            ),
        },
        command_required=True,
        real_executor=True,
        sends_sdep_request=True,
        metadata={
            "description": "Codex-compatible executor wrapper.",
        },
    ),
    "claude_code": ExecutorRuntimeSpec(
        executor_id="claude_code",
        transport="sdep_subprocess_wrapper",
        default_command="claude -p --permission-mode acceptEdits",
        permission_enforcement="command_flag",
        permission_commands={
            "read_only": "claude -p --permission-mode plan",
            "workspace_write": "claude -p --permission-mode acceptEdits",
            "danger_full_access": "claude -p --permission-mode bypassPermissions",
        },
        command_required=True,
        real_executor=True,
        sends_sdep_request=True,
        metadata={
            "description": "Claude Code-compatible executor wrapper.",
        },
    ),
    "hermes": ExecutorRuntimeSpec(
        executor_id="hermes",
        transport="sdep_subprocess_wrapper",
        default_command="hermes chat -Q",
        permission_enforcement="command_flag",
        permission_commands={
            "read_only": "hermes chat -Q",
            "workspace_write": "hermes chat -Q",
            "danger_full_access": "hermes chat --yolo -Q",
        },
        command_required=True,
        real_executor=True,
        sends_sdep_request=True,
        metadata={
            "description": "Hermes-compatible executor wrapper.",
            "permission_note": (
                "Hermes exposes --yolo for bypassing dangerous-command approval; "
                "read_only and workspace_write both use Hermes' normal approval model."
            ),
        },
    ),
    "openclaw": ExecutorRuntimeSpec(
        executor_id="openclaw",
        transport="sdep_subprocess_wrapper",
        default_command="openclaw agent --json --message",
        permission_enforcement="executor_policy",
        permission_commands={
            "read_only": "openclaw agent --json --message",
            "workspace_write": "openclaw agent --json --message",
            "danger_full_access": "openclaw agent --json --message",
        },
        command_required=True,
        real_executor=True,
        sends_sdep_request=True,
        metadata={
            "description": "OpenClaw-compatible executor wrapper.",
            "permission_note": (
                "OpenClaw permissions are governed by OpenClaw exec-policy, approvals, "
                "and sandbox config. Inspect with `openclaw exec-policy show --json` "
                "and `openclaw sandbox explain --json`."
            ),
            "recommended_policy": {
                "read_only": "deny-all or an equivalent read-only allowlist",
                "workspace_write": "cautious",
                "danger_full_access": "yolo; Spice does not switch this automatically",
            },
        },
    ),
}


def executor_runtime_specs() -> dict[str, ExecutorRuntimeSpec]:
    return dict(_EXECUTOR_RUNTIME_SPECS)


def resolve_executor_runtime(
    executor_id: str | None = None,
    *,
    executor_command: str | None = None,
    executor_permission_mode: str | None = None,
) -> ResolvedExecutorRuntime:
    requested = str(executor_id or "dry_run").strip() or "dry_run"
    permission_mode = _normalize_permission_mode(executor_permission_mode)
    spec = _EXECUTOR_RUNTIME_SPECS.get(requested)
    if spec is None:
        return ResolvedExecutorRuntime(
            requested_executor_id=requested,
            executor_id=requested,
            transport="unsupported",
            command=str(executor_command or "").strip(),
            command_source="config" if str(executor_command or "").strip() else "none",
            permission_mode=permission_mode,
            status="unsupported",
            detail=(
                "Unsupported executor. Supported values: "
                + ", ".join(sorted(_EXECUTOR_RUNTIME_SPECS))
                + "."
            ),
            metadata={"supported_executors": sorted(_EXECUTOR_RUNTIME_SPECS)},
        )

    raw_configured_command = str(executor_command or "").strip()
    configured_command = (
        ""
        if _is_legacy_generated_command(spec.executor_id, raw_configured_command)
        else raw_configured_command
    )
    generated_command = spec.permission_commands.get(permission_mode) or spec.default_command
    command = configured_command or generated_command
    command_source = (
        "config"
        if configured_command
        else "legacy_default:migrated"
        if raw_configured_command and raw_configured_command != configured_command
        else f"permission:{permission_mode}"
        if generated_command and spec.permission_commands
        else "default"
        if command
        else "none"
    )
    command_argv, parse_error = _parse_command(command)
    command_path = _resolve_command_path(command_argv[0]) if command_argv else ""
    command_found = bool(command_path) if command_argv else not spec.command_required

    if spec.command_required and not command:
        status = "failed"
        detail = f"missing executor_command: executor={spec.executor_id} requires executor_command."
    elif parse_error:
        status = "failed"
        detail = f"cannot parse executor command: {parse_error}"
    elif spec.command_required and not command_found:
        status = "failed"
        detail = f"command not found: {command_argv[0] if command_argv else command}"
    elif spec.executor_id == "dry_run":
        status = "ready"
        detail = "not needed for dry_run"
    else:
        status = "ready"
        detail = command

    return ResolvedExecutorRuntime(
        requested_executor_id=requested,
        executor_id=spec.executor_id,
        transport=spec.transport,
        command=command,
        command_argv=tuple(command_argv),
        command_source=command_source,
        permission_mode=permission_mode,
        permission_enforcement=spec.permission_enforcement,
        command_required=spec.command_required,
        command_found=command_found,
        command_path=command_path,
        approval_required=spec.approval_required,
        real_executor=spec.real_executor,
        sends_sdep_request=spec.sends_sdep_request,
        status=status,
        detail=detail,
        metadata={
            **dict(spec.metadata),
            "permission_mode": permission_mode,
            "permission_enforcement": spec.permission_enforcement,
            "permission_commands": dict(spec.permission_commands),
        },
    )


def resolve_executor_runtime_from_config(config: SpiceWorkspaceConfig) -> ResolvedExecutorRuntime:
    return resolve_executor_runtime(
        config.executor,
        executor_command=config.executor_command,
        executor_permission_mode=config.executor_permission_mode,
    )


def resolve_executor_runtime_from_config_with_permission(
    config: SpiceWorkspaceConfig,
    executor_permission_mode: str,
) -> ResolvedExecutorRuntime:
    return resolve_executor_runtime(
        config.executor,
        executor_command=config.executor_command,
        executor_permission_mode=executor_permission_mode,
    )


def _normalize_permission_mode(value: str | None) -> str:
    normalized = str(value or "workspace_write").strip() or "workspace_write"
    if normalized in {"readonly", "read-only", "read_only"}:
        return "read_only"
    if normalized in {"workspace-write", "workspace", "workspace_write"}:
        return "workspace_write"
    if normalized in {"danger", "danger-full-access", "danger_full_access", "full_access"}:
        return "danger_full_access"
    return normalized


def _is_legacy_generated_command(executor_id: str, command: str) -> bool:
    legacy_commands = {
        "codex": {
            "codex exec --skip-git-repo-check -",
            "codex exec --skip-git-repo-check --sandbox read-only -",
            "codex exec --skip-git-repo-check --sandbox workspace-write -",
            (
                "codex exec --skip-git-repo-check "
                "--dangerously-bypass-approvals-and-sandbox -"
            ),
        },
        "claude_code": {
            "claude -p",
            "claude -p --permission-mode plan",
            "claude -p --permission-mode acceptEdits",
            "claude -p --permission-mode bypassPermissions",
        },
        "hermes": {
            "hermes -z",
            "hermes --yolo -z",
            "hermes -z --yolo",
            "hermes chat -Q",
            "hermes chat --yolo -Q",
        },
        "openclaw": {
            "openclaw agent --json --message",
        },
    }
    return command in legacy_commands.get(executor_id, set())


def _parse_command(command: str) -> tuple[list[str], str]:
    if not command:
        return [], ""
    try:
        return shlex.split(command), ""
    except ValueError as exc:
        return [], str(exc)


def _resolve_command_path(executable: str) -> str:
    if not executable:
        return ""
    path = Path(executable)
    if path.is_absolute() or "/" in executable:
        return str(path) if path.exists() else ""
    found = shutil.which(executable)
    return found or ""
