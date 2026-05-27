from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from spice.decision.general import GeneralDecisionState, store_general_state
from spice.decision.general.types import payload_value
from spice.memory import ContextCompiler, DeterministicContextCompiler, FileMemoryProvider, MemoryProvider
from spice.protocols import WorldState

SPICE_DIR_NAME = ".spice"
WORKSPACE_CONFIG_SCHEMA_VERSION = "spice.workspace.config.v1"
WORKSPACE_STATE_SCHEMA_VERSION = "spice.workspace.state.v1"

DEFAULT_WORKSPACE_CONFIG: dict[str, str] = {
    "llm_provider": "deterministic",
    "llm_model": "",
    "llm_api_key_env": "",
    "llm_candidate_expand": "false",
    "llm_simulation": "false",
    "executor": "dry_run",
    "executor_command": "",
    "executor_permission_mode": "workspace_write",
    "permission_mode": "confirm_before_execution",
    "perception_provider": "manual",
    "perception_poll_url": "",
    "perception_poll_command": "",
    "perception_poll_interval": "60",
    "perception_poll_timeout": "10",
    "perception_allow_command_poll": "false",
    "openchronicle_mcp_url": "http://127.0.0.1:8742/mcp",
    "openchronicle_since_minutes": "15",
    "openchronicle_context_limit": "5",
    "perception_trigger_mode": "state_only",
    "store": "local_json",
    "memory_provider": "file",
    "memory_path": ".spice/memory",
    "context_compiler": "deterministic",
    "memory_summary_provider": "deterministic",
    "memory_summary_llm_min_new_records": "4",
    "memory_summary_trigger_chars": "8000",
    "memory_summary_target_chars": "6000",
    "active_session_id": "session.default",
}

DEFAULT_WORKSPACE_PERCEPTION_CONFIG: dict[str, str] = {
    "depth": "auto",
    "max_rounds": "",
    "max_tool_calls": "",
    "max_files_read": "",
    "total_char_budget": "",
}

VALID_WORKSPACE_CONFIG_KEYS = frozenset(DEFAULT_WORKSPACE_CONFIG.keys())
VALID_WORKSPACE_PERCEPTION_CONFIG_KEYS = frozenset(DEFAULT_WORKSPACE_PERCEPTION_CONFIG.keys())
VALID_WORKSPACE_PERCEPTION_DEPTHS = frozenset({"auto", "normal", "deep", "native"})
VALID_WORKSPACE_EXECUTORS = frozenset(
    {"claude_code", "codex", "dry_run", "hermes", "openclaw", "sdep_subprocess"}
)
VALID_WORKSPACE_LLM_PROVIDERS = frozenset(
    {
        "anthropic",
        "deepseek",
        "deterministic",
        "mimo",
        "openai",
        "openrouter",
        "subprocess",
    }
)
VALID_WORKSPACE_PERMISSION_MODES = frozenset({"confirm_before_execution"})
VALID_WORKSPACE_EXECUTOR_PERMISSION_MODES = frozenset(
    {"danger_full_access", "read_only", "workspace_write"}
)
VALID_WORKSPACE_PERCEPTION_PROVIDERS = frozenset({"manual", "open_chronicle", "poll"})
VALID_WORKSPACE_PERCEPTION_TRIGGER_MODES = frozenset({"state_only", "decision_on_change"})
VALID_WORKSPACE_STORES = frozenset({"local_json"})
VALID_WORKSPACE_MEMORY_PROVIDERS = frozenset({"file"})
VALID_WORKSPACE_CONTEXT_COMPILERS = frozenset({"deterministic"})
VALID_WORKSPACE_MEMORY_SUMMARY_PROVIDERS = frozenset({"deterministic", "llm"})


