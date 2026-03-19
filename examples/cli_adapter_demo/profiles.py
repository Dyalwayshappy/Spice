from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from spice.executors import CLIActionMapping, CLIAdapterProfile, CLIInvocation


THIS_DIR = Path(__file__).resolve().parent


def build_portable_profile() -> CLIAdapterProfile:
    agent_path = THIS_DIR / "portable_cli_agent.py"

    return CLIAdapterProfile(
        profile_id="portable-cli",
        display_name="Portable Local CLI Agent",
        default_timeout_seconds=20.0,
        action_mappings={
            "repo.request.review": CLIActionMapping(
                action_type="repo.request.review",
                parser_mode="json",
                default_outcome_type="observation",
                render_invocation=lambda ctx: CLIInvocation(
                    argv=[sys.executable, str(agent_path)],
                    stdin_text=json.dumps(_context_payload(ctx), ensure_ascii=True),
                ),
            ),
            "workspace.run.command": CLIActionMapping(
                action_type="workspace.run.command",
                parser_mode="json",
                default_outcome_type="state_delta",
                render_invocation=lambda ctx: CLIInvocation(
                    argv=[sys.executable, str(agent_path)],
                    stdin_text=json.dumps(_context_payload(ctx), ensure_ascii=True),
                ),
            ),
        },
        metadata={"demo": "portable", "requires_install": False},
    )


def build_optional_codex_profile() -> CLIAdapterProfile | None:
    if shutil.which("codex") is None:
        return None

    review_cmd = _command_from_env("SPICE_CODEX_REVIEW_CMD", default="codex exec")
    run_cmd = _command_from_env("SPICE_CODEX_RUN_CMD", default="codex exec")
    timeout = float(os.environ.get("SPICE_CODEX_TIMEOUT_SECONDS", "60"))

    return CLIAdapterProfile(
        profile_id="codex-cli",
        display_name="Codex CLI (Optional)",
        default_timeout_seconds=timeout,
        action_mappings={
            "repo.request.review": CLIActionMapping(
                action_type="repo.request.review",
                parser_mode="text",
                default_outcome_type="observation",
                render_invocation=lambda ctx: CLIInvocation(
                    argv=list(review_cmd),
                    stdin_text=_codex_prompt(ctx),
                ),
            ),
            "workspace.run.command": CLIActionMapping(
                action_type="workspace.run.command",
                parser_mode="text",
                default_outcome_type="state_delta",
                render_invocation=lambda ctx: CLIInvocation(
                    argv=list(run_cmd),
                    stdin_text=_codex_prompt(ctx),
                ),
            ),
        },
        metadata={
            "demo": "optional",
            "requires_install": True,
            "note": "Best-effort profile. Override command strings via SPICE_CODEX_* env vars.",
        },
    )


def _context_payload(ctx: Any) -> dict[str, Any]:
    return {
        "intent_id": getattr(getattr(ctx, "intent", None), "id", ""),
        "action_type": str(getattr(ctx, "action_type", "")),
        "target": dict(getattr(ctx, "target", {})),
        "input": dict(getattr(ctx, "input_payload", {})),
        "parameters": dict(getattr(ctx, "parameters", {})),
        "constraints": list(getattr(ctx, "constraints", [])),
        "mode": str(getattr(ctx, "mode", "sync")),
        "dry_run": bool(getattr(ctx, "dry_run", False)),
    }


def _codex_prompt(ctx: Any) -> str:
    payload = _context_payload(ctx)
    return (
        "You are an execution agent.\n"
        "Interpret the following semantic action and return a concise execution output.\n\n"
        f"{json.dumps(payload, ensure_ascii=True, indent=2)}\n"
    )


def _command_from_env(env_var: str, *, default: str) -> list[str]:
    raw = os.environ.get(env_var, default).strip()
    if not raw:
        return shlex.split(default)
    command = shlex.split(raw)
    return command or shlex.split(default)
