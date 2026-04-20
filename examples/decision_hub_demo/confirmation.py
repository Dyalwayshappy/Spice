from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from spice.protocols.world_state import WorldState

from examples.decision_hub_demo.execution_adapter import (
    ExecutionFeedbackAdapter,
    ExecutionFeedbackResult,
)
from examples.decision_hub_demo.ids import make_confirmation_id, timestamp_segment
from examples.decision_hub_demo.state import utc_now
from examples.decision_hub_demo.trace import get_trace

ConfirmationChoice = Literal["confirm", "reject", "details"]


@dataclass(slots=True)
class ConfirmationRequest:
    confirmation_id: str
    decision_id: str
    selected_action: str
    acted_on: str | None
    human_summary: str
    reason_summary: list[str]
    options: list[dict[str, str]]
    created_at: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConfirmationRecord:
    confirmation_id: str
    decision_id: str
    selected_action: str
    status: str
    created_at: str
    resolved_at: str | None
    request: dict[str, Any]
    recommendation: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConfirmationResolution:
    status: str
    choice: str
    confirmation_id: str
    confirmation_request: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    details: dict[str, Any] | None = None
    state_updated: bool = False
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ControlLoopResult:
    status: str
    recommendation: dict[str, Any]
    confirmation_request: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    ask_user: dict[str, Any] | None = None
    state_updated: bool = False
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryConfirmationStore:
    """Small demo registry for pending decision confirmations."""

    def __init__(self) -> None:
        self._records: dict[str, ConfirmationRecord] = {}

    def put(self, request: ConfirmationRequest, recommendation: dict[str, Any]) -> ConfirmationRecord:
        record = ConfirmationRecord(
            confirmation_id=request.confirmation_id,
            decision_id=request.decision_id,
            selected_action=request.selected_action,
            status="pending",
            created_at=request.created_at,
            resolved_at=None,
            request=request.to_payload(),
            recommendation=dict(recommendation),
        )
        self._records[request.confirmation_id] = record
        return record

    def get(self, confirmation_id: str) -> ConfirmationRecord | None:
        return self._records.get(confirmation_id)

    def resolve(self, confirmation_id: str, *, status: str, now: datetime | None = None) -> ConfirmationRecord:
        record = self._records[confirmation_id]
        record.status = status
        record.resolved_at = timestamp_segment(now or utc_now())
        return record

    def to_payload(self) -> dict[str, Any]:
        return {key: value.to_payload() for key, value in self._records.items()}