@dataclass(slots=True)
class SpiceWorkspaceConfig:
    schema_version: str = WORKSPACE_CONFIG_SCHEMA_VERSION
    llm_provider: str = DEFAULT_WORKSPACE_CONFIG["llm_provider"]
    llm_model: str = DEFAULT_WORKSPACE_CONFIG["llm_model"]
    llm_api_key_env: str = DEFAULT_WORKSPACE_CONFIG["llm_api_key_env"]
    llm_candidate_expand: str = DEFAULT_WORKSPACE_CONFIG["llm_candidate_expand"]
    llm_simulation: str = DEFAULT_WORKSPACE_CONFIG["llm_simulation"]
    executor: str = DEFAULT_WORKSPACE_CONFIG["executor"]
    executor_command: str = DEFAULT_WORKSPACE_CONFIG["executor_command"]
    executor_permission_mode: str = DEFAULT_WORKSPACE_CONFIG["executor_permission_mode"]
    permission_mode: str = DEFAULT_WORKSPACE_CONFIG["permission_mode"]
    perception_provider: str = DEFAULT_WORKSPACE_CONFIG["perception_provider"]
    perception_poll_url: str = DEFAULT_WORKSPACE_CONFIG["perception_poll_url"]
    perception_poll_command: str = DEFAULT_WORKSPACE_CONFIG["perception_poll_command"]
    perception_poll_interval: str = DEFAULT_WORKSPACE_CONFIG["perception_poll_interval"]
    perception_poll_timeout: str = DEFAULT_WORKSPACE_CONFIG["perception_poll_timeout"]
    perception_allow_command_poll: str = DEFAULT_WORKSPACE_CONFIG["perception_allow_command_poll"]
    openchronicle_mcp_url: str = DEFAULT_WORKSPACE_CONFIG["openchronicle_mcp_url"]
    openchronicle_since_minutes: str = DEFAULT_WORKSPACE_CONFIG["openchronicle_since_minutes"]
    openchronicle_context_limit: str = DEFAULT_WORKSPACE_CONFIG["openchronicle_context_limit"]
    perception_trigger_mode: str = DEFAULT_WORKSPACE_CONFIG["perception_trigger_mode"]
    store: str = DEFAULT_WORKSPACE_CONFIG["store"]
    memory_provider: str = DEFAULT_WORKSPACE_CONFIG["memory_provider"]
    memory_path: str = DEFAULT_WORKSPACE_CONFIG["memory_path"]
    context_compiler: str = DEFAULT_WORKSPACE_CONFIG["context_compiler"]
    memory_summary_provider: str = DEFAULT_WORKSPACE_CONFIG["memory_summary_provider"]
    memory_summary_llm_min_new_records: str = DEFAULT_WORKSPACE_CONFIG[
        "memory_summary_llm_min_new_records"
    ]
    memory_summary_trigger_chars: str = DEFAULT_WORKSPACE_CONFIG[
        "memory_summary_trigger_chars"
    ]
    memory_summary_target_chars: str = DEFAULT_WORKSPACE_CONFIG[
        "memory_summary_target_chars"
    ]
    active_session_id: str = DEFAULT_WORKSPACE_CONFIG["active_session_id"]
    workspace_perception: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_WORKSPACE_PERCEPTION_CONFIG)
    )
    metadata: dict[str, Any] = field(
        default_factory=lambda: {
            "created_by": "spice setup",
            "role": "local workspace configuration",
        }
    )

    def to_payload(self) -> dict[str, Any]:
        return payload_value(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SpiceWorkspaceConfig":
        if not isinstance(payload, dict):
            raise ValueError("Workspace config payload must be a dict.")
        return cls(
            schema_version=str(payload.get("schema_version") or WORKSPACE_CONFIG_SCHEMA_VERSION),
            llm_provider=str(payload.get("llm_provider") or DEFAULT_WORKSPACE_CONFIG["llm_provider"]),
            llm_model=str(payload.get("llm_model") or DEFAULT_WORKSPACE_CONFIG["llm_model"]),
            llm_api_key_env=str(
                payload.get("llm_api_key_env") or DEFAULT_WORKSPACE_CONFIG["llm_api_key_env"]
            ),
            llm_candidate_expand=str(
                payload.get("llm_candidate_expand")
                or DEFAULT_WORKSPACE_CONFIG["llm_candidate_expand"]
            ),
            llm_simulation=str(
                payload.get("llm_simulation")
                or DEFAULT_WORKSPACE_CONFIG["llm_simulation"]
            ),
            executor=str(payload.get("executor") or DEFAULT_WORKSPACE_CONFIG["executor"]),
            executor_command=str(
                payload.get("executor_command") or DEFAULT_WORKSPACE_CONFIG["executor_command"]
            ),
            executor_permission_mode=str(
                payload.get("executor_permission_mode")
                or DEFAULT_WORKSPACE_CONFIG["executor_permission_mode"]
            ),
            permission_mode=str(
                payload.get("permission_mode") or DEFAULT_WORKSPACE_CONFIG["permission_mode"]
            ),
            perception_provider=str(
                payload.get("perception_provider") or DEFAULT_WORKSPACE_CONFIG["perception_provider"]
            ),
            perception_poll_url=str(
                payload.get("perception_poll_url") or DEFAULT_WORKSPACE_CONFIG["perception_poll_url"]
            ),
            perception_poll_command=str(
                payload.get("perception_poll_command")
                or DEFAULT_WORKSPACE_CONFIG["perception_poll_command"]
            ),
            perception_poll_interval=str(
                payload.get("perception_poll_interval")
                or DEFAULT_WORKSPACE_CONFIG["perception_poll_interval"]
            ),
            perception_poll_timeout=str(
                payload.get("perception_poll_timeout")
                or DEFAULT_WORKSPACE_CONFIG["perception_poll_timeout"]
            ),
            perception_allow_command_poll=str(
                payload.get("perception_allow_command_poll")
                or DEFAULT_WORKSPACE_CONFIG["perception_allow_command_poll"]
            ),
            openchronicle_mcp_url=str(
                payload.get("openchronicle_mcp_url")
                or DEFAULT_WORKSPACE_CONFIG["openchronicle_mcp_url"]
            ),
            openchronicle_since_minutes=str(
                payload.get("openchronicle_since_minutes")
                or DEFAULT_WORKSPACE_CONFIG["openchronicle_since_minutes"]
            ),
            openchronicle_context_limit=str(
                payload.get("openchronicle_context_limit")
                or DEFAULT_WORKSPACE_CONFIG["openchronicle_context_limit"]
            ),
            perception_trigger_mode=str(
                payload.get("perception_trigger_mode")
                or DEFAULT_WORKSPACE_CONFIG["perception_trigger_mode"]
            ),
            store=str(payload.get("store") or DEFAULT_WORKSPACE_CONFIG["store"]),
            memory_provider=str(
                payload.get("memory_provider") or DEFAULT_WORKSPACE_CONFIG["memory_provider"]
            ),
            memory_path=str(payload.get("memory_path") or DEFAULT_WORKSPACE_CONFIG["memory_path"]),
            context_compiler=str(
                payload.get("context_compiler") or DEFAULT_WORKSPACE_CONFIG["context_compiler"]
            ),
            memory_summary_provider=str(
                payload.get("memory_summary_provider")
                or DEFAULT_WORKSPACE_CONFIG["memory_summary_provider"]
            ),
            memory_summary_llm_min_new_records=str(
                payload.get("memory_summary_llm_min_new_records")
                or DEFAULT_WORKSPACE_CONFIG["memory_summary_llm_min_new_records"]
            ),
            memory_summary_trigger_chars=str(
                payload.get("memory_summary_trigger_chars")
                or DEFAULT_WORKSPACE_CONFIG["memory_summary_trigger_chars"]
            ),
            memory_summary_target_chars=str(
                payload.get("memory_summary_target_chars")
                or DEFAULT_WORKSPACE_CONFIG["memory_summary_target_chars"]
            ),
            active_session_id=str(
                payload.get("active_session_id") or DEFAULT_WORKSPACE_CONFIG["active_session_id"]
            ),
            workspace_perception=_workspace_perception_config_from_payload(
                payload.get("workspace_perception")
            ),
            metadata=dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {},
        )


@dataclass(frozen=True, slots=True)
class SpiceWorkspacePaths:
    project_root: Path
    spice_dir: Path
    config: Path
    decision_profile: Path
    state_dir: Path
    state: Path
    sessions_dir: Path
    runs_dir: Path
    decisions_dir: Path
    approvals_dir: Path
    investigations_dir: Path
    outcomes_dir: Path
    perceptions_dir: Path
    conversations_dir: Path
    cache_dir: Path
    memory_dir: Path
    executors_dir: Path
    skills_dir: Path

    @property
    def directories(self) -> tuple[Path, ...]:
        return (
            self.spice_dir,
            self.state_dir,
            self.sessions_dir,
            self.runs_dir,
            self.decisions_dir,
            self.approvals_dir,
            self.investigations_dir,
            self.outcomes_dir,
            self.perceptions_dir,
            self.conversations_dir,
            self.cache_dir,
            self.memory_dir,
            self.executors_dir,
            self.skills_dir,
        )


@dataclass(slots=True)
class SpiceWorkspaceSetupReport:
    workspace: Path
    created: list[Path] = field(default_factory=list)
    existing: list[Path] = field(default_factory=list)
    overwritten: list[Path] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "created": [str(path) for path in self.created],
            "existing": [str(path) for path in self.existing],
            "overwritten": [str(path) for path in self.overwritten],
        }


