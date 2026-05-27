from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from spice.decision.general import (
    GenericObservation,
    ObservationConfidence,
    ObservationEvidence,
    ObservationKind,
    ObservationSource,
    ObservationSubject,
)
from spice.decision.general.types import payload_value
from spice.runtime.claude_code_provider import execute_claude_code_approval
from spice.runtime.codex_provider import execute_codex_approval
from spice.runtime.dry_run_executor import DryRunExecutionResult, execute_dry_run_approval
from spice.runtime.hermes_provider import execute_hermes_approval
from spice.runtime.openclaw_provider import execute_openclaw_approval
from spice.perception.providers.open_chronicle import OpenChroniclePerceptionProvider
from spice.perception.providers.poll import PollPerceptionProvider
from spice.runtime.sdep_subprocess_executor import (
    SDEPSubprocessExecutionResult,
    execute_sdep_subprocess_approval,
)
from spice.runtime.store import LocalJsonStore


@dataclass(frozen=True, slots=True)
class RuntimeProviderDescriptor:
    provider_id: str
    provider_type: str
    implementation: str
    status: str = "available"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return payload_value(self)


class PerceptionProvider(Protocol):
    provider_id: str

    def descriptor(self) -> RuntimeProviderDescriptor:
        ...

    def collect_observations(
        self,
        intent: str,
        *,
        config: dict[str, Any],
        now: datetime,
    ) -> list[GenericObservation]:
        ...


class StoreProvider(Protocol):
    provider_id: str

    def descriptor(self) -> RuntimeProviderDescriptor:
        ...

    def store(self, project_root: str | Path = ".") -> LocalJsonStore:
        ...


class ExecutorProvider(Protocol):
    provider_id: str

    def descriptor(self) -> RuntimeProviderDescriptor:
        ...

    def execute_approval(
        self,
        approval_id: str,
        *,
        project_root: str | Path = ".",
        now: datetime | None = None,
    ) -> DryRunExecutionResult:
        ...


@dataclass(frozen=True, slots=True)
class ManualInputProvider:
    provider_id: str = "manual"

    def descriptor(self) -> RuntimeProviderDescriptor:
        return RuntimeProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="perception",
            implementation="spice.runtime.providers.ManualInputProvider",
            metadata={
                "input": "manual_intent",
                "output": "GenericObservation[]",
                "external_calls": False,
            },
        )

    def collect_observations(
        self,
        intent: str,
        *,
        config: dict[str, Any],
        now: datetime,
    ) -> list[GenericObservation]:
        text = intent.strip()
        if not text:
            raise ValueError("ManualInputProvider requires a non-empty intent.")
        slug = _hash(text)[:12]
        intent_id = f"intent.manual.{slug}"
        observations = [
            GenericObservation(
                observation_id=f"obs.manual.intent.{slug}",
                kind=ObservationKind.INTENT,
                source=ObservationSource(
                    provider=self.provider_id,
                    channel="cli",
                    actor="user",
                    received_at=_timestamp(now),
                ),
                subject=ObservationSubject(
                    subject_id=intent_id,
                    subject_type="intent",
                    title=text[:80],
                    refs=[intent_id],
                ),
                summary=text,
                attributes={
                    "intent_id": intent_id,
                    "desired_outcome": text,
                    "original_text": text,
                    "urgency": "unknown",
                    "status": "active",
                    "target_refs": [intent_id],
                },
                evidence=[
                    ObservationEvidence(
                        evidence_id=f"evidence.manual.intent.{slug}",
                        kind="user_text",
                        summary="Original manual user intent.",
                        content=text,
                    )
                ],
                confidence=ObservationConfidence(score=0.75, level="medium"),
                metadata={"source": "spice run --once", "original_text": text},
            )
        ]
        observations.extend(_manual_context_hint_observations(text, slug=slug, now=now))
        executor = str(config.get("executor") or "dry_run")
        if executor:
            observations.append(
                GenericObservation(
                    observation_id=f"obs.manual.capability.{_hash(executor)[:12]}",
                    kind=ObservationKind.CAPABILITY,
                    source=ObservationSource(
                        provider="setup_config",
                        channel="local_config",
                        received_at=_timestamp(now),
                    ),
                    subject=ObservationSubject(
                        subject_id=f"capability.executor.{_safe_slug(executor)}",
                        subject_type="executor_capability",
                        title=f"{executor} executor capability",
                    ),
                    summary=f"Configured executor capability is available: {executor}.",
                    attributes={
                        "capability_id": f"capability.executor.{_safe_slug(executor)}",
                        "provider": executor,
                        "scope": "general",
                        "status": "available",
                        "requires_confirmation": True,
                        "side_effects": ["execute"] if executor != "dry_run" else [],
                    },
                    confidence=ObservationConfidence(score=0.70, level="medium"),
                    metadata={"source": "spice config"},
                )
            )
        if str(config.get("permission_mode") or "") == "confirm_before_execution":
            observations.append(
                GenericObservation(
                    observation_id=f"obs.manual.constraint.approval.{slug}",
                    kind=ObservationKind.CONSTRAINT,
                    source=ObservationSource(
                        provider="setup_config",
                        channel="local_config",
                        received_at=_timestamp(now),
                    ),
                    subject=ObservationSubject(
                        subject_id=f"constraint.approval.{slug}",
                        subject_type="approval_boundary",
                        refs=[intent_id],
                    ),
                    summary="Execution requires approval before crossing the execution boundary.",
                    attributes={
                        "constraint_id": f"constraint.approval.{slug}",
                        "constraint_kind": "approval_boundary",
                        "description": "Confirm before execution.",
                        "severity": "medium",
                        "target_refs": [intent_id],
                        "status": "active",
                    },
                    confidence=ObservationConfidence(score=1.0, level="high"),
                    metadata={"source": "spice config"},
                )
            )
        return observations


