from __future__ import annotations

import getpass
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from spice.runtime.doctor import render_doctor_report, run_doctor
from spice.runtime.executor_discovery import (
    ExecutorCLIDetection,
    detect_executor_cli,
    detect_known_executor_clis,
)
from spice.runtime.executor_runtime import resolve_executor_runtime, resolve_executor_runtime_from_config
from spice.runtime.workspace import (
    DEFAULT_WORKSPACE_CONFIG,
    SpiceWorkspaceConfig,
    SpiceWorkspaceSetupReport,
    load_workspace_env,
    setup_workspace,
    workspace_paths,
)


LLM_PROVIDER_CHOICES: tuple[tuple[str, str, str, str], ...] = (
    ("deterministic", "Deterministic", "", ""),
    ("openai", "OpenAI", "gpt-4o-mini", "OPENAI_API_KEY"),
    ("anthropic", "Anthropic", "claude-3-5-sonnet-latest", "ANTHROPIC_API_KEY"),
    ("openrouter", "OpenRouter", "openai/gpt-4o-mini", "OPENROUTER_API_KEY"),
    ("deepseek", "DeepSeek", "deepseek-chat", "DEEPSEEK_API_KEY"),
    ("mimo", "MiMo / Xiaomi", "mimo-v2.5-pro", "XIAOMI_API_KEY"),
)

EXECUTOR_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("dry_run", "Dry run", ""),
    ("sdep_subprocess", "SDEP subprocess", "python -m spice.runtime.sdep_echo_executor"),
    ("codex", "Codex", ""),
    ("claude_code", "Claude Code", "claude -p"),
    ("hermes", "Hermes", "hermes chat -Q"),
    ("openclaw", "OpenClaw", "openclaw agent --json --message"),
)

EXECUTOR_PERMISSION_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("workspace_write", "Workspace write", "can edit files in this workspace"),
    ("read_only", "Read only", "can inspect but cannot write files"),
    ("danger_full_access", "Danger full access", "executor CLI may bypass sandbox limits"),
)

PERCEPTION_CHOICES: tuple[tuple[str, str], ...] = (
    ("manual", "Manual input"),
    ("poll", "Poll URL or command"),
    ("open_chronicle", "Open Chronicle"),
)


@dataclass(slots=True)
class SetupWizardResult:
    report: SpiceWorkspaceSetupReport
    config: SpiceWorkspaceConfig
    saved_env_path: Path | None = None
    doctor_text: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "report": self.report.to_payload(),
            "config": self.config.to_payload(),
            "saved_env_path": str(self.saved_env_path) if self.saved_env_path else None,
            "doctor_text": self.doctor_text,
        }


PasswordReader = Callable[[str], str]


class _SetupBack(Exception):
    pass


class _SetupQuit(Exception):
    pass