def workspace_paths(project_root: str | Path = ".") -> SpiceWorkspacePaths:
    root = Path(project_root)
    spice_dir = root / SPICE_DIR_NAME
    return SpiceWorkspacePaths(
        project_root=root,
        spice_dir=spice_dir,
        config=spice_dir / "config.json",
        decision_profile=spice_dir / "decision.md",
        state_dir=spice_dir / "state",
        state=spice_dir / "state" / "state.json",
        sessions_dir=spice_dir / "sessions",
        runs_dir=spice_dir / "runs",
        decisions_dir=spice_dir / "decisions",
        approvals_dir=spice_dir / "approvals",
        investigations_dir=spice_dir / "investigations",
        outcomes_dir=spice_dir / "outcomes",
        perceptions_dir=spice_dir / "perceptions",
        conversations_dir=spice_dir / "conversations",
        cache_dir=spice_dir / "cache",
        memory_dir=spice_dir / "memory",
        executors_dir=spice_dir / "executors",
        skills_dir=spice_dir / "skills",
    )


def setup_workspace(
    *,
    project_root: str | Path = ".",
    force: bool = False,
) -> SpiceWorkspaceSetupReport:
    paths = workspace_paths(project_root)
    report = SpiceWorkspaceSetupReport(workspace=paths.spice_dir)

    for directory in paths.directories:
        _ensure_directory(directory, report=report)

    _write_json_file(
        paths.config,
        SpiceWorkspaceConfig().to_payload(),
        force=force,
        report=report,
    )
    _write_text_file(
        paths.decision_profile,
        _default_decision_profile_text(),
        force=force,
        report=report,
    )
    _write_json_file(
        paths.state,
        _default_state_payload(),
        force=force,
        report=report,
    )
    return report


