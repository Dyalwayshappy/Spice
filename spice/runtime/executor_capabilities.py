from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any

from spice.decision.general.types import PayloadRecord, safe_dataclass_from_payload
from spice.executors.sdep import SubprocessSDEPTransport
from spice.executors.sdep_mapping import build_sdep_describe_request
from spice.protocols import SDEPDescribeResponse


EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION = "spice.executor_capability_snapshot.v1"

CAPABILITY_SNAPSHOT_SOURCES = (
    "static_baseline",
    "sdep_describe",
    "unavailable",
)

CAPABILITY_SNAPSHOT_STATUSES = (
    "available",
    "unavailable",
    "unknown",
)

_BASELINE_LIMITATION = "Static baseline, not live tool inventory."

_STATIC_EXECUTOR_CAPABILITY_BASELINES: dict[str, dict[str, Any]] = {
    "dry_run": {
        "executor_id": "dry_run",
        "provider": "dry_run",
        "status": "available",
        "source": "static_baseline",
        "capability_ids": ["simulate_execution"],
        "permission_modes": ["read_only"],
        "summary": "Previews an execution handoff without calling an external executor.",
        "limitations": [
            "No real side effects.",
            _BASELINE_LIMITATION,
        ],
        "metadata": {"baseline_only": True, "live_tool_list": False},
    },
    "codex": {
        "executor_id": "codex",
        "provider": "codex",
        "status": "available",
        "source": "static_baseline",
        "capability_ids": [
            "repo_read",
            "code_edit",
            "test_run",
            "workspace_write",
            "terminal_command",
        ],
        "permission_modes": ["read_only", "workspace_write", "danger_full_access"],
        "summary": "Good for repo-local coding work, tests, and terminal-backed implementation.",
        "limitations": [
            _BASELINE_LIMITATION,
            "Actual tools and sandbox behavior depend on the installed Codex runtime.",
        ],
        "metadata": {"baseline_only": True, "live_tool_list": False},
    },
    "claude_code": {
        "executor_id": "claude_code",
        "provider": "claude_code",
        "status": "available",
        "source": "static_baseline",
        "capability_ids": [
            "repo_read",
            "code_edit",
            "workspace_write",
            "terminal_command",
        ],
        "permission_modes": ["read_only", "workspace_write", "danger_full_access"],
        "summary": "Good for repo-local coding work and terminal-backed implementation.",
        "limitations": [
            _BASELINE_LIMITATION,
            "Actual tools and permission behavior depend on the installed Claude Code runtime.",
        ],
        "metadata": {"baseline_only": True, "live_tool_list": False},
    },
    "hermes": {
        "executor_id": "hermes",
        "provider": "hermes",
        "status": "available",
        "source": "static_baseline",
        "capability_ids": [
            "general_execution",
            "tool_use",
            "workspace_write",
            "browser_or_external_tools",
            "note_or_memory_work",
        ],
        "permission_modes": ["read_only", "workspace_write", "danger_full_access"],
        "summary": "Good for broad tool-use execution after approval.",
        "limitations": [
            _BASELINE_LIMITATION,
            "Hermes tool and skill inventory can vary by installation.",
        ],
        "metadata": {"baseline_only": True, "live_tool_list": False},
    },
    "openclaw": {
        "executor_id": "openclaw",
        "provider": "openclaw",
        "status": "available",
        "source": "static_baseline",
        "capability_ids": [
            "general_execution",
            "tool_use",
            "gateway_agent_turn",
            "agent_routing",
            "workspace_write",
            "browser_or_external_tools",
            "message_or_channel_work",
            "channel_messaging",
        ],
        "permission_modes": ["read_only", "workspace_write", "danger_full_access"],
        "summary": (
            "Good for OpenClaw Gateway-backed agent turns, channel workflows, "
            "and broad executor handoff after Spice approval."
        ),
        "limitations": [
            _BASELINE_LIMITATION,
            "OpenClaw permissions are controlled by OpenClaw exec-policy, approvals, and sandbox config.",
            "This baseline describes the OpenClaw integration path, not a live OpenClaw tool inventory.",
            "Actual channels, tools, skills, and agent routing vary by installation.",
        ],
        "metadata": {
            "baseline_only": True,
            "live_tool_list": False,
            "routing_model": "gateway_agent_turn",
            "permission_enforcement": "executor_policy",
            "permission_note": (
                "Spice approval decides whether to hand off. OpenClaw exec-policy, "
                "approvals, and sandbox config decide what OpenClaw may do."
            ),
            "policy_commands": [
                "openclaw exec-policy show --json",
                "openclaw sandbox explain --json",
            ],
            "recommended_policy": {
                "read_only": "deny-all or an equivalent read-only allowlist",
                "workspace_write": "cautious",
                "danger_full_access": "yolo; Spice does not switch this automatically",
            },
        },
    },
    "sdep_subprocess": {
        "executor_id": "sdep_subprocess",
        "provider": "sdep_subprocess",
        "status": "unknown",
        "source": "static_baseline",
        "capability_ids": ["general_execution"],
        "permission_modes": ["read_only", "workspace_write", "danger_full_access"],
        "summary": "Generic SDEP subprocess executor; concrete capabilities depend on the agent.",
        "limitations": [
            _BASELINE_LIMITATION,
            "Use agent.describe when available for a live capability snapshot.",
        ],
        "metadata": {"baseline_only": True, "live_tool_list": False},
    },
}