@dataclass(frozen=True, slots=True)
class LocalJsonStoreProvider:
    provider_id: str = "local_json"

    def descriptor(self) -> RuntimeProviderDescriptor:
        return RuntimeProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="store",
            implementation="spice.runtime.providers.LocalJsonStoreProvider",
            metadata={
                "storage": "workspace_json_files",
                "external_calls": False,
            },
        )

    def store(self, project_root: str | Path = ".") -> LocalJsonStore:
        return LocalJsonStore.from_project_root(project_root)


@dataclass(frozen=True, slots=True)
class DryRunExecutorProvider:
    provider_id: str = "dry_run"

    def descriptor(self) -> RuntimeProviderDescriptor:
        return RuntimeProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="executor",
            implementation="spice.runtime.providers.DryRunExecutorProvider",
            metadata={
                "input": "approved approval_id",
                "output": "local SDEP execute.response + OutcomeRecord",
                "real_executor_called": False,
                "sdep_request_sent": False,
            },
        )

    def execute_approval(
        self,
        approval_id: str,
        *,
        project_root: str | Path = ".",
        now: datetime | None = None,
    ) -> DryRunExecutionResult:
        return execute_dry_run_approval(
            approval_id,
            project_root=project_root,
            now=now,
        )


@dataclass(frozen=True, slots=True)
class SDEPSubprocessExecutorProvider:
    provider_id: str = "sdep_subprocess"

    def descriptor(self) -> RuntimeProviderDescriptor:
        return RuntimeProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="executor",
            implementation="spice.runtime.providers.SDEPSubprocessExecutorProvider",
            metadata={
                "input": "approved approval_id + planned SDEP execute.request",
                "output": "SDEP execute.response + OutcomeRecord",
                "transport": "local_subprocess",
                "shell": False,
                "real_executor_called": False,
            },
        )

    def execute_approval(
        self,
        approval_id: str,
        *,
        command: str | list[str],
        project_root: str | Path = ".",
        timeout_seconds: int = 120,
        now: datetime | None = None,
    ) -> SDEPSubprocessExecutionResult:
        return execute_sdep_subprocess_approval(
            approval_id,
            command=command,
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            now=now,
        )


@dataclass(frozen=True, slots=True)
class CodexExecutorProvider:
    provider_id: str = "codex"

    def descriptor(self) -> RuntimeProviderDescriptor:
        return RuntimeProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="executor",
            implementation="spice.runtime.providers.CodexExecutorProvider",
            metadata={
                "input": "approved approval_id + planned SDEP execute.request",
                "output": "SDEP execute.response + OutcomeRecord",
                "transport": "local_subprocess",
                "executor": "codex",
                "shell": False,
                "real_executor_called": True,
            },
        )

    def execute_approval(
        self,
        approval_id: str,
        *,
        command: str | list[str] = "codex",
        project_root: str | Path = ".",
        timeout_seconds: int = 600,
        now: datetime | None = None,
    ) -> SDEPSubprocessExecutionResult:
        return execute_codex_approval(
            approval_id,
            command=command,
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            now=now,
        )