def load_workspace_config(project_root: str | Path = ".") -> SpiceWorkspaceConfig:
    paths = workspace_paths(project_root)
    payload = json.loads(paths.config.read_text(encoding="utf-8"))
    return SpiceWorkspaceConfig.from_payload(payload)


def workspace_memory_path(
    project_root: str | Path = ".",
    config: SpiceWorkspaceConfig | None = None,
) -> Path:
    root = Path(project_root)
    config = config or load_workspace_config(root)
    configured = Path(config.memory_path)
    if configured.is_absolute():
        return configured
    return root / configured


def load_workspace_memory_provider(
    project_root: str | Path = ".",
    config: SpiceWorkspaceConfig | None = None,
) -> MemoryProvider:
    config = config or load_workspace_config(project_root)
    if config.memory_provider != "file":
        raise ValueError(f"Unsupported memory_provider: {config.memory_provider}")
    return FileMemoryProvider(workspace_memory_path(project_root, config))


def load_workspace_context_compiler(
    project_root: str | Path = ".",
    config: SpiceWorkspaceConfig | None = None,
    memory_provider: MemoryProvider | None = None,
) -> ContextCompiler:
    config = config or load_workspace_config(project_root)
    if config.context_compiler != "deterministic":
        raise ValueError(f"Unsupported context_compiler: {config.context_compiler}")
    provider = memory_provider or load_workspace_memory_provider(project_root, config)
    return DeterministicContextCompiler(memory_provider=provider)


