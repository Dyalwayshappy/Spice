from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from spice_hermes_bridge.extraction.commitments import (
    extract_commitment_proposal,
    has_precise_time_evidence,
    looks_like_commitment_candidate,
)
from spice_hermes_bridge.extraction.llm import (
    CommitmentProposalProvider,
    provider_from_environment,
)
from spice_hermes_bridge.extraction.proposals import CommitmentProposal
from spice_hermes_bridge.observations import (
    ObservationValidationIssue,
    StructuredObservation,
    build_observation,
    validate_observation,
)
from spice_hermes_bridge.storage.pending import (
    DEFAULT_PENDING_STORE,
    PendingConfirmation,
    append_pending_confirmation,
    build_followup_record,
    build_pending_confirmation,
    find_active_pending,
    find_resolved_pending_for_followup,
    hash_followup_text,
    hash_resolution_input,
    mark_pending_resolved,
    update_pending_still_pending,
)


_HERMES_RESPONSE_PREFIXES = (
    "⚕ Hermes Agent",
    "⚕ *Hermes Agent*",
    "Hermes Agent",
)
_OBSERVATION_CONFIDENCE_THRESHOLD = 0.70
_EXTRACTOR_MODES = {"deterministic", "llm_assisted"}


@dataclass(frozen=True, slots=True)
class WhatsAppInboundMessage:
    text: str
    chat_id: str | None = None
    sender_id: str | None = None
    message_id: str | None = None
    received_at: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WhatsAppInboundMessage:
        text = _first_string(payload, "text", "message", "body", "content")
        return cls(
            text=text or "",
            chat_id=_first_string(payload, "chat_id", "chatId", "thread_id", "threadId"),
            sender_id=_first_string(payload, "sender_id", "senderId", "from", "author"),
            message_id=_first_string(payload, "message_id", "messageId", "id"),
            received_at=_first_string(payload, "received_at", "receivedAt", "timestamp"),
        )