@dataclass(frozen=True, slots=True)
class ClaudeCodeExecutorProvider:
    provider_id: str = "claude_code"

    def descriptor(self) -> RuntimeProviderDescriptor:
        return RuntimeProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="executor",
            implementation="spice.runtime.providers.ClaudeCodeExecutorProvider",
            metadata={
                "input": "approved approval_id + planned SDEP execute.request",
                "output": "SDEP execute.response + OutcomeRecord",
                "transport": "local_subprocess",
                "executor": "claude_code",
                "shell": False,
                "real_executor_called": True,
            },
        )

    def execute_approval(
        self,
        approval_id: str,
        *,
        command: str | list[str] = "claude",
        project_root: str | Path = ".",
        timeout_seconds: int = 600,
        now: datetime | None = None,
    ) -> SDEPSubprocessExecutionResult:
        return execute_claude_code_approval(
            approval_id,
            command=command,
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            now=now,
        )


@dataclass(frozen=True, slots=True)
class HermesExecutorProvider:
    provider_id: str = "hermes"

    def descriptor(self) -> RuntimeProviderDescriptor:
        return RuntimeProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="executor",
            implementation="spice.runtime.providers.HermesExecutorProvider",
            metadata={
                "input": "approved approval_id + planned SDEP execute.request",
                "output": "SDEP execute.response + OutcomeRecord",
                "transport": "local_subprocess",
                "executor": "hermes",
                "shell": False,
                "real_executor_called": True,
            },
        )

    def execute_approval(
        self,
        approval_id: str,
        *,
        command: str | list[str] = "hermes chat -Q",
        project_root: str | Path = ".",
        timeout_seconds: int = 600,
        now: datetime | None = None,
    ) -> SDEPSubprocessExecutionResult:
        return execute_hermes_approval(
            approval_id,
            command=command,
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            now=now,
        )


@dataclass(frozen=True, slots=True)
class OpenClawExecutorProvider:
    provider_id: str = "openclaw"

    def descriptor(self) -> RuntimeProviderDescriptor:
        return RuntimeProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="executor",
            implementation="spice.runtime.providers.OpenClawExecutorProvider",
            metadata={
                "input": "approved approval_id + planned SDEP execute.request",
                "output": "SDEP execute.response + OutcomeRecord",
                "transport": "local_subprocess",
                "executor": "openclaw",
                "shell": False,
                "real_executor_called": True,
                "permission_enforcement": "executor_policy",
                "policy_commands": [
                    "openclaw exec-policy show --json",
                    "openclaw sandbox explain --json",
                ],
                "permission_note": "Spice does not mutate OpenClaw policy; configure OpenClaw exec-policy before handoff.",
            },
        )

    def execute_approval(
        self,
        approval_id: str,
        *,
        command: str | list[str] = "openclaw agent --json --message",
        project_root: str | Path = ".",
        timeout_seconds: int = 600,
        now: datetime | None = None,
    ) -> SDEPSubprocessExecutionResult:
        return execute_openclaw_approval(
            approval_id,
            command=command,
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            now=now,
        )


def default_runtime_provider_descriptors() -> dict[str, dict[str, Any]]:
    return {
        "perception": ManualInputProvider().descriptor().to_payload(),
        "poll_perception": RuntimeProviderDescriptor(
            provider_id=PollPerceptionProvider.provider_id,
            provider_type="perception",
            implementation="spice.perception.providers.poll.PollPerceptionProvider",
            metadata={
                "input": "url or command poll source",
                "output": "GenericObservation[]",
                "external_calls": True,
                "command_poll_requires_opt_in": True,
            },
        ).to_payload(),
        "open_chronicle_perception": RuntimeProviderDescriptor(
            provider_id=OpenChroniclePerceptionProvider.provider_id,
            provider_type="perception",
            implementation="spice.perception.providers.open_chronicle.OpenChroniclePerceptionProvider",
            metadata={
                "input": "Open Chronicle MCP current_context and recent_activity",
                "output": "GenericObservation[]",
                "external_calls": True,
                "trigger_capable": True,
            },
        ).to_payload(),
        "store": LocalJsonStoreProvider().descriptor().to_payload(),
        "executor": DryRunExecutorProvider().descriptor().to_payload(),
        "sdep_subprocess_executor": SDEPSubprocessExecutorProvider().descriptor().to_payload(),
        "codex_executor": CodexExecutorProvider().descriptor().to_payload(),
        "claude_code_executor": ClaudeCodeExecutorProvider().descriptor().to_payload(),
        "hermes_executor": HermesExecutorProvider().descriptor().to_payload(),
        "openclaw_executor": OpenClawExecutorProvider().descriptor().to_payload(),
    }