class DecisionControlLoop:
    """Minimal confirmation/execution loop for demo recommendations."""

    def __init__(
        self,
        *,
        confirmation_store: InMemoryConfirmationStore | None = None,
        execution_adapter: ExecutionFeedbackAdapter | None = None,
    ) -> None:
        self.confirmation_store = confirmation_store or InMemoryConfirmationStore()
        self.execution_adapter = execution_adapter or ExecutionFeedbackAdapter()

    def handle_recommendation(
        self,
        state: WorldState,
        recommendation: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> ControlLoopResult:
        action = str(recommendation.get("selected_action") or "")
        if action == "ask_user":
            return ControlLoopResult(
                status="ask_user",
                recommendation=recommendation,
                ask_user={
                    "decision_id": recommendation.get("decision_id"),
                    "acted_on": recommendation.get("acted_on"),
                    "message": recommendation.get("human_summary"),
                    "reason_summary": list(recommendation.get("reason_summary", [])),
                    "trace_ref": recommendation.get("trace_ref"),
                },
                reason="ask_user requests information and does not enter execution",
            )
        if action == "ignore_temporarily":
            return ControlLoopResult(
                status="no_execution",
                recommendation=recommendation,
                reason="ignore_temporarily is a no-op recommendation in this demo",
            )
        if bool(recommendation.get("requires_confirmation", False)):
            request = create_confirmation_request(recommendation, now=now)
            self.confirmation_store.put(request, recommendation)
            return ControlLoopResult(
                status="confirmation_required",
                recommendation=recommendation,
                confirmation_request=request.to_payload(),
                reason="selected action requires human confirmation before execution",
            )

        feedback = self.execution_adapter.execute_and_apply(
            state,
            recommendation,
            now=now,
            confirmed=True,
        )
        return ControlLoopResult(
            status=feedback.status,
            recommendation=recommendation,
            execution=feedback.to_payload(),
            state_updated=feedback.state_updated,
            reason=feedback.reason,
        )

    def resolve_confirmation(
        self,
        state: WorldState,
        confirmation_id: str,
        *,
        choice: ConfirmationChoice,
        now: datetime | None = None,
    ) -> ConfirmationResolution:
        record = self.confirmation_store.get(confirmation_id)
        if record is None:
            return ConfirmationResolution(
                status="missing_confirmation",
                choice=choice,
                confirmation_id=confirmation_id,
                reason="confirmation_id was not found",
            )
        if record.status != "pending":
            return ConfirmationResolution(
                status="already_resolved",
                choice=choice,
                confirmation_id=confirmation_id,
                confirmation_request=record.request,
                reason=f"confirmation is already {record.status}",
            )
        if choice == "details":
            return ConfirmationResolution(
                status="details",
                choice=choice,
                confirmation_id=confirmation_id,
                confirmation_request=record.request,
                details=confirmation_details(record.recommendation),
                reason="details returned without execution",
            )
        if choice == "reject":
            self.confirmation_store.resolve(confirmation_id, status="rejected", now=now)
            return ConfirmationResolution(
                status="rejected",
                choice=choice,
                confirmation_id=confirmation_id,
                confirmation_request=record.request,
                reason="user rejected execution",
            )

        self.confirmation_store.resolve(confirmation_id, status="confirmed", now=now)
        feedback = self.execution_adapter.execute_and_apply(
            state,
            record.recommendation,
            now=now,
            confirmed=True,
        )
        return ConfirmationResolution(
            status="executed",
            choice=choice,
            confirmation_id=confirmation_id,
            confirmation_request=record.request,
            execution=feedback.to_payload(),
            state_updated=feedback.state_updated,
            reason="user confirmed execution",
        )


def create_confirmation_request(
    recommendation: dict[str, Any],
    *,
    now: datetime | None = None,
) -> ConfirmationRequest:
    created = now or utc_now()
    decision_id = str(recommendation["decision_id"])
    selected_action = str(recommendation["selected_action"])
    acted_on = recommendation.get("acted_on")
    return ConfirmationRequest(
        confirmation_id=make_confirmation_id(
            now=created,
            decision_id=decision_id,
            selected_action=selected_action,
            acted_on=acted_on,
        ),
        decision_id=decision_id,
        selected_action=selected_action,
        acted_on=str(acted_on) if acted_on else None,
        human_summary=str(recommendation.get("human_summary") or selected_action),
        reason_summary=[str(item) for item in recommendation.get("reason_summary", [])],
        options=[
            {"key": "1", "value": "confirm"},
            {"key": "2", "value": "reject"},
            {"key": "3", "value": "details"},
        ],
        created_at=timestamp_segment(created),
    )


def format_confirmation_for_whatsapp(request: ConfirmationRequest | dict[str, Any]) -> str:
    payload = request.to_payload() if isinstance(request, ConfirmationRequest) else request
    reasons = [str(item) for item in payload.get("reason_summary", [])]
    reason_block = "\n".join(f"- {item}" for item in reasons) if reasons else "- selected by Spice decision policy"
    return (
        "我建议执行：\n"
        f"{payload.get('selected_action')} ({payload.get('human_summary')})\n\n"
        "原因：\n"
        f"{reason_block}\n\n"
        "回复：\n"
        "1 同意执行\n"
        "2 拒绝\n"
        "3 查看详情"
    )


def confirmation_details(recommendation: dict[str, Any]) -> dict[str, Any]:
    trace_ref = recommendation.get("trace_ref")
    trace = get_trace(str(trace_ref)) if trace_ref else None
    return {
        "decision_id": recommendation.get("decision_id"),
        "selected_action": recommendation.get("selected_action"),
        "acted_on": recommendation.get("acted_on"),
        "human_summary": recommendation.get("human_summary"),
        "reason_summary": list(recommendation.get("reason_summary", [])),
        "trace_ref": trace_ref,
        "score_breakdown": dict(recommendation.get("score_breakdown", {})),
        "veto_reasons": list(recommendation.get("veto_reasons", [])),
        "tradeoff_rules_applied": list(recommendation.get("tradeoff_rules_applied", [])),
        "trace_available": trace is not None,
    }
