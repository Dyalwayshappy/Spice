from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from spice.runtime.executor_discovery import detect_executor_cli
from spice.runtime.store import LocalJsonStore
from spice.runtime.executor_runtime import resolve_executor_runtime_from_config
from spice.runtime.workspace import (
    SpiceWorkspaceConfig,
    load_workspace_env,
    safe_workspace_record_id,
    workspace_paths,
)


@dataclass(slots=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    next_step: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "metadata": dict(self.metadata),
        }
        if self.next_step:
            payload["next_step"] = self.next_step
        return payload


@dataclass(slots=True)
class DoctorReport:
    workspace: str
    status: str
    checks: list[DoctorCheck]

    def to_payload(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "status": self.status,
            "checks": [check.to_payload() for check in self.checks],
        }


def run_doctor(project_root: str | Path = ".") -> DoctorReport:
    paths = workspace_paths(project_root)
    load_workspace_env(project_root)
    checks: list[DoctorCheck] = []
    checks.append(_python_check())
    checks.append(_path_check(".spice/", paths.spice_dir, is_dir=True))
    config_payload = _config_check(paths.config, checks)
    checks.append(_path_check("decision.md", paths.decision_profile))
    state_payload = _json_file_check("state.json", paths.state)
    checks.append(state_payload[0])
    checks.append(_rich_check())
    checks.extend(_directory_checks(paths))
    config = (
        SpiceWorkspaceConfig.from_payload(config_payload)
        if isinstance(config_payload, dict)
        else None
    )
    checks.append(_llm_provider_check(config))
    checks.append(_llm_model_check(config))
    checks.append(_llm_candidate_expansion_check(config))
    checks.append(_llm_simulation_check(config))
    checks.append(_llm_api_key_check(config))
    checks.append(_llm_readiness_check(config))
    checks.append(_memory_provider_check(config))
    checks.append(_memory_path_check(paths, config))
    checks.append(_context_compiler_check(config))
    checks.append(_memory_summary_check(config))
    checks.append(_perception_provider_check(config))
    checks.append(_perception_poll_source_check(config))
    checks.append(_open_chronicle_check(config))
    checks.append(_perception_trigger_mode_check(config))
    checks.append(_executor_check(config))
    checks.append(_executor_runtime_check(config))
    checks.append(_executor_command_check(config))
    checks.append(_executor_cli_check(config))
    checks.append(_active_session_check(paths, config))
    checks.append(_pending_approvals_check(paths))
    return DoctorReport(
        workspace=str(paths.spice_dir),
        status=_overall_status(checks),
        checks=checks,
    )


def render_doctor_report(report: DoctorReport) -> str:
    lines = [
        "Spice Doctor - workspace check",
        f"workspace: {report.workspace}",
        "",
    ]
    width = max((len(check.name) for check in report.checks), default=16) + 2
    for check in report.checks:
        label = f"{check.name}".ljust(width, ".")
        lines.append(f"{label} {check.status} - {check.detail}")
        if check.next_step:
            lines.append(f"{'':{width}} Next: {check.next_step}")
    lines.append("")
    if report.status == "ok":
        lines.append("All required checks passed.")
    elif report.status == "warn":
        lines.append("Required checks passed with warnings.")
    else:
        lines.append("Some required checks failed.")
    return "\n".join(lines)


def _python_check() -> DoctorCheck:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):
        return DoctorCheck("Python", "ok", f"{version} >= 3.11")
    return DoctorCheck(
        "Python",
        "fail",
        f"{version} < 3.11",
        next_step="Use Python 3.11 or newer.",
    )


def _path_check(name: str, path: Path, *, is_dir: bool = False) -> DoctorCheck:
    if not path.exists():
        return DoctorCheck(
            name,
            "fail",
            f"missing: {path}",
            next_step="Run `spice setup` first.",
        )
    if is_dir and not path.is_dir():
        return DoctorCheck(name, "fail", f"not a directory: {path}")
    if not is_dir and not path.is_file():
        return DoctorCheck(name, "fail", f"not a file: {path}")
    return DoctorCheck(name, "ok", str(path))