def _manual_context_hint_observations(
    text: str,
    *,
    slug: str,
    now: datetime,
) -> list[GenericObservation]:
    lowered = text.lower()
    observations: list[GenericObservation] = []

    if "failing test" in lowered or "failing tests" in lowered:
        observations.append(
            _manual_work_item_observation(
                slug=f"{slug}.failing_test",
                now=now,
                title="Fix failing test",
                summary="A failing test is blocking progress and needs attention.",
                urgency="high",
                estimate_minutes=20,
                blocker_refs=["ci"],
                original_text=text,
            )
        )

    if "pending pr" in lowered or "pr review" in lowered or "pull request" in lowered:
        observations.append(
            _manual_work_item_observation(
                slug=f"{slug}.pr_review",
                now=now,
                title="Review pending PR",
                summary="A pending pull request review is waiting for attention.",
                urgency="medium",
                estimate_minutes=30,
                original_text=text,
            )
        )

    meeting_minutes = _extract_meeting_minutes(lowered)
    if meeting_minutes is not None:
        meeting_slug = _hash(f"{slug}.meeting")[:12]
        start = now + timedelta(minutes=meeting_minutes)
        end = start + timedelta(minutes=30)
        observations.append(
            GenericObservation(
                observation_id=f"obs.manual.commitment.{meeting_slug}",
                kind=ObservationKind.COMMITMENT,
                source=ObservationSource(
                    provider="manual",
                    channel="cli_hint",
                    actor="user",
                    received_at=_timestamp(now),
                ),
                subject=ObservationSubject(
                    subject_id=f"commitment.manual.meeting.{slug}",
                    subject_type="commitment",
                    title=f"Meeting in {meeting_minutes} minutes",
                ),
                summary=f"Meeting starts in {meeting_minutes} minutes.",
                attributes={
                    "commitment_id": f"commitment.manual.meeting.{slug}",
                    "title": f"Meeting in {meeting_minutes} minutes",
                    "start_at": _timestamp(start),
                    "end_at": _timestamp(end),
                    "prep_start_at": _timestamp(max(now, start - timedelta(minutes=10))),
                    "fixed": True,
                    "priority": "normal",
                    "status": "active",
                },
                evidence=[
                    ObservationEvidence(
                        evidence_id=f"evidence.manual.commitment.{meeting_slug}",
                        kind="user_text",
                        summary="Meeting timing mentioned in manual intent.",
                        content=text,
                    )
                ],
                confidence=ObservationConfidence(score=0.75, level="medium"),
                metadata={
                    "source": "manual_context_hint",
                    "original_text": text,
                    "hint": "meeting_window",
                },
            )
        )

    return observations


def _manual_work_item_observation(
    *,
    slug: str,
    now: datetime,
    title: str,
    summary: str,
    urgency: str,
    estimate_minutes: int,
    original_text: str,
    blocker_refs: list[str] | None = None,
) -> GenericObservation:
    item_slug = _safe_slug(slug)
    item_id = f"work.manual.{item_slug}"
    evidence_id = f"evidence.manual.work_item.{_hash(slug)[:12]}"
    return GenericObservation(
        observation_id=f"obs.manual.work_item.{_hash(slug)[:12]}",
        kind=ObservationKind.WORK_ITEM,
        source=ObservationSource(
            provider="manual",
            channel="cli_hint",
            actor="user",
            received_at=_timestamp(now),
        ),
        subject=ObservationSubject(
            subject_id=item_id,
            subject_type="work_item",
            title=title,
        ),
        summary=summary,
        attributes={
            "work_item_id": item_id,
            "title": title,
            "status": "open",
            "urgency": urgency,
            "estimate_minutes": estimate_minutes,
            "blocker_refs": list(blocker_refs or []),
        },
        evidence=[
            ObservationEvidence(
                evidence_id=evidence_id,
                kind="user_text",
                summary="Work item mentioned in manual intent.",
                content=original_text,
            )
        ],
        confidence=ObservationConfidence(score=0.72, level="medium"),
        metadata={
            "source": "manual_context_hint",
            "original_text": original_text,
        },
    )


def _extract_meeting_minutes(lowered_text: str) -> int | None:
    if "meeting" not in lowered_text:
        return None
    for number in range(1, 181):
        if (
            f"in {number} minutes" in lowered_text
            or f"in {number} minute" in lowered_text
            or f"in {number} mins" in lowered_text
            or f"in {number} min" in lowered_text
        ):
            return number
    return 45 if "meeting soon" in lowered_text else None


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _hash(value: Any) -> str:
    return sha256(json.dumps(payload_value(value), sort_keys=True).encode("utf-8")).hexdigest()


def _safe_slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_") or "unknown"