def run_setup_wizard(
    *,
    project_root: str | Path = ".",
    force: bool = False,
    input_stream: TextIO,
    output_stream: TextIO,
    password_reader: PasswordReader | None = None,
) -> SetupWizardResult:
    """Initialize a workspace and ask for the first runtime configuration.

    The wizard is intentionally local and synchronous. It never validates API keys
    against remote providers and never starts perception or executor processes.
    """

    root = Path(project_root)
    report = setup_workspace(project_root=root, force=force)
    paths = workspace_paths(root)
    payload = _load_config_payload(paths.config)
    saved_env_path: Path | None = None
    pending_env: tuple[str, str] | None = None
    password_reader = password_reader or getpass.getpass

    _write(output_stream, "Spice setup")
    _write(output_stream, f"workspace: {paths.spice_dir}")
    _write(output_stream, "Tip: type `b` to go back, `q` to cancel.")
    _write(output_stream, "")

    step = 0
    while True:
        try:
            if step == 0:
                pending_env = _ask_llm_config(
                    payload,
                    env_path=paths.spice_dir / ".env",
                    input_stream=input_stream,
                    output_stream=output_stream,
                    password_reader=password_reader,
                )
                step = 1
                continue
            if step == 1:
                _configure_memory_summary_defaults(payload)
                _ask_executor_config(payload, input_stream=input_stream, output_stream=output_stream)
                step = 2
                continue
            if step == 2:
                _ask_perception_config(payload, input_stream=input_stream, output_stream=output_stream)
                step = 3
                continue
            config = SpiceWorkspaceConfig.from_payload(payload)
            _write(output_stream, "")
            _write(output_stream, _render_setup_review(config, pending_env=pending_env))
            if _ask_yes_no(
                "Save this configuration?",
                default=True,
                input_stream=input_stream,
                output_stream=output_stream,
            ):
                break
            edit = _ask_choice(
                (
                    ("llm", "Edit LLM provider"),
                    ("executor", "Edit executor"),
                    ("perception", "Edit perception"),
                ),
                default="llm",
                input_stream=input_stream,
                output_stream=output_stream,
            )
            step = {"llm": 0, "executor": 1, "perception": 2}[edit]
        except _SetupBack:
            if step <= 0:
                _write(output_stream, "Already at the first setup step.")
            else:
                step -= 1
                _write(output_stream, "")
                _write(output_stream, f"Back to {_setup_step_name(step)}.")
        except _SetupQuit as exc:
            raise ValueError("Setup cancelled.") from exc

    config = SpiceWorkspaceConfig.from_payload(payload)
    if pending_env is not None:
        env_name, api_key = pending_env
        saved_env_path = paths.spice_dir / ".env"
        _write_env_key(saved_env_path, env_name, api_key)
        load_workspace_env(root)
    paths.config.write_text(
        json.dumps(config.to_payload(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    doctor_text = render_doctor_report(run_doctor(root))

    _write(output_stream, "")
    _write(output_stream, "Setup complete.")
    _write(output_stream, f"llm_provider={config.llm_provider}")
    _write(output_stream, f"executor={config.executor}")
    _write(output_stream, f"perception_provider={config.perception_provider}")
    _write(output_stream, "")
    _write(output_stream, doctor_text)
    _write(output_stream, "")
    _write(output_stream, "Next:")
    _write(output_stream, "  spice shell")
    _write(output_stream, '  spice decide "I have a failing test and a pending PR review" --act')
    _write(output_stream, "  spice approval list")
    _write(output_stream, "  spice execute <approval_id>")

    return SetupWizardResult(
        report=report,
        config=config,
        saved_env_path=saved_env_path,
        doctor_text=doctor_text,
    )


def _ask_llm_config(
    payload: dict[str, object],
    *,
    env_path: Path,
    input_stream: TextIO,
    output_stream: TextIO,
    password_reader: PasswordReader,
) -> tuple[str, str] | None:
    _write(output_stream, "LLM provider")
    provider = _ask_choice(
        LLM_PROVIDER_CHOICES,
        default="deterministic",
        input_stream=input_stream,
        output_stream=output_stream,
    )
    _, _, default_model, env_name = _choice_by_id(LLM_PROVIDER_CHOICES, provider)
    model = ""
    pending_env: tuple[str, str] | None = None
    payload["llm_api_key_env"] = ""
    if provider != "deterministic":
        model = _ask_text(
            "Model",
            default=str(payload.get("llm_model") or default_model),
            input_stream=input_stream,
            output_stream=output_stream,
        )
        _write(output_stream, f"API key will be read from {env_name}.")
        _write(output_stream, "Paste the key below. Input is hidden when your terminal supports it.")
        api_key = password_reader(f"{env_name}: ").strip()
        payload["llm_api_key_env"] = env_name
        if api_key and _ask_yes_no(
            f"Save {env_name} to {env_path}?",
            default=False,
            input_stream=input_stream,
            output_stream=output_stream,
        ):
            pending_env = (env_name, api_key)
        elif api_key:
            _write(output_stream, f"Not saved. Export {env_name}=<key> before using LLM features.")
    payload["llm_provider"] = provider
    payload["llm_model"] = model

    if provider == "deterministic":
        payload["llm_candidate_expand"] = "false"
        payload["llm_simulation"] = "false"
    else:
        payload["llm_candidate_expand"] = _bool_string(
            _ask_yes_no(
                "Enable LLM candidate expansion?",
                default=True,
                input_stream=input_stream,
                output_stream=output_stream,
            )
        )
        payload["llm_simulation"] = _bool_string(
            _ask_yes_no(
                "Enable LLM simulation metadata?",
                default=True,
                input_stream=input_stream,
                output_stream=output_stream,
            )
        )
    return pending_env


def _configure_memory_summary_defaults(payload: dict[str, object]) -> None:
    provider = str(payload.get("llm_provider") or "deterministic").strip()
    candidate_expand = _truthy(payload.get("llm_candidate_expand"))
    payload["memory_provider"] = str(payload.get("memory_provider") or "file")
    payload["memory_path"] = str(payload.get("memory_path") or ".spice/memory")
    payload["context_compiler"] = str(payload.get("context_compiler") or "deterministic")
    payload["memory_summary_provider"] = (
        "llm" if provider != "deterministic" and candidate_expand else "deterministic"
    )
    payload["memory_summary_llm_min_new_records"] = str(
        payload.get("memory_summary_llm_min_new_records") or "4"
    )
    payload["memory_summary_trigger_chars"] = str(
        payload.get("memory_summary_trigger_chars") or "8000"
    )
    payload["memory_summary_target_chars"] = str(
        payload.get("memory_summary_target_chars") or "6000"
    )


def _ask_executor_config(
    payload: dict[str, object],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> None:
    _write(output_stream, "")
    _write(output_stream, "Executor")
    detections = detect_known_executor_clis()
    _write(output_stream, _render_executor_detection_summary(detections))
    executor = _ask_choice(
        EXECUTOR_CHOICES,
        default="dry_run",
        input_stream=input_stream,
        output_stream=output_stream,
    )
    _, _, default_command = _choice_by_id(EXECUTOR_CHOICES, executor)
    detection = (
        detect_executor_cli(executor)
        if executor in {"codex", "claude_code", "hermes", "openclaw"}
        else None
    )
    if detection is not None:
        _write(output_stream, _render_selected_executor_detection(detection))
        if detection.status == "ready" and detection.command:
            default_command = _default_executor_command_for_runtime(executor, detection)
    payload["executor"] = executor
    payload["permission_mode"] = "confirm_before_execution"
    if executor == "dry_run":
        payload["executor_command"] = ""
        payload["executor_permission_mode"] = "workspace_write"
        _write(output_stream, "Execution remains approval-gated and dry-run by default.")
        return
    _write(output_stream, "")
    _write(output_stream, "Execution permission")
    permission_mode = _ask_choice(
        EXECUTOR_PERMISSION_CHOICES,
        default="workspace_write",
        input_stream=input_stream,
        output_stream=output_stream,
    )
    if permission_mode == "danger_full_access":
        confirmed = _ask_yes_no(
            "Danger full access can allow the executor CLI to modify files outside this workspace. Continue?",
            default=False,
            input_stream=input_stream,
            output_stream=output_stream,
        )
        if not confirmed:
            permission_mode = "workspace_write"
            _write(output_stream, "Using workspace_write instead.")
    payload["executor_permission_mode"] = permission_mode
    if executor == "sdep_subprocess":
        payload["executor_command"] = _ask_text(
            "SDEP executor command",
            default=default_command,
            input_stream=input_stream,
            output_stream=output_stream,
        )
    else:
        runtime = resolve_executor_runtime(
            executor,
            executor_permission_mode=permission_mode,
        )
        _write(output_stream, f"Resolved executor command: {runtime.command}")
        if runtime.permission_enforcement in {"delegated_to_executor", "executor_policy"}:
            _write(output_stream, "Permission enforcement is controlled by the selected executor CLI.")
        if executor == "openclaw":
            recommended = runtime.metadata.get("recommended_policy", {})
            if isinstance(recommended, dict):
                policy = recommended.get(permission_mode)
                if policy:
                    _write(output_stream, f"OpenClaw recommended policy for {permission_mode}: {policy}")
            _write(
                output_stream,
                "Inspect OpenClaw policy with `openclaw exec-policy show --json` "
                "and `openclaw sandbox explain --json`.",
            )
        payload["executor_command"] = ""
    _write(output_stream, "Execution remains approval-gated before any handoff.")


def _default_executor_command_for_runtime(
    executor_id: str,
    detection: ExecutorCLIDetection,
) -> str:
    command = detection.command or executor_id
    if executor_id == "codex":
        return f"{command} exec --skip-git-repo-check -"
    if executor_id == "claude_code":
        return f"{command} -p"
    if executor_id == "hermes":
        return f"{command} chat -Q"
    if executor_id == "openclaw":
        return f"{command} agent --json --message"
    return command


def _render_executor_detection_summary(
    detections: dict[str, ExecutorCLIDetection],
) -> str:
    labels = {
        "codex": "Codex CLI",
        "claude_code": "Claude Code CLI",
        "hermes": "Hermes CLI",
        "openclaw": "OpenClaw CLI",
    }
    lines = ["Detected executor CLIs"]
    for executor_id in ("codex", "claude_code", "hermes", "openclaw"):
        detection = detections.get(executor_id)
        if detection is None:
            continue
        label = labels[executor_id]
        if detection.status == "ready":
            lines.append(f"- {label}: found ({detection.executable_path})")
        elif detection.status == "broken_symlink":
            lines.append(
                f"- {label}: broken symlink ({detection.broken_symlink_path} -> "
                f"{detection.broken_symlink_target})"
            )
        elif detection.status == "app_only":
            lines.append(f"- {label}: app/extension detected, CLI missing")
        else:
            lines.append(f"- {label}: missing")
    return "\n".join(lines)


def _render_selected_executor_detection(detection: ExecutorCLIDetection) -> str:
    label = detection.executor_id.replace("_", " ")
    if detection.status == "ready":
        return f"Detected {label} command: {detection.command}"
    if detection.status == "broken_symlink":
        return "\n".join(
            [
                f"{label} CLI is not usable: broken symlink detected.",
                f"  {detection.broken_symlink_path} -> {detection.broken_symlink_target}",
                "Next: install the CLI or choose dry_run.",
            ]
        )
    if detection.status == "app_only":
        return "\n".join(
            [
                f"{label} app/extension detected, but Spice needs a terminal CLI command.",
                "Next: install the CLI, configure an advanced command override, or choose dry_run.",
            ]
        )
    return f"{label} CLI not found. Install the CLI, configure an advanced command override, or choose dry_run."


def _ask_perception_config(
    payload: dict[str, object],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> None:
    _write(output_stream, "")
    _write(output_stream, "Perception")
    provider = _ask_choice(
        PERCEPTION_CHOICES,
        default="manual",
        input_stream=input_stream,
        output_stream=output_stream,
    )
    payload["perception_provider"] = provider
    payload["perception_trigger_mode"] = "state_only"
    if provider == "manual":
        return
    decide_on_change = _ask_yes_no(
        "Generate a Decision Card when perception changes?",
        default=False,
        input_stream=input_stream,
        output_stream=output_stream,
    )
    payload["perception_trigger_mode"] = "decision_on_change" if decide_on_change else "state_only"
    if provider == "poll":
        _ask_poll_config(payload, input_stream=input_stream, output_stream=output_stream)
    elif provider == "open_chronicle":
        payload["openchronicle_mcp_url"] = _ask_text(
            "Open Chronicle MCP URL",
            default=str(
                payload.get("openchronicle_mcp_url")
                or DEFAULT_WORKSPACE_CONFIG["openchronicle_mcp_url"]
            ),
            input_stream=input_stream,
            output_stream=output_stream,
        )
        payload["openchronicle_since_minutes"] = _ask_text(
            "Open Chronicle lookback minutes",
            default=str(
                payload.get("openchronicle_since_minutes")
                or DEFAULT_WORKSPACE_CONFIG["openchronicle_since_minutes"]
            ),
            input_stream=input_stream,
            output_stream=output_stream,
        )
        payload["openchronicle_context_limit"] = _ask_text(
            "Open Chronicle context limit",
            default=str(
                payload.get("openchronicle_context_limit")
                or DEFAULT_WORKSPACE_CONFIG["openchronicle_context_limit"]
            ),
            input_stream=input_stream,
            output_stream=output_stream,
        )


def _ask_poll_config(
    payload: dict[str, object],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> None:
    mode = _ask_choice(
        (("url", "Poll a URL"), ("command", "Poll a local command")),
        default="url",
        input_stream=input_stream,
        output_stream=output_stream,
    )
    if mode == "url":
        payload["perception_poll_url"] = _ask_text(
            "Poll URL",
            default=str(payload.get("perception_poll_url") or ""),
            input_stream=input_stream,
            output_stream=output_stream,
        )
        payload["perception_poll_command"] = ""
        payload["perception_allow_command_poll"] = "false"
    else:
        allow_command = _ask_yes_no(
            "Allow command polling? This runs a local command with shell=False.",
            default=False,
            input_stream=input_stream,
            output_stream=output_stream,
        )
        payload["perception_allow_command_poll"] = _bool_string(allow_command)
        payload["perception_poll_command"] = _ask_text(
            "Poll command",
            default=str(payload.get("perception_poll_command") or ""),
            input_stream=input_stream,
            output_stream=output_stream,
        )
        payload["perception_poll_url"] = ""
    payload["perception_poll_interval"] = _ask_text(
        "Poll interval seconds",
        default=str(
            payload.get("perception_poll_interval")
            or DEFAULT_WORKSPACE_CONFIG["perception_poll_interval"]
        ),
        input_stream=input_stream,
        output_stream=output_stream,
    )
    payload["perception_poll_timeout"] = _ask_text(
        "Poll timeout seconds",
        default=str(
            payload.get("perception_poll_timeout")
            or DEFAULT_WORKSPACE_CONFIG["perception_poll_timeout"]
        ),
        input_stream=input_stream,
        output_stream=output_stream,
    )


def _ask_choice(
    choices: tuple[tuple[str, ...], ...],
    *,
    default: str,
    input_stream: TextIO,
    output_stream: TextIO,
) -> str:
    for index, choice in enumerate(choices, start=1):
        _write(output_stream, f"  {index}. {choice[1]} ({choice[0]})")
    default_index = next(
        (index for index, choice in enumerate(choices, start=1) if choice[0] == default),
        1,
    )
    while True:
        answer = _read_line(
            f"Choose [{default_index}]: ",
            input_stream=input_stream,
            output_stream=output_stream,
        )
        _raise_for_control(answer)
        if not answer:
            return choices[default_index - 1][0]
        if answer.isdigit():
            index = int(answer)
            if 1 <= index <= len(choices):
                return choices[index - 1][0]
        for choice in choices:
            if answer == choice[0]:
                return choice[0]
        _write(output_stream, "Please choose a listed number or id.")


def _choice_by_id(choices: tuple[tuple[str, ...], ...], choice_id: str) -> tuple[str, ...]:
    for choice in choices:
        if choice[0] == choice_id:
            return choice
    raise ValueError(f"Unknown choice: {choice_id}")


def _ask_text(
    label: str,
    *,
    default: str,
    input_stream: TextIO,
    output_stream: TextIO,
) -> str:
    suffix = f" [{default}]" if default else ""
    answer = _read_line(
        f"{label}{suffix}: ",
        input_stream=input_stream,
        output_stream=output_stream,
    )
    _raise_for_control(answer)
    return answer or default


def _ask_yes_no(
    label: str,
    *,
    default: bool,
    input_stream: TextIO,
    output_stream: TextIO,
) -> bool:
    marker = "Y/n" if default else "y/N"
    while True:
        answer = _read_line(
            f"{label} [{marker}]: ",
            input_stream=input_stream,
            output_stream=output_stream,
        ).lower()
        _raise_for_control(answer)
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        _write(output_stream, "Please answer y or n.")


def _read_line(prompt: str, *, input_stream: TextIO, output_stream: TextIO) -> str:
    output_stream.write(prompt)
    output_stream.flush()
    line = input_stream.readline()
    if line == "":
        return ""
    return line.strip()


def _write(output_stream: TextIO, text: str) -> None:
    output_stream.write(f"{text}\n")


def _raise_for_control(answer: str) -> None:
    lowered = answer.strip().lower()
    if lowered in {"b", "back"}:
        raise _SetupBack()
    if lowered in {"q", "quit", "exit"}:
        raise _SetupQuit()


def _setup_step_name(step: int) -> str:
    return {
        0: "LLM provider",
        1: "Executor",
        2: "Perception",
        3: "Review",
    }.get(step, "setup")


def _render_setup_review(
    config: SpiceWorkspaceConfig,
    *,
    pending_env: tuple[str, str] | None,
) -> str:
    runtime = resolve_executor_runtime_from_config(config)
    env_label = pending_env[0] if pending_env else config.llm_api_key_env or "not needed"
    env_saved = "yes" if pending_env else "no"
    lines = [
        "Review configuration",
        "",
        f"llm_provider.............. {config.llm_provider}",
        f"llm_model................. {config.llm_model or '<default>'}",
        f"llm_api_key_env........... {env_label}",
        f"save_api_key_to_env....... {env_saved}",
        f"llm_candidate_expand...... {config.llm_candidate_expand}",
        f"llm_simulation............ {config.llm_simulation}",
        "",
        f"memory_provider........... {config.memory_provider}",
        f"memory_path............... {config.memory_path}",
        f"context_compiler.......... {config.context_compiler}",
        f"memory_summary............ {config.memory_summary_provider}",
        f"memory_summary_trigger.... {config.memory_summary_llm_min_new_records} records or {config.memory_summary_trigger_chars} chars",
        f"memory_summary_target..... {config.memory_summary_target_chars} chars",
        "",
        f"executor.................. {config.executor}",
        f"executor_permission....... {config.executor_permission_mode}",
        f"executor_command.......... {runtime.command}",
        f"executor_command_source... {runtime.command_source}",
        f"executor_transport........ {runtime.transport}",
        f"executor_permission_source {runtime.permission_enforcement}",
        f"executor_real_runtime..... {str(runtime.real_executor).lower()}",
        f"executor_status........... {runtime.status}",
        "",
        f"perception_provider....... {config.perception_provider}",
        f"perception_trigger_mode... {config.perception_trigger_mode}",
    ]
    if config.perception_provider == "poll":
        lines.extend(
            [
                f"perception_poll_url...... {config.perception_poll_url or '<none>'}",
                f"perception_poll_command.. {config.perception_poll_command or '<none>'}",
            ]
        )
    if config.perception_provider == "open_chronicle":
        lines.append(f"openchronicle_mcp_url.... {config.openchronicle_mcp_url}")
    lines.extend(
        [
            "",
            "Boundary: approvals are required before executor handoff.",
            "Boundary: perception can create Decision Cards, but never executes automatically.",
        ]
    )
    return "\n".join(lines)


def _load_config_payload(config_path: Path) -> dict[str, object]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Workspace config payload must be a dict.")
    return payload


def _write_env_key(env_path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    updated = False
    next_lines: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            next_lines.append(f"{key}={value}")
            updated = True
        else:
            next_lines.append(line)
    if not updated:
        next_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")


def _bool_string(value: bool) -> str:
    return "true" if value else "false"


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