def _config_check(path: Path, checks: list[DoctorCheck]) -> dict[str, Any] | None:
    if not path.exists():
        checks.append(
            DoctorCheck(
                "config.json",
                "fail",
                f"missing: {path}",
                next_step="Run `spice setup` first.",
            )
        )
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        checks.append(
            DoctorCheck(
                "config.json",
                "fail",
                f"invalid JSON: {exc}",
                next_step="Fix .spice/config.json or rerun `spice setup --force`.",
            )
        )
        return None
    if not isinstance(payload, dict):
        checks.append(DoctorCheck("config.json", "fail", "payload is not an object"))
        return None
    try:
        SpiceWorkspaceConfig.from_payload(payload)
    except Exception as exc:
        checks.append(DoctorCheck("config.json", "fail", str(exc)))
        return None
    checks.append(DoctorCheck("config.json", "ok", str(path)))
    return payload


def _json_file_check(name: str, path: Path) -> tuple[DoctorCheck, dict[str, Any] | None]:
    if not path.exists():
        return (
            DoctorCheck(
                name,
                "fail",
                f"missing: {path}",
                next_step="Run `spice setup` first.",
            ),
            None,
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return (
            DoctorCheck(
                name,
                "fail",
                f"invalid JSON: {exc}",
                next_step=f"Fix {path}.",
            ),
            None,
        )
    if not isinstance(payload, dict):
        return (DoctorCheck(name, "fail", "payload is not an object"), None)
    return (DoctorCheck(name, "ok", str(path)), payload)


def _rich_check() -> DoctorCheck:
    if find_spec("rich") is None:
        return DoctorCheck(
            "rich",
            "warn",
            "not installed (optional)",
            next_step="Install rich for Rich-lite Decision Cards.",
        )
    return DoctorCheck("rich", "ok", "installed (optional)")


def _llm_provider_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("llm provider", "fail", "config unavailable")
    if config.llm_provider in {
        "anthropic",
        "deepseek",
        "deterministic",
        "mimo",
        "openai",
        "openrouter",
        "subprocess",
    }:
        return DoctorCheck("llm provider", "ok", config.llm_provider)
    return DoctorCheck(
        "llm provider",
        "fail",
        config.llm_provider,
        next_step=(
            "Set llm_provider to anthropic, deepseek, deterministic, mimo, "
            "openai, openrouter, or subprocess."
        ),
    )


def _llm_api_key_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("llm api key", "fail", "config unavailable")
    if config.llm_provider == "deterministic":
        return DoctorCheck("llm api key", "ok", "not needed for deterministic")
    if config.llm_provider == "subprocess":
        return DoctorCheck("llm api key", "ok", "not needed for subprocess")
    env_names = _llm_api_key_envs_for_provider(config.llm_provider, config.llm_api_key_env)
    if env_names:
        set_env = _first_set_env(env_names)
        if set_env:
            return DoctorCheck("llm api key", "ok", f"{set_env} set")
        env_label = " or ".join(env_names)
        return DoctorCheck(
            "llm api key",
            "warn",
            f"{env_label} is not set",
            next_step=f"Export {env_names[0]} or switch llm_provider to deterministic.",
        )
    return DoctorCheck("llm api key", "warn", "not checked for unsupported llm_provider")


def _llm_model_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("llm model", "fail", "config unavailable")
    if config.llm_provider == "deterministic":
        return DoctorCheck("llm model", "ok", config.llm_model or "deterministic.v1")
    if config.llm_provider == "subprocess":
        return DoctorCheck("llm model", "ok", config.llm_model or "provided by subprocess")
    if config.llm_model.strip():
        return DoctorCheck("llm model", "ok", config.llm_model.strip())
    return DoctorCheck(
        "llm model",
        "warn",
        "missing for configured LLM provider",
        next_step=(
            f"Run `spice config enable-llm --provider {config.llm_provider} "
            "--model <model>`."
        ),
    )


def _llm_candidate_expansion_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("llm candidate expansion", "fail", "config unavailable")
    if _config_bool(config.llm_candidate_expand):
        return DoctorCheck("llm candidate expansion", "ok", "enabled")
    return DoctorCheck(
        "llm candidate expansion",
        "ok",
        "disabled",
        next_step="Enable with `spice config enable-llm --provider <provider> --model <model>`.",
    )


def _llm_simulation_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("llm simulation", "fail", "config unavailable")
    if _config_bool(config.llm_simulation):
        return DoctorCheck("llm simulation", "ok", "enabled")
    return DoctorCheck(
        "llm simulation",
        "ok",
        "disabled",
        next_step="Enable with `spice config enable-llm --provider <provider> --model <model>`.",
    )


def _llm_readiness_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("llm readiness", "fail", "config unavailable")
    if not _llm_features_enabled(config):
        return DoctorCheck(
            "llm readiness",
            "warn",
            "rule-only mode",
            next_step="Run `spice config enable-llm --provider openai --model gpt-4o-mini`.",
        )
    if config.llm_provider == "deterministic":
        return DoctorCheck(
            "llm readiness",
            "warn",
            "deterministic provider; no external LLM calls",
            next_step="Set a real provider and model with `spice config enable-llm`.",
        )
    if config.llm_provider == "subprocess":
        return DoctorCheck("llm readiness", "ok", "subprocess provider configured")
    if not config.llm_model.strip():
        return DoctorCheck(
            "llm readiness",
            "warn",
            "LLM features enabled but llm_model is missing",
            next_step=(
                f"Run `spice config enable-llm --provider {config.llm_provider} "
                "--model <model>`."
            ),
        )
    env_names = _llm_api_key_envs_for_provider(config.llm_provider, config.llm_api_key_env)
    if env_names and not _first_set_env(env_names):
        env_label = " or ".join(env_names)
        return DoctorCheck(
            "llm readiness",
            "warn",
            f"LLM features enabled but {env_label} is not set",
            next_step=f"Export {env_names[0]} and rerun `spice doctor`.",
        )
    return DoctorCheck("llm readiness", "ok", "ready for LLM candidate expansion/simulation")


def _directory_checks(paths: Any) -> list[DoctorCheck]:
    checks = []
    for name, path in (
        ("sessions dir", paths.sessions_dir),
        ("approvals dir", paths.approvals_dir),
        ("decisions dir", paths.decisions_dir),
        ("runs dir", paths.runs_dir),
        ("outcomes dir", paths.outcomes_dir),
        ("perceptions dir", paths.perceptions_dir),
        ("memory dir", paths.memory_dir),
    ):
        if path.exists() and path.is_dir():
            pattern = "*.jsonl" if name == "memory dir" else "*.json"
            count = len([item for item in path.glob(pattern) if item.is_file()])
            unit = "namespaces" if name == "memory dir" else "records"
            checks.append(DoctorCheck(name, "ok", f"{path} ({count} {unit})"))
        else:
            checks.append(
                DoctorCheck(
                    name,
                    "fail",
                    f"missing: {path}",
                    next_step="Run `spice setup` first.",
                )
            )
    return checks


def _memory_provider_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("memory provider", "fail", "config unavailable")
    if config.memory_provider == "file":
        return DoctorCheck(
            "memory provider",
            "ok",
            "file",
            metadata={"storage": "jsonl"},
        )
    return DoctorCheck(
        "memory provider",
        "fail",
        config.memory_provider,
        next_step="Set memory_provider to file.",
    )


def _memory_path_check(paths: Any, config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("memory path", "fail", "config unavailable")
    configured = Path(config.memory_path)
    memory_path = configured if configured.is_absolute() else paths.project_root / configured
    if memory_path.exists() and memory_path.is_dir():
        namespaces = len([item for item in memory_path.glob("*.jsonl") if item.is_file()])
        return DoctorCheck(
            "memory path",
            "ok",
            f"{memory_path} ({namespaces} namespaces)",
            metadata={"path": str(memory_path), "namespaces": namespaces},
        )
    return DoctorCheck(
        "memory path",
        "warn",
        f"missing: {memory_path}",
        next_step="Run `spice setup` or create the configured memory_path directory.",
        metadata={"path": str(memory_path)},
    )


def _context_compiler_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("context compiler", "fail", "config unavailable")
    if config.context_compiler == "deterministic":
        return DoctorCheck(
            "context compiler",
            "ok",
            "deterministic",
            metadata={"implementation": "spice.memory.DeterministicContextCompiler"},
        )
    return DoctorCheck(
        "context compiler",
        "fail",
        config.context_compiler,
        next_step="Set context_compiler to deterministic.",
    )


def _memory_summary_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("memory summary", "fail", "config unavailable")
    provider = str(config.memory_summary_provider or "deterministic")
    if provider == "deterministic":
        return DoctorCheck(
            "memory summary",
            "ok",
            "deterministic rolling summary",
            metadata={"provider": provider},
        )
    if provider == "llm":
        if not _llm_features_enabled(config) or config.llm_provider == "deterministic":
            return DoctorCheck(
                "memory summary",
                "warn",
                "llm requested but no LLM runtime is enabled; deterministic summary remains available",
                next_step="Enable an LLM provider and llm_candidate_expand, or set memory_summary_provider=deterministic.",
                metadata={"provider": provider},
            )
        return DoctorCheck(
            "memory summary",
            "ok",
            (
                "llm rolling summary "
                f"(trigger={config.memory_summary_llm_min_new_records} records or "
                f"{config.memory_summary_trigger_chars} chars, "
                f"target={config.memory_summary_target_chars} chars)"
            ),
            metadata={
                "provider": provider,
                "min_new_records": config.memory_summary_llm_min_new_records,
                "trigger_chars": config.memory_summary_trigger_chars,
                "target_chars": config.memory_summary_target_chars,
            },
        )
    return DoctorCheck(
        "memory summary",
        "fail",
        provider,
        next_step="Set memory_summary_provider to deterministic or llm.",
    )


def _perception_provider_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("perception provider", "fail", "config unavailable")
    if config.perception_provider in {"manual", "open_chronicle", "poll"}:
        return DoctorCheck("perception provider", "ok", config.perception_provider)
    return DoctorCheck(
        "perception provider",
        "fail",
        config.perception_provider,
        next_step="Set perception_provider to manual, poll, or open_chronicle.",
    )


def _perception_poll_source_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("perception poll source", "fail", "config unavailable")
    if config.perception_provider != "poll":
        return DoctorCheck("perception poll source", "ok", f"not needed for {config.perception_provider}")
    has_url = bool(config.perception_poll_url.strip())
    has_command = bool(config.perception_poll_command.strip())
    if not has_url and not has_command:
        return DoctorCheck(
            "perception poll source",
            "warn",
            "poll provider has no URL or command",
            next_step="Set perception_poll_url or perception_poll_command.",
        )
    checks = []
    if has_url:
        checks.append(f"url={config.perception_poll_url.strip()}")
    if has_command:
        if not _config_bool(config.perception_allow_command_poll):
            return DoctorCheck(
                "perception poll source",
                "warn",
                "command configured but command poll is disabled",
                next_step="Set perception_allow_command_poll=true to opt in to shell-free command polling.",
            )
        command_check = _command_exists_check(
            "perception poll source",
            config.perception_poll_command.strip(),
            next_step="Set perception_poll_command to an executable command.",
        )
        if command_check.status != "ok":
            return command_check
        checks.append(f"command={config.perception_poll_command.strip()}")
    return DoctorCheck(
        "perception poll source",
        "ok",
        ", ".join(checks),
        metadata={
            "timeout_seconds": config.perception_poll_timeout,
            "interval_seconds": config.perception_poll_interval,
        },
    )


def _open_chronicle_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("open chronicle", "fail", "config unavailable")
    if config.perception_provider != "open_chronicle":
        return DoctorCheck("open chronicle", "ok", f"not needed for {config.perception_provider}")
    endpoint = config.openchronicle_mcp_url.strip()
    if not endpoint:
        return DoctorCheck(
            "open chronicle",
            "warn",
            "MCP endpoint is not configured",
            next_step="Set openchronicle_mcp_url, usually http://127.0.0.1:8742/mcp.",
        )
    payload = {
        "jsonrpc": "2.0",
        "id": "spice.doctor.open_chronicle",
        "method": "tools/list",
        "params": {},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            response.read(1024)
    except (OSError, urllib.error.URLError):
        return DoctorCheck(
            "open chronicle",
            "warn",
            f"MCP not reachable: {endpoint}",
            next_step="Start Open Chronicle with `openchronicle start`.",
            metadata={"endpoint": endpoint},
        )
    return DoctorCheck(
        "open chronicle",
        "ok",
        f"MCP reachable: {endpoint}",
        metadata={
            "endpoint": endpoint,
            "since_minutes": config.openchronicle_since_minutes,
            "context_limit": config.openchronicle_context_limit,
        },
    )


def _perception_trigger_mode_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("perception trigger mode", "fail", "config unavailable")
    if config.perception_trigger_mode == "state_only":
        return DoctorCheck(
            "perception trigger mode",
            "ok",
            "state_only",
            next_step="Use `spice perceive --decide-on-change` to generate Decision Cards from changed signals.",
        )
    if config.perception_trigger_mode == "decision_on_change":
        return DoctorCheck(
            "perception trigger mode",
            "ok",
            "decision_on_change",
            next_step="Changed perception signals create Decision Cards, but never execute automatically.",
        )
    return DoctorCheck(
        "perception trigger mode",
        "fail",
        config.perception_trigger_mode,
        next_step="Set perception_trigger_mode to state_only or decision_on_change.",
    )


def _executor_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("executor", "fail", "config unavailable")
    runtime = resolve_executor_runtime_from_config(config)
    if runtime.status == "unsupported":
        return DoctorCheck(
            "executor",
            "fail",
            runtime.executor_id,
            next_step=(
                "Set executor to dry_run, codex, claude_code, hermes, "
                "openclaw, or sdep_subprocess."
            ),
            metadata=runtime.to_payload(),
        )
    return DoctorCheck(
        "executor",
        "ok",
        runtime.executor_id,
        metadata=runtime.to_payload(),
    )


def _executor_runtime_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("executor runtime", "fail", "config unavailable")
    runtime = resolve_executor_runtime_from_config(config)
    if runtime.status == "unsupported":
        return DoctorCheck(
            "executor runtime",
            "fail",
            runtime.detail,
            next_step=(
                "Set executor to dry_run, codex, claude_code, hermes, "
                "openclaw, or sdep_subprocess."
            ),
            metadata=runtime.to_payload(),
        )
    detail = (
        f"transport={runtime.transport}, "
        f"command_source={runtime.command_source}, "
        f"permission={runtime.permission_mode}, "
        f"permission_enforcement={runtime.permission_enforcement}, "
        f"real_executor={str(runtime.real_executor).lower()}, "
        f"sends_sdep={str(runtime.sends_sdep_request).lower()}"
    )
    if runtime.status != "ready":
        return DoctorCheck(
            "executor runtime",
            "fail",
            detail,
            next_step=_executor_command_next_step(runtime.executor_id),
            metadata=runtime.to_payload(),
        )
    return DoctorCheck(
        "executor runtime",
        "ok",
        detail,
        metadata=runtime.to_payload(),
    )


def _executor_command_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("executor_command", "fail", "config unavailable")
    runtime = resolve_executor_runtime_from_config(config)
    if runtime.status == "unsupported":
        return DoctorCheck("executor_command", "warn", "not checked for unsupported executor")
    if runtime.executor_id == "dry_run":
        return DoctorCheck(
            "executor_command",
            "ok",
            runtime.detail,
            metadata=runtime.to_payload(),
        )
    next_step = _executor_command_next_step(runtime.executor_id)
    status = "ok" if runtime.status == "ready" else "fail"
    return DoctorCheck(
        "executor_command",
        status,
        runtime.detail,
        next_step=None if status == "ok" else next_step,
        metadata=runtime.to_payload(),
    )


def _executor_command_next_step(executor_id: str) -> str:
    return {
        "codex": (
            "Install Codex CLI or set executor_permission_mode to read_only, "
            "workspace_write, or danger_full_access."
        ),
        "claude_code": (
            "Install Claude Code CLI. Use executor_command only for advanced custom wrappers."
        ),
        "hermes": "Install Hermes CLI. Use executor_command only for advanced custom wrappers.",
        "openclaw": (
            "Install OpenClaw CLI. OpenClaw permissions are controlled by "
            "`openclaw exec-policy` and sandbox settings; Spice does not switch them automatically."
        ),
        "sdep_subprocess": "Set executor_command to an executable SDEP-compatible command.",
    }.get(executor_id, "Set executor to a supported executor or configure executor_command.")


def _executor_cli_check(config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("executor cli", "fail", "config unavailable")
    if config.executor == "dry_run":
        return DoctorCheck("executor cli", "ok", "not needed for dry_run")
    if config.executor == "sdep_subprocess":
        return DoctorCheck("executor cli", "ok", "custom SDEP subprocess command")
    if config.executor not in {"codex", "claude_code", "hermes", "openclaw"}:
        return DoctorCheck("executor cli", "warn", "not checked for unsupported executor")
    detection = detect_executor_cli(config.executor)
    if detection.status == "ready":
        return DoctorCheck(
            "executor cli",
            "ok",
            detection.detail,
            metadata=detection.to_payload(),
        )
    if detection.status == "broken_symlink":
        return DoctorCheck(
            "executor cli",
            "fail",
            detection.detail,
            next_step=(
                "Fix or remove the broken CLI symlink, install the CLI, "
                "or switch executor to dry_run."
            ),
            metadata=detection.to_payload(),
        )
    if detection.status == "app_only":
        return DoctorCheck(
            "executor cli",
            "warn",
            detection.detail,
            next_step=(
                "Install the terminal CLI. Advanced users can set executor_command to a compatible wrapper. "
                "Desktop apps and editor extensions are not executable by Spice subprocess."
            ),
            metadata=detection.to_payload(),
        )
    return DoctorCheck(
        "executor cli",
        "fail",
        detection.detail,
        next_step=_executor_command_next_step(config.executor),
        metadata=detection.to_payload(),
    )


def _command_exists_check(name: str, command: str, *, next_step: str) -> DoctorCheck:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return DoctorCheck(name, "fail", f"cannot parse command: {exc}")
    if not argv:
        return DoctorCheck(name, "fail", "empty command")
    executable = argv[0]
    if Path(executable).is_absolute() or "/" in executable:
        exists = Path(executable).exists()
    else:
        exists = shutil.which(executable) is not None
    if not exists:
        return DoctorCheck(
            name,
            "fail",
            f"command not found: {executable}",
            next_step=next_step,
        )
    return DoctorCheck(name, "ok", command)


def _active_session_check(paths: Any, config: SpiceWorkspaceConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("active_session", "fail", "config unavailable")
    session_path = paths.sessions_dir / f"{safe_workspace_record_id(config.active_session_id)}.json"
    if session_path.exists():
        return DoctorCheck("active_session", "ok", config.active_session_id)
    return DoctorCheck(
        "active_session",
        "warn",
        f"{config.active_session_id} has no saved session record yet",
        next_step="Run `spice decide \"...\"` or `spice session list`.",
    )


def _pending_approvals_check(paths: Any) -> DoctorCheck:
    if not paths.approvals_dir.exists():
        return DoctorCheck("pending approvals", "warn", "approvals dir missing")
    pending = 0
    total = 0
    store = LocalJsonStore(paths)
    for approval_id in store.list_record_ids("approvals"):
        total += 1
        try:
            payload = store.load_approval(approval_id)
        except Exception:
            continue
        if str(payload.get("status") or "") == "pending":
            pending += 1
    if pending:
        return DoctorCheck(
            "pending approvals",
            "warn",
            f"{pending} pending of {total} approvals",
            next_step="Run `spice approval list`.",
            metadata={"pending": pending, "total": total},
        )
    return DoctorCheck(
        "pending approvals",
        "ok",
        f"0 pending of {total} approvals",
        metadata={"pending": 0, "total": total},
    )


def _llm_api_key_env_for_provider(provider: str) -> str:
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "mimo": "XIAOMI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(provider, "")


def _llm_api_key_envs_for_provider(provider: str, configured_env: str = "") -> tuple[str, ...]:
    names: list[str] = []
    if configured_env.strip():
        names.append(configured_env.strip())
    if provider == "mimo":
        names.extend(["XIAOMI_API_KEY", "MIMO_API_KEY"])
    else:
        default = _llm_api_key_env_for_provider(provider)
        if default:
            names.append(default)
    deduped: list[str] = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)
    return tuple(deduped)


def _first_set_env(names: tuple[str, ...]) -> str:
    for name in names:
        if _env_is_set(name):
            return name
    return ""


def _env_is_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _config_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _llm_features_enabled(config: SpiceWorkspaceConfig) -> bool:
    return _config_bool(config.llm_candidate_expand) or _config_bool(config.llm_simulation)


def _overall_status(checks: list[DoctorCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "ok"