_EXECUTOR_ID_ALIASES = {
    "claude": "claude_code",
    "claude-code": "claude_code",
    "claudecode": "claude_code",
    "dryrun": "dry_run",
    "open-claw": "openclaw",
    "open_claw": "openclaw",
    "sdep": "sdep_subprocess",
}


@dataclass(slots=True)
class ExecutorCapabilitySnapshot(PayloadRecord):
    executor_id: str
    provider: str = ""
    status: str = "unknown"
    source: str = "unavailable"
    capability_ids: list[str] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)
    permission_modes: list[str] = field(default_factory=list)
    summary: str = ""
    limitations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION

    def validate(self) -> None:
        if not str(self.executor_id or "").strip():
            raise ValueError("executor capability snapshot requires executor_id")
        if self.source not in CAPABILITY_SNAPSHOT_SOURCES:
            allowed = ", ".join(CAPABILITY_SNAPSHOT_SOURCES)
            raise ValueError(f"executor capability snapshot source must be one of [{allowed}]")
        if self.status not in CAPABILITY_SNAPSHOT_STATUSES:
            allowed = ", ".join(CAPABILITY_SNAPSHOT_STATUSES)
            raise ValueError(f"executor capability snapshot status must be one of [{allowed}]")
        self.capability_ids = _unique_strings(self.capability_ids)
        self.skill_ids = _unique_strings(self.skill_ids)
        self.permission_modes = _unique_strings(self.permission_modes)
        self.limitations = _unique_strings(self.limitations)
        self.metadata = _dict(self.metadata)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ExecutorCapabilitySnapshot":
        item = safe_dataclass_from_payload(cls, payload)
        item.capability_ids = _unique_strings(payload.get("capability_ids"))
        item.skill_ids = _unique_strings(payload.get("skill_ids"))
        item.permission_modes = _unique_strings(payload.get("permission_modes"))
        item.limitations = _unique_strings(payload.get("limitations"))
        item.metadata = _dict(payload.get("metadata"))
        item.validate()
        return item

    def compact_payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "executor_id": self.executor_id,
            "provider": self.provider,
            "status": self.status,
            "source": self.source,
            "capability_ids": list(self.capability_ids),
            "skill_ids": list(self.skill_ids),
            "permission_modes": list(self.permission_modes),
            "summary": self.summary,
            "limitations": list(self.limitations),
        }

    def has_capability(self, capability_id: str) -> bool:
        return str(capability_id or "").strip() in set(self.capability_ids)


def unavailable_executor_capability_snapshot(
    executor_id: str,
    *,
    provider: str = "",
    reason: str = "",
) -> ExecutorCapabilitySnapshot:
    limitations = [reason] if reason else ["Executor capability discovery is unavailable."]
    snapshot = ExecutorCapabilitySnapshot(
        executor_id=str(executor_id or "unknown"),
        provider=provider or str(executor_id or ""),
        status="unavailable",
        source="unavailable",
        limitations=limitations,
    )
    snapshot.validate()
    return snapshot


def static_executor_capability_snapshot(executor_id: str) -> ExecutorCapabilitySnapshot:
    normalized_executor_id = _normalize_executor_id(executor_id)
    payload = _STATIC_EXECUTOR_CAPABILITY_BASELINES.get(normalized_executor_id)
    if payload is None:
        requested = str(executor_id or "unknown").strip() or "unknown"
        return unavailable_executor_capability_snapshot(
            requested,
            provider=requested,
            reason="No static capability baseline is defined for this executor.",
        )
    return ExecutorCapabilitySnapshot.from_payload(dict(payload))


def static_executor_capability_snapshots() -> dict[str, ExecutorCapabilitySnapshot]:
    return {
        executor_id: static_executor_capability_snapshot(executor_id)
        for executor_id in sorted(_STATIC_EXECUTOR_CAPABILITY_BASELINES)
    }


