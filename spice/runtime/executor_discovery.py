from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from spice.decision.general.types import payload_value


_EXECUTOR_COMMANDS: dict[str, str] = {
    "codex": "codex",
    "claude_code": "claude",
    "hermes": "hermes",
    "openclaw": "openclaw",
}


@dataclass(frozen=True, slots=True)
class ExecutorCLIDetection:
    executor_id: str
    command_name: str
    status: str
    command: str = ""
    executable_path: str = ""
    detail: str = ""
    broken_symlink_path: str = ""
    broken_symlink_target: str = ""
    detected_apps: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def to_payload(self) -> dict[str, object]:
        return payload_value(self)


def detect_executor_cli(
    executor_id: str,
    *,
    search_paths: list[Path] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> ExecutorCLIDetection:
    """Detect a local executor CLI without invoking it."""

    normalized = str(executor_id or "").strip()
    command_name = _EXECUTOR_COMMANDS.get(normalized, "")
    if not command_name:
        return ExecutorCLIDetection(
            executor_id=normalized,
            command_name="",
            status="unsupported",
            detail=(
                "Executor CLI discovery only supports codex, claude_code, "
                "hermes, and openclaw."
            ),
        )

    found = which(command_name)
    if found:
        return ExecutorCLIDetection(
            executor_id=normalized,
            command_name=command_name,
            status="ready",
            command=command_name,
            executable_path=str(found),
            detail=f"{command_name} found on PATH: {found}",
        )

    paths = search_paths if search_paths is not None else _default_search_paths(command_name)
    broken: tuple[Path, str] | None = None
    for path in paths:
        if path.is_symlink() and not path.exists():
            broken = (path, os.readlink(path))
            continue
        if path.exists() and path.is_file() and os.access(path, os.X_OK):
            return ExecutorCLIDetection(
                executor_id=normalized,
                command_name=command_name,
                status="ready",
                command=str(path),
                executable_path=str(path),
                detail=f"{command_name} found outside PATH: {path}",
                metadata={"command_source": "absolute_path"},
            )

    apps = _detect_app_installations(normalized)
    if broken is not None:
        path, target = broken
        return ExecutorCLIDetection(
            executor_id=normalized,
            command_name=command_name,
            status="broken_symlink",
            broken_symlink_path=str(path),
            broken_symlink_target=target,
            detected_apps=apps,
            detail=f"broken CLI symlink: {path} -> {target}",
        )

    if apps:
        return ExecutorCLIDetection(
            executor_id=normalized,
            command_name=command_name,
            status="app_only",
            detected_apps=apps,
            detail=(
                f"{normalized} app/extension detected, but no executable CLI command "
                "was found for Spice subprocess execution."
            ),
        )

    return ExecutorCLIDetection(
        executor_id=normalized,
        command_name=command_name,
        status="missing",
        detected_apps=apps,
        detail=f"{command_name} CLI not found.",
    )


def detect_known_executor_clis() -> dict[str, ExecutorCLIDetection]:
    return {
        executor_id: detect_executor_cli(executor_id)
        for executor_id in ("codex", "claude_code", "hermes", "openclaw")
    }


def _default_search_paths(command_name: str) -> list[Path]:
    home = Path.home()
    return [
        home / ".local" / "bin" / command_name,
        home / ".npm-global" / "bin" / command_name,
        Path("/opt/homebrew/bin") / command_name,
        Path("/usr/local/bin") / command_name,
    ]


def _detect_app_installations(executor_id: str) -> tuple[str, ...]:
    home = Path.home()
    candidates: list[Path] = []
    if executor_id == "codex":
        candidates.extend(
            [
                Path("/Applications/ChatGPT.app"),
                home / "Applications" / "ChatGPT.app",
            ]
        )
        vscode_extensions = home / ".vscode" / "extensions"
        if vscode_extensions.exists():
            candidates.extend(vscode_extensions.glob("openai.chatgpt-*"))
    elif executor_id == "claude_code":
        candidates.extend(
            [
                Path("/Applications/Claude.app"),
                home / "Applications" / "Claude.app",
            ]
        )
    elif executor_id == "hermes":
        candidates.extend(
            [
                home / ".hermes",
                home / ".config" / "hermes",
            ]
        )
    elif executor_id == "openclaw":
        candidates.extend(
            [
                home / ".openclaw",
                home / ".config" / "openclaw",
            ]
        )
    return tuple(str(path) for path in candidates if path.exists())