@dataclass(frozen=True, slots=True)
class WhatsAppIngressResult:
    result_type: str
    reason: str | None = None
    observation: StructuredObservation | None = None
    pending_confirmation: PendingConfirmation | None = None
    issues: tuple[ObservationValidationIssue, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if self.result_type == "observation":
            return "observation_built"
        return self.result_type

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_type": self.result_type,
            "status": self.status,
            "reason": self.reason,
            "valid": self.valid,
            "observation": self.observation.to_dict() if self.observation else None,
            "pending_confirmation": (
                self.pending_confirmation.to_dict()
                if self.pending_confirmation
                else None
            ),
            "warnings": list(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def observe_whatsapp_message(
    message: WhatsAppInboundMessage,
    *,
    default_timezone: str = "Asia/Shanghai",
    extractor: str = "deterministic",
    llm_provider: CommitmentProposalProvider | None = None,
    pending_store_path: Path | None = DEFAULT_PENDING_STORE,
    persist_pending: bool = True,
    resolve_pending: bool = False,
) -> WhatsAppIngressResult:
    """Build and validate observations from WhatsApp text without state decisions."""

    if extractor not in _EXTRACTOR_MODES:
        raise ValueError("extractor must be deterministic or llm_assisted")

    if resolve_pending and pending_store_path is not None:
        pending = find_active_pending(
            path=pending_store_path,
            chat_id=message.chat_id,
            source="whatsapp",
        )
        if pending is not None:
            return _resolve_pending_confirmation(
                pending,
                message,
                default_timezone=default_timezone,
                extractor=extractor,
                llm_provider=llm_provider,
                pending_store_path=pending_store_path,
            )

        resolved = find_resolved_pending_for_followup(
            followup_hash=hash_followup_text(message.text),
            path=pending_store_path,
            chat_id=message.chat_id,
            source="whatsapp",
        )
        if resolved is not None:
            return WhatsAppIngressResult(
                result_type="ignored",
                reason="pending_already_resolved_for_followup",
                warnings=(f"resolved_pending_id={resolved.pending_id}",),
            )

    ignored_reason = _filter_message(message)
    if ignored_reason:
        return WhatsAppIngressResult(result_type="ignored", reason=ignored_reason)

    if not looks_like_commitment_candidate(message.text):
        return WhatsAppIngressResult(
            result_type="ignored",
            reason="no_supported_commitment_pattern",
        )

    reference_time = _parse_reference_time(message.received_at)
    extraction = _extract_proposal(
        message,
        extractor=extractor,
        llm_provider=llm_provider,
        reference_time=reference_time.value,
        default_timezone=default_timezone,
    )
    warnings = reference_time.warnings + extraction.warnings
    proposal = extraction.proposal
    if proposal is None:
        return WhatsAppIngressResult(
            result_type="ignored",
            reason="no_supported_commitment_pattern",
            warnings=warnings,
        )

    proposal = proposal.with_duration_from_end_time()
    gating = _gate_commitment_proposal(proposal, original_text=message.text)
    if gating.missing_fields or gating.reason:
        pending = build_pending_confirmation(
            original_text=message.text,
            missing_fields=gating.missing_fields,
            uncertain_fields=proposal.meta.uncertain_fields,
            assumptions=proposal.meta.assumptions,
            provenance=_base_provenance(
                message,
                extractor=proposal.extractor,
                extractor_mode=extractor,
                proposal=proposal,
                time_anchor_source=reference_time.source,
                default_timezone=default_timezone,
                fallback_reason=extraction.fallback_reason,
                extra={"gating_reason": gating.reason},
            ),
        )
        if persist_pending and pending_store_path is not None:
            append_pending_confirmation(pending, path=pending_store_path)
        return WhatsAppIngressResult(
            result_type="pending_confirmation",
            reason=gating.reason,
            pending_confirmation=pending,
            warnings=warnings + gating.warnings,
        )

    attributes = _commitment_attributes(proposal)
    observation = build_observation(
        observation_type="commitment_declared",
        source="whatsapp",
        confidence=proposal.meta.confidence,
        attributes=attributes,
        provenance=_base_provenance(
            message,
            extractor=proposal.extractor,
            extractor_mode=extractor,
            proposal=proposal,
            time_anchor_source=reference_time.source,
            default_timezone=default_timezone,
            fallback_reason=extraction.fallback_reason,
        ),
    )
    issues = tuple(validate_observation(observation))
    if any(issue.severity == "error" for issue in issues):
        pending = build_pending_confirmation(
            original_text=message.text,
            missing_fields=tuple(issue.field for issue in issues if issue.severity == "error"),
            uncertain_fields=proposal.meta.uncertain_fields,
            assumptions=proposal.meta.assumptions,
            provenance=_base_provenance(
                message,
                extractor=proposal.extractor,
                extractor_mode=extractor,
                proposal=proposal,
                time_anchor_source=reference_time.source,
                default_timezone=default_timezone,
                fallback_reason=extraction.fallback_reason,
                extra={"gating_reason": "schema_validation_failed"},
            ),
        )
        if persist_pending and pending_store_path is not None:
            append_pending_confirmation(pending, path=pending_store_path)
        return WhatsAppIngressResult(
            result_type="pending_confirmation",
            reason="schema_validation_failed",
            pending_confirmation=pending,
            issues=issues,
            warnings=warnings,
        )

    return WhatsAppIngressResult(
        result_type="observation",
        observation=observation,
        issues=issues,
        warnings=warnings + gating.warnings,
    )


def _resolve_pending_confirmation(
    pending: PendingConfirmation,
    followup_message: WhatsAppInboundMessage,
    *,
    default_timezone: str,
    extractor: str,
    llm_provider: CommitmentProposalProvider | None,
    pending_store_path: Path,
) -> WhatsAppIngressResult:
    followup = build_followup_record(
        text=followup_message.text,
        message_id=followup_message.message_id,
        received_at=followup_message.received_at,
    )
    resolution_hash = hash_resolution_input(pending.original_text, followup_message.text)
    merged_text = f"{pending.original_text}\n{followup_message.text}"
    anchor_received_at = _optional_string(pending.provenance.get("received_at"))

    merged_message = WhatsAppInboundMessage(
        text=merged_text,
        chat_id=followup_message.chat_id or _optional_string(pending.provenance.get("chat_id")),
        sender_id=(
            followup_message.sender_id
            or _optional_string(pending.provenance.get("sender_id"))
        ),
        message_id=followup_message.message_id,
        received_at=anchor_received_at or followup_message.received_at,
    )

    result = observe_whatsapp_message(
        merged_message,
        default_timezone=default_timezone,
        extractor=extractor,
        llm_provider=llm_provider,
        pending_store_path=pending_store_path,
        persist_pending=False,
        resolve_pending=False,
    )

    if result.observation is not None:
        resolved = mark_pending_resolved(
            pending_id=pending.pending_id,
            followup=followup,
            resolved_input_hash=resolution_hash,
            path=pending_store_path,
        )
        result.observation.provenance.update(
            {
                "pending_resolution": True,
                "pending_id": resolved.pending_id,
                "resolved_input_hash": resolution_hash,
                "original_text_sha256": hashlib.sha256(
                    pending.original_text.encode("utf-8")
                ).hexdigest(),
                "followup_text_sha256": followup["input_hash"],
            }
        )
        return WhatsAppIngressResult(
            result_type="observation",
            observation=result.observation,
            issues=result.issues,
            warnings=result.warnings + (f"resolved_pending_id={resolved.pending_id}",),
        )

    missing_fields = pending.missing_fields
    uncertain_fields = pending.uncertain_fields
    assumptions = pending.assumptions
    reason = result.reason or "pending_followup_did_not_resolve"
    if result.pending_confirmation is not None:
        missing_fields = result.pending_confirmation.missing_fields
        uncertain_fields = result.pending_confirmation.uncertain_fields
        assumptions = result.pending_confirmation.assumptions

    updated = update_pending_still_pending(
        pending_id=pending.pending_id,
        followup=followup,
        missing_fields=missing_fields,
        uncertain_fields=uncertain_fields,
        assumptions=assumptions,
        path=pending_store_path,
    )
    return WhatsAppIngressResult(
        result_type="pending_confirmation",
        reason=reason,
        pending_confirmation=updated,
        issues=result.issues,
        warnings=result.warnings + ("pending_followup_recorded",),
    )


def _filter_message(message: WhatsAppInboundMessage) -> str | None:
    text = message.text.strip()
    if not text:
        return "empty_message"
    if text.startswith("/"):
        return "command_message"
    if any(text.startswith(prefix) for prefix in _HERMES_RESPONSE_PREFIXES):
        return "hermes_response"
    return None


@dataclass(frozen=True, slots=True)
class _ReferenceTime:
    value: datetime | None
    source: str
    warnings: tuple[str, ...] = ()


def _parse_reference_time(value: str | None) -> _ReferenceTime:
    if not value:
        return _ReferenceTime(value=None, source="system_now")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _ReferenceTime(
            value=None,
            source="system_now",
            warnings=("invalid_received_at_used_system_now",),
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return _ReferenceTime(
            value=None,
            source="system_now",
            warnings=("naive_received_at_ignored_used_system_now",),
        )
    return _ReferenceTime(value=parsed, source="received_at")


@dataclass(frozen=True, slots=True)
class _GatingResult:
    reason: str | None = None
    missing_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _ProposalExtraction:
    proposal: CommitmentProposal | None
    warnings: tuple[str, ...] = ()
    fallback_reason: str | None = None


def _extract_proposal(
    message: WhatsAppInboundMessage,
    *,
    extractor: str,
    llm_provider: CommitmentProposalProvider | None,
    reference_time: datetime | None,
    default_timezone: str,
) -> _ProposalExtraction:
    if extractor == "deterministic":
        return _ProposalExtraction(
            extract_commitment_proposal(
                message.text,
                reference_time=reference_time,
                default_timezone=default_timezone,
            ),
        )

    provider = llm_provider or provider_from_environment()
    if provider is not None:
        try:
            proposal = provider.propose_commitment(
                text=message.text,
                reference_time=reference_time,
                default_timezone=default_timezone,
            )
            if proposal is not None:
                return _ProposalExtraction(proposal)
        except Exception as exc:  # noqa: BLE001 - boundary must not crash on provider failure
            fallback = extract_commitment_proposal(
                message.text,
                reference_time=reference_time,
                default_timezone=default_timezone,
            )
            reason = f"llm_assisted_failed_fell_back_to_deterministic: {exc}"
            return _ProposalExtraction(
                proposal=fallback,
                warnings=(reason,),
                fallback_reason=reason,
            )

        fallback = extract_commitment_proposal(
            message.text,
            reference_time=reference_time,
            default_timezone=default_timezone,
        )
        reason = "llm_assisted_returned_no_proposal_fell_back_to_deterministic"
        return _ProposalExtraction(
            proposal=fallback,
            warnings=(reason,),
            fallback_reason=reason,
        )

    fallback = extract_commitment_proposal(
        message.text,
        reference_time=reference_time,
        default_timezone=default_timezone,
    )
    reason = "llm_assisted_provider_not_configured_fell_back_to_deterministic"
    return _ProposalExtraction(
        proposal=fallback,
        warnings=(reason,),
        fallback_reason=reason,
    )


def _gate_commitment_proposal(
    proposal: CommitmentProposal,
    *,
    original_text: str,
) -> _GatingResult:
    missing: list[str] = []
    warnings: list[str] = []

    if not proposal.summary:
        missing.append("summary")
    if not proposal.start_time:
        missing.append("start_time")
    elif not has_precise_time_evidence(original_text):
        return _GatingResult(
            reason="proposal_start_time_not_supported_by_text",
            missing_fields=("start_time",),
            warnings=tuple(warnings),
        )
    if proposal.duration_minutes is None and not proposal.end_time:
        missing.extend(("duration_minutes", "end_time"))
    if proposal.meta.uncertain_fields:
        missing.extend(proposal.meta.uncertain_fields)
    if proposal.meta.assumptions:
        return _GatingResult(
            reason="proposal_has_key_assumptions",
            missing_fields=tuple(dict.fromkeys(missing)),
            warnings=tuple(warnings),
        )
    if proposal.meta.needs_confirmation:
        return _GatingResult(
            reason="proposal_needs_confirmation",
            missing_fields=tuple(dict.fromkeys(missing)),
            warnings=tuple(warnings),
        )
    if proposal.meta.confidence < _OBSERVATION_CONFIDENCE_THRESHOLD:
        return _GatingResult(
            reason="proposal_confidence_below_threshold",
            missing_fields=tuple(dict.fromkeys(missing or ("confidence",))),
            warnings=tuple(warnings),
        )
    if missing:
        return _GatingResult(
            reason="proposal_missing_required_fields",
            missing_fields=tuple(dict.fromkeys(missing)),
            warnings=tuple(warnings),
        )
    if proposal.duration_source == "default_safe":
        warnings.append("duration_defaulted_to_60_minutes_for_bounded_commitment")
    return _GatingResult(warnings=tuple(warnings))


def _commitment_attributes(proposal: CommitmentProposal) -> dict[str, Any]:
    assert proposal.summary is not None
    assert proposal.start_time is not None

    duration_minutes = proposal.duration_minutes
    end_time = proposal.end_time
    if duration_minutes is None and end_time is not None:
        duration_minutes = proposal.with_duration_from_end_time().duration_minutes
    if end_time is None and duration_minutes is not None:
        start = datetime.fromisoformat(proposal.start_time.replace("Z", "+00:00"))
        end_time = (start + timedelta(minutes=duration_minutes)).isoformat()

    attributes: dict[str, Any] = {
        "summary": proposal.summary,
        "start_time": proposal.start_time,
        "end_time": end_time,
        "duration_minutes": duration_minutes,
    }
    if proposal.prep_start_time:
        attributes["prep_start_time"] = proposal.prep_start_time
    if proposal.priority_hint:
        attributes["priority_hint"] = proposal.priority_hint
    if proposal.flexibility_hint:
        attributes["flexibility_hint"] = proposal.flexibility_hint
    if proposal.constraint_hints:
        attributes["constraint_hints"] = list(proposal.constraint_hints)
    return attributes


def _base_provenance(
    message: WhatsAppInboundMessage,
    *,
    extractor: str,
    extractor_mode: str,
    proposal: CommitmentProposal,
    time_anchor_source: str,
    default_timezone: str,
    fallback_reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = {
        "adapter": "whatsapp_perception.v2",
        "platform": "whatsapp",
        "chat_id": message.chat_id,
        "sender_id": message.sender_id,
        "message_id": message.message_id,
        "received_at": message.received_at,
        "extractor": extractor,
        "extractor_mode": extractor_mode,
        "fallback": fallback_reason is not None,
        "fallback_reason": fallback_reason,
        "time_anchor_source": time_anchor_source,
        "default_timezone": default_timezone,
        "duration_source": proposal.duration_source,
        "matched_terms": list(proposal.matched_terms),
        "proposal_meta": proposal.meta.to_dict(),
        "text_sha256": hashlib.sha256(message.text.encode("utf-8")).hexdigest(),
    }
    if extra:
        provenance.update(extra)
    return provenance




def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