def discover_executor_capability_snapshot(
    config: Any,
    *,
    timeout_seconds: float = 5.0,
) -> ExecutorCapabilitySnapshot:
    payload = _config_payload(config)
    raw_executor = str(payload.get("executor") or "").strip()
    if not raw_executor:
        return unavailable_executor_capability_snapshot(
            "unknown",
            reason="Executor is not configured.",
        )

    executor_id = _normalize_executor_id(raw_executor)
    if executor_id != "sdep_subprocess":
        return static_executor_capability_snapshot(executor_id)

    command = str(payload.get("executor_command") or "").strip()
    if not command:
        return _sdep_describe_fallback(
            executor_id,
            reason="SDEP describe skipped: missing executor_command.",
        )

    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return _sdep_describe_fallback(
            executor_id,
            reason=f"SDEP describe skipped: cannot parse executor_command: {exc}",
        )
    if not argv:
        return _sdep_describe_fallback(
            executor_id,
            reason="SDEP describe skipped: empty executor_command.",
        )

    request = build_sdep_describe_request(
        metadata={
            "runtime": "spice",
            "adapter": "discover_executor_capability_snapshot",
            "executor_id": executor_id,
        },
    )
    try:
        raw_response = SubprocessSDEPTransport(
            argv,
            timeout_seconds=timeout_seconds,
        ).describe(request)
        response = SDEPDescribeResponse.from_dict(raw_response)
    except Exception as exc:
        return _sdep_describe_fallback(
            executor_id,
            reason=f"SDEP describe failed: {exc}",
        )

    if response.status.strip().lower() not in {"success", "ok", "available"}:
        reason = f"SDEP describe returned status={response.status!r}."
        if response.error is not None and response.error.message:
            reason = f"{reason} {response.error.message}"
        return _sdep_describe_fallback(executor_id, reason=reason, raw_response=raw_response)

    return _snapshot_from_sdep_describe_response(
        executor_id=executor_id,
        response=response,
        raw_response=raw_response,
    )


def config_with_executor_capability_snapshot(
    config: Any,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    payload = _config_payload(config)
    current = payload.get("executor_capabilities")
    if isinstance(current, dict) and current:
        return payload
    payload["executor_capabilities"] = discover_executor_capability_snapshot(
        payload,
        timeout_seconds=timeout_seconds,
    ).compact_payload()
    return payload


def _normalize_executor_id(executor_id: str) -> str:
    text = str(executor_id or "").strip().lower().replace(" ", "_")
    if text.startswith("spice."):
        text = text.removeprefix("spice.")
    normalized = text.replace("-", "_")
    return _EXECUTOR_ID_ALIASES.get(text) or _EXECUTOR_ID_ALIASES.get(normalized) or normalized


def _snapshot_from_sdep_describe_response(
    *,
    executor_id: str,
    response: SDEPDescribeResponse,
    raw_response: dict[str, Any],
) -> ExecutorCapabilitySnapshot:
    capabilities = response.description.capabilities
    capability_ids = [capability.action_type for capability in capabilities]
    side_effect_classes = [
        capability.side_effect_class
        for capability in capabilities
        if capability.side_effect_class
    ]
    provider = (
        response.responder.implementation
        or response.responder.id
        or response.responder.name
        or executor_id
    )
    summary = response.description.summary or (
        f"SDEP agent.describe returned {len(capability_ids)} action capability"
        f"{'' if len(capability_ids) == 1 else 'ies'}."
    )
    snapshot = ExecutorCapabilitySnapshot(
        executor_id=executor_id,
        provider=provider,
        status="available",
        source="sdep_describe",
        capability_ids=capability_ids,
        permission_modes=_permission_modes_from_side_effects(side_effect_classes),
        summary=summary,
        limitations=["Dynamic SDEP snapshot from agent.describe; not a Spice static baseline."],
        metadata={
            "sdep_request_id": response.request_id,
            "responder": response.responder.to_dict(),
            "capability_version": response.description.capability_version,
            "side_effect_classes": _unique_strings(side_effect_classes),
            "raw_sdep_describe_response": raw_response,
        },
    )
    snapshot.validate()
    return snapshot


def _permission_modes_from_side_effects(side_effect_classes: list[str]) -> list[str]:
    values = set(side_effect_classes)
    if not values or values <= {"read_only"}:
        return ["read_only"]
    return ["read_only", "workspace_write", "danger_full_access"]


def _sdep_describe_fallback(
    executor_id: str,
    *,
    reason: str,
    raw_response: dict[str, Any] | None = None,
) -> ExecutorCapabilitySnapshot:
    snapshot = static_executor_capability_snapshot(executor_id)
    snapshot.limitations = _unique_strings([*snapshot.limitations, reason])
    snapshot.metadata = {
        **snapshot.metadata,
        "dynamic_discovery": {
            "attempted": True,
            "success": False,
            "reason": reason,
            "raw_sdep_describe_response": raw_response or {},
        },
    }
    snapshot.validate()
    return snapshot


def _config_payload(config: Any) -> dict[str, Any]:
    if hasattr(config, "to_payload") and callable(config.to_payload):
        payload = config.to_payload()
        return dict(payload) if isinstance(payload, dict) else {}
    return dict(config) if isinstance(config, dict) else {}


def _unique_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