def load_workspace_env(
    project_root: str | Path = ".",
    *,
    override: bool = False,
) -> dict[str, str]:
    """Load simple KEY=value entries from .spice/.env into os.environ.

    Existing non-empty environment variables win by default. This keeps shell
    exports authoritative while making setup-saved API keys usable immediately
    by runtime commands.
    """

    env_path = workspace_paths(project_root).spice_dir / ".env"
    if not env_path.exists():
        return {}
    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = value
            loaded[key] = value
    return loaded


def require_workspace(project_root: str | Path = ".") -> SpiceWorkspacePaths:
    paths = workspace_paths(project_root)
    missing = [path for path in (paths.config, paths.decision_profile, paths.state) if not path.exists()]
    if missing:
        rendered = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            f"Spice workspace is not initialized. Missing: {rendered}. Run `spice setup` first."
        )
    return paths


def update_workspace_config(
    project_root: str | Path,
    key: str,
    value: str,
) -> SpiceWorkspaceConfig:
    paths = require_workspace(project_root)
    normalized_key, normalized_value = validate_workspace_config_update(
        project_root,
        key,
        value,
    )
    payload = json.loads(paths.config.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Workspace config payload must be a dict.")
    if normalized_key.startswith("workspace_perception."):
        perception_key = normalized_key.split(".", 1)[1]
        workspace_perception = payload.get("workspace_perception")
        if not isinstance(workspace_perception, dict):
            workspace_perception = dict(DEFAULT_WORKSPACE_PERCEPTION_CONFIG)
        workspace_perception[perception_key] = normalized_value
        payload["workspace_perception"] = workspace_perception
    else:
        payload[normalized_key] = normalized_value
    paths.config.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return SpiceWorkspaceConfig.from_payload(payload)


def configure_workspace_llm(
    project_root: str | Path,
    *,
    provider: str,
    model: str,
    candidate_expand: bool = True,
    simulation: bool = True,
) -> SpiceWorkspaceConfig:
    paths = require_workspace(project_root)
    normalized_provider = provider.strip()
    if normalized_provider not in VALID_WORKSPACE_LLM_PROVIDERS:
        valid = ", ".join(sorted(VALID_WORKSPACE_LLM_PROVIDERS))
        raise ValueError(f"Invalid llm_provider: {normalized_provider}. Valid values: {valid}.")
    normalized_model = model.strip()
    if normalized_provider != "deterministic" and not normalized_model:
        raise ValueError("llm_model is required for non-deterministic LLM providers.")
    payload = json.loads(paths.config.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Workspace config payload must be a dict.")
    payload["llm_provider"] = normalized_provider
    payload["llm_model"] = normalized_model
    payload["llm_api_key_env"] = _llm_api_key_env_for_provider(normalized_provider)
    payload["llm_candidate_expand"] = "true" if candidate_expand else "false"
    payload["llm_simulation"] = "true" if simulation else "false"
    payload["memory_summary_provider"] = (
        "llm" if normalized_provider != "deterministic" and candidate_expand else "deterministic"
    )
    paths.config.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return SpiceWorkspaceConfig.from_payload(payload)


def validate_workspace_config_update(
    project_root: str | Path,
    key: str,
    value: str,
) -> tuple[str, str]:
    normalized_key = key.strip()
    if normalized_key.startswith("workspace_perception."):
        nested_key = normalized_key.split(".", 1)[1].strip()
        normalized_nested_key, normalized_value = _validate_workspace_perception_config_update(
            nested_key,
            value,
        )
        return f"workspace_perception.{normalized_nested_key}", normalized_value
    if normalized_key not in VALID_WORKSPACE_CONFIG_KEYS:
        valid = ", ".join(sorted(_all_valid_workspace_config_keys()))
        raise ValueError(f"Unknown config key: {key}. Valid keys: {valid}.")
    normalized_value = value.strip()
    optional_keys = {
        "executor_command",
        "llm_api_key_env",
        "llm_model",
        "memory_path",
        "openchronicle_mcp_url",
        "perception_poll_command",
        "perception_poll_url",
    }
    if normalized_key not in optional_keys and not normalized_value:
        raise ValueError(f"Config value for {normalized_key} must be non-empty.")
    if normalized_key in {"llm_api_key_env", "llm_model"}:
        return normalized_key, normalized_value
    if normalized_key in {
        "llm_candidate_expand",
        "llm_simulation",
        "memory_summary_llm_min_new_records",
        "memory_summary_target_chars",
        "memory_summary_trigger_chars",
        "perception_allow_command_poll",
    }:
        if normalized_key in {
            "memory_summary_llm_min_new_records",
            "memory_summary_target_chars",
            "memory_summary_trigger_chars",
        }:
            try:
                parsed = int(normalized_value)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid {normalized_key}: {normalized_value}. Must be an integer."
                ) from exc
            if parsed <= 0:
                raise ValueError(
                    f"Invalid {normalized_key}: {normalized_value}. Must be positive."
                )
            normalized_value = str(parsed)
        else:
            normalized_value = _normalize_config_bool(normalized_value, key=normalized_key)
    if normalized_key == "llm_provider" and normalized_value not in VALID_WORKSPACE_LLM_PROVIDERS:
        valid = ", ".join(sorted(VALID_WORKSPACE_LLM_PROVIDERS))
        raise ValueError(f"Invalid llm_provider: {normalized_value}. Valid values: {valid}.")
    if normalized_key == "executor" and normalized_value not in VALID_WORKSPACE_EXECUTORS:
        valid = ", ".join(sorted(VALID_WORKSPACE_EXECUTORS))
        raise ValueError(f"Invalid executor: {normalized_value}. Valid values: {valid}.")
    if (
        normalized_key == "executor_permission_mode"
        and normalized_value not in VALID_WORKSPACE_EXECUTOR_PERMISSION_MODES
    ):
        valid = ", ".join(sorted(VALID_WORKSPACE_EXECUTOR_PERMISSION_MODES))
        raise ValueError(
            f"Invalid executor_permission_mode: {normalized_value}. Valid values: {valid}."
        )
    if (
        normalized_key == "permission_mode"
        and normalized_value not in VALID_WORKSPACE_PERMISSION_MODES
    ):
        valid = ", ".join(sorted(VALID_WORKSPACE_PERMISSION_MODES))
        raise ValueError(f"Invalid permission_mode: {normalized_value}. Valid values: {valid}.")
    if (
        normalized_key == "perception_provider"
        and normalized_value not in VALID_WORKSPACE_PERCEPTION_PROVIDERS
    ):
        valid = ", ".join(sorted(VALID_WORKSPACE_PERCEPTION_PROVIDERS))
        raise ValueError(f"Invalid perception_provider: {normalized_value}. Valid values: {valid}.")
    if (
        normalized_key == "perception_trigger_mode"
        and normalized_value not in VALID_WORKSPACE_PERCEPTION_TRIGGER_MODES
    ):
        valid = ", ".join(sorted(VALID_WORKSPACE_PERCEPTION_TRIGGER_MODES))
        raise ValueError(f"Invalid perception_trigger_mode: {normalized_value}. Valid values: {valid}.")
    if normalized_key in {
        "openchronicle_context_limit",
        "openchronicle_since_minutes",
        "perception_poll_interval",
        "perception_poll_timeout",
    }:
        try:
            parsed = int(normalized_value)
        except ValueError as exc:
            raise ValueError(f"Invalid {normalized_key}: {normalized_value}. Must be an integer.") from exc
        if parsed <= 0:
            raise ValueError(f"Invalid {normalized_key}: {normalized_value}. Must be positive.")
        normalized_value = str(parsed)
    if normalized_key == "store" and normalized_value not in VALID_WORKSPACE_STORES:
        valid = ", ".join(sorted(VALID_WORKSPACE_STORES))
        raise ValueError(f"Invalid store: {normalized_value}. Valid values: {valid}.")
    if (
        normalized_key == "memory_provider"
        and normalized_value not in VALID_WORKSPACE_MEMORY_PROVIDERS
    ):
        valid = ", ".join(sorted(VALID_WORKSPACE_MEMORY_PROVIDERS))
        raise ValueError(f"Invalid memory_provider: {normalized_value}. Valid values: {valid}.")
    if (
        normalized_key == "context_compiler"
        and normalized_value not in VALID_WORKSPACE_CONTEXT_COMPILERS
    ):
        valid = ", ".join(sorted(VALID_WORKSPACE_CONTEXT_COMPILERS))
        raise ValueError(f"Invalid context_compiler: {normalized_value}. Valid values: {valid}.")
    if (
        normalized_key == "memory_summary_provider"
        and normalized_value not in VALID_WORKSPACE_MEMORY_SUMMARY_PROVIDERS
    ):
        valid = ", ".join(sorted(VALID_WORKSPACE_MEMORY_SUMMARY_PROVIDERS))
        raise ValueError(
            f"Invalid memory_summary_provider: {normalized_value}. Valid values: {valid}."
        )
    if normalized_key == "active_session_id":
        session_path = workspace_paths(project_root).sessions_dir / f"{safe_workspace_record_id(normalized_value)}.json"
        if not session_path.exists():
            raise FileNotFoundError(
                f"Session does not exist: {normalized_value}. "
                "Run `spice session list` to find available sessions."
            )
    return normalized_key, normalized_value


def _all_valid_workspace_config_keys() -> tuple[str, ...]:
    nested = tuple(
        f"workspace_perception.{key}" for key in sorted(VALID_WORKSPACE_PERCEPTION_CONFIG_KEYS)
    )
    return tuple(sorted(VALID_WORKSPACE_CONFIG_KEYS)) + nested


def _workspace_perception_config_from_payload(value: object) -> dict[str, str]:
    result = dict(DEFAULT_WORKSPACE_PERCEPTION_CONFIG)
    if not isinstance(value, Mapping):
        return result
    for key in VALID_WORKSPACE_PERCEPTION_CONFIG_KEYS:
        if key not in value:
            continue
        _, normalized_value = _validate_workspace_perception_config_update(
            key,
            str(value.get(key) or ""),
        )
        result[key] = normalized_value
    return result


def _validate_workspace_perception_config_update(key: str, value: str) -> tuple[str, str]:
    normalized_key = key.strip()
    if normalized_key not in VALID_WORKSPACE_PERCEPTION_CONFIG_KEYS:
        valid = ", ".join(sorted(VALID_WORKSPACE_PERCEPTION_CONFIG_KEYS))
        raise ValueError(
            f"Unknown workspace_perception config key: {key}. Valid keys: {valid}."
        )
    normalized_value = value.strip()
    if normalized_key == "depth":
        if not normalized_value:
            normalized_value = DEFAULT_WORKSPACE_PERCEPTION_CONFIG["depth"]
        if normalized_value not in VALID_WORKSPACE_PERCEPTION_DEPTHS:
            valid = ", ".join(sorted(VALID_WORKSPACE_PERCEPTION_DEPTHS))
            raise ValueError(
                f"Invalid workspace_perception.depth: {normalized_value}. Valid values: {valid}."
            )
        return normalized_key, normalized_value
    if normalized_value == "":
        return normalized_key, ""
    try:
        parsed = int(normalized_value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid workspace_perception.{normalized_key}: {normalized_value}. "
            "Must be a positive integer or empty."
        ) from exc
    if parsed <= 0:
        raise ValueError(
            f"Invalid workspace_perception.{normalized_key}: {normalized_value}. "
            "Must be positive."
        )
    return normalized_key, str(parsed)


def _normalize_config_bool(value: str, *, key: str) -> str:
    token = value.strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return "true"
    if token in {"0", "false", "no", "off"}:
        return "false"
    raise ValueError(f"Invalid {key}: {value}. Valid values: true, false.")


def _llm_api_key_env_for_provider(provider: str) -> str:
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "mimo": "XIAOMI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(provider, "")


def set_workspace_active_session(
    project_root: str | Path,
    session_id: str,
) -> SpiceWorkspaceConfig:
    if not session_id:
        raise ValueError("session_id must be non-empty.")
    paths = workspace_paths(project_root)
    payload = json.loads(paths.config.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Workspace config payload must be a dict.")
    payload["active_session_id"] = session_id
    paths.config.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return SpiceWorkspaceConfig.from_payload(payload)


def safe_workspace_record_id(record_id: str) -> str:
    allowed = []
    for char in record_id:
        if char.isalnum() or char in {"-", "_", "."}:
            allowed.append(char)
        else:
            allowed.append("_")
    safe = "".join(allowed).strip("._")
    if not safe:
        raise ValueError(f"record_id cannot be converted to a safe filename: {record_id!r}")
    return safe


def _ensure_directory(path: Path, *, report: SpiceWorkspaceSetupReport) -> None:
    if path.exists():
        report.existing.append(path)
        if not path.is_dir():
            raise FileExistsError(f"Workspace path exists but is not a directory: {path}")
        return
    path.mkdir(parents=True, exist_ok=True)
    report.created.append(path)


def _write_json_file(
    path: Path,
    payload: dict[str, Any],
    *,
    force: bool,
    report: SpiceWorkspaceSetupReport,
) -> None:
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    _write_text_file(path, text, force=force, report=report)


def _write_text_file(
    path: Path,
    text: str,
    *,
    force: bool,
    report: SpiceWorkspaceSetupReport,
) -> None:
    existed = path.exists()
    if existed and not force:
        report.existing.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if existed and force:
        report.overwritten.append(path)
    else:
        report.created.append(path)


def _default_decision_profile_text() -> str:
    return (
        files("spice.decision.profiles")
        .joinpath("default.decision.md")
        .read_text(encoding="utf-8")
    )


def _default_state_payload() -> dict[str, Any]:
    world_state = WorldState(
        id="worldstate.local",
        provenance={"created_by": "spice setup"},
    )
    general_state = GeneralDecisionState(
        state_id=world_state.id,
        metadata={"created_by": "spice setup"},
    )
    store_general_state(world_state, general_state)
    return {
        "schema_version": WORKSPACE_STATE_SCHEMA_VERSION,
        "world_state": payload_value(world_state),
    }
