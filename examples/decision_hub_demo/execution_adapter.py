from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from spice.protocols.observation import Observation
from spice.protocols.world_state import WorldState

from examples.decision_hub_demo.ids import make_execution_id, short_hash, timestamp_segment
from examples.decision_hub_demo.reducer import ingest_observation
from examples.decision_hub_demo.state import utc_now


NON_EXECUTABLE_ACTIONS = {"ask_user"}


@dataclass(slots=True)
class ExecutionRequest:
    execution_id: str
    decision_id: str
    action_type: str
    acted_on: str | None
    params: dict[str, Any]
    executor: str
    created_at: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionOutcome:
    status: str
    elapsed_minutes: int
    risk_change: str
    followup_needed: bool
    summary: str
    execution_ref: str
    blocking_issue: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionFeedbackResult:
    status: str
    execution_request: dict[str, Any] | None
    outcome: dict[str, Any] | None
    observation: dict[str, Any] | None
    state_updated: bool
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class Executor(Protocol):
    name: str

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        ...


class MockExecutor:
    name = "mock"

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        action = request.action_type
        if action == "delegate_to_executor":
            return ExecutionOutcome(
                status="success",
                elapsed_minutes=6,
                risk_change="reduced",
                followup_needed=True,
                summary="PR triaged, no blocking issue.",
                execution_ref=f"mock.{request.execution_id}",
                metadata={"executor": self.name, "mode": "demo"},
            )
        if action == "quick_triage_then_defer":
            return ExecutionOutcome(
                status="partial",
                elapsed_minutes=5,
                risk_change="reduced",
                followup_needed=True,
                summary="Quick triage completed; full handling remains.",
                execution_ref=f"mock.{request.execution_id}",
                metadata={"executor": self.name, "mode": "demo"},
            )
        if action == "handle_now":
            return ExecutionOutcome(
                status="success",
                elapsed_minutes=max(1, int(request.params.get("expected_time_cost_minutes") or 30)),
                risk_change="reduced",
                followup_needed=False,
                summary="Work item handled in the mock executor.",
                execution_ref=f"mock.{request.execution_id}",
                metadata={"executor": self.name, "mode": "demo"},
            )
        if action == "ignore_temporarily":
            return ExecutionOutcome(
                status="abandoned",
                elapsed_minutes=0,
                risk_change="increased",
                followup_needed=True,
                summary="No execution was performed for the work item.",
                execution_ref=f"mock.{request.execution_id}",
                metadata={"executor": self.name, "mode": "demo"},
            )
        return ExecutionOutcome(
            status="failed",
            elapsed_minutes=0,
            risk_change="unchanged",
            followup_needed=True,
            summary=f"Unsupported mock execution action: {action}",
            execution_ref=f"mock.{request.execution_id}",
            blocking_issue="unsupported_action",
            metadata={"executor": self.name, "mode": "demo"},
        )


class ExecutionFeedbackAdapter:
    """Demo execution feedback loop.

    Execution output never mutates WorldState directly. It is converted into an
    execution_result_observed observation and then applied through the reducer.
    The default executor is SDEP-backed; tests and legacy callers may still
    inject another Executor explicitly.
    """

    def __init__(self, executor: Executor | None = None) -> None:
        self.executor = executor or create_default_executor()

    def execute_and_apply(
        self,
        state: WorldState,
        recommendation: dict[str, Any],
        *,
        now: datetime | None = None,
        confirmed: bool = False,
    ) -> ExecutionFeedbackResult:
        action_type = str(recommendation.get("selected_action") or "")
        if action_type in NON_EXECUTABLE_ACTIONS:
            return ExecutionFeedbackResult(
                status="skipped",
                execution_request=None,
                outcome=None,
                observation=None,
                state_updated=False,
                reason=f"{action_type} requires user input and does not trigger execution",
            )
        if bool(recommendation.get("requires_confirmation", False)) and not confirmed:
            return ExecutionFeedbackResult(
                status="confirmation_required",
                execution_request=None,
                outcome=None,
                observation=None,
                state_updated=False,
                reason=f"{action_type} requires confirmation before execution",
            )

        request = build_execution_request(
            recommendation,
            executor=_target_executor(recommendation) or self.executor.name,
            now=now,
        )
        outcome = self.executor.execute(request)
        observation = execution_outcome_to_observation(
            request=request,
            outcome=outcome,
            selected_action=action_type,
            now=now,
        )
        ingest_observation(state, observation)
        return ExecutionFeedbackResult(
            status="applied",
            execution_request=request.to_payload(),
            outcome=outcome.to_payload(),
            observation=_observation_payload(observation),
            state_updated=True,
        )


def build_execution_request(
    recommendation: dict[str, Any],
    *,
    executor: str,
    now: datetime | None = None,
) -> ExecutionRequest:
    created = now or utc_now()
    decision_id = str(recommendation["decision_id"])
    action_type = str(recommendation["selected_action"])
    acted_on = recommendation.get("acted_on")
    selected_consequence = (
        recommendation.get("trace", {})
        .get("candidate_consequences", {})
        .get(f"cand.{action_type}", {})
    )
    target = _target_work_item(recommendation)
    scope = _execution_scope(action_type, selected_consequence)
    time_budget = _time_budget(action_type, selected_consequence)
    params = {
        "scope": scope,
        "time_budget_minutes": time_budget,
        "target_title": target.get("title"),
        "target_url": target.get("url"),
        "success_criteria": _success_criteria(action_type),
        "recommendation": recommendation.get("recommendation"),
        "human_summary": recommendation.get("human_summary"),
        "reason_summary": list(recommendation.get("reason_summary", [])),
        "score_breakdown": dict(recommendation.get("score_breakdown", {})),
        "trace_ref": recommendation.get("trace_ref"),
        "expected_time_cost_minutes": selected_consequence.get("expected_time_cost_minutes"),
        "requires_confirmation": recommendation.get("requires_confirmation", False),
    }
    return ExecutionRequest(
        execution_id=make_execution_id(
            now=created,
            decision_id=decision_id,
            action_type=action_type,
            acted_on=acted_on,
        ),
        decision_id=decision_id,
        action_type=action_type,
        acted_on=str(acted_on) if acted_on else None,
        params=params,
        executor=executor,
        created_at=timestamp_segment(created),
    )


def create_default_executor() -> Executor:
    from examples.decision_hub_demo import sdep_executor

    return sdep_executor.create_default_sdep_executor()


def execution_outcome_to_observation(
    *,
    request: ExecutionRequest,
    outcome: ExecutionOutcome,
    selected_action: str,
    now: datetime | None = None,
) -> Observation:
    observed_at = now or datetime.now(timezone.utc)
    observation_id = "obs.execution." + short_hash(
        {
            "execution_id": request.execution_id,
            "execution_ref": outcome.execution_ref,
            "decision_id": request.decision_id,
        },
        length=12,
    )
    outcome_metadata = dict(outcome.metadata)
    trace_ref = _trace_ref_from_request(request)
    provenance = {
        "adapter": "decision_hub_demo.execution_feedback_adapter",
        "execution_id": request.execution_id,
        "decision_id": request.decision_id,
        "trace_ref": trace_ref,
        "acted_on": request.acted_on,
        "selected_action": selected_action,
        "executor": request.executor,
        "execution_ref": outcome.execution_ref,
        "outcome_status": outcome.status,
    }
    if outcome_metadata.get("sdep_response_status") is not None:
        provenance["sdep_response_status"] = outcome_metadata["sdep_response_status"]
    if outcome_metadata.get("sdep_outcome_status") is not None:
        provenance["sdep_outcome_status"] = outcome_metadata["sdep_outcome_status"]
    if outcome_metadata.get("sdep_error") is not None:
        provenance["protocol_error"] = outcome_metadata["sdep_error"]
    return Observation(
        id=observation_id,
        timestamp=observed_at,
        observation_type="execution_result_observed",
        source=request.executor,
        attributes={
            "execution_id": request.execution_id,
            "decision_id": request.decision_id,
            "trace_ref": trace_ref,
            "status": outcome.status,
            "acted_on": request.acted_on,
            "selected_action": selected_action,
            "elapsed_minutes": outcome.elapsed_minutes,
            "risk_change": outcome.risk_change,
            "followup_needed": outcome.followup_needed,
            "summary": outcome.summary,
            "execution_ref": outcome.execution_ref,
            "blocking_issue": outcome.blocking_issue,
        },
        metadata={
            "execution_request": request.to_payload(),
            "execution_outcome": outcome.to_payload(),
            "execution_metadata": provenance,
            "outcome_metadata": outcome_metadata,
            "provenance": provenance,
            "bridge": "decision_hub_demo.execution_feedback_adapter",
        },
    )


def _observation_payload(observation: Observation) -> dict[str, Any]:
    return {
        "id": observation.id,
        "timestamp": timestamp_segment(observation.timestamp),
        "observation_type": observation.observation_type,
        "source": observation.source,
        "attributes": dict(observation.attributes),
        "metadata": dict(observation.metadata),
    }


def _target_executor(recommendation: dict[str, Any]) -> str | None:
    action_type = str(recommendation.get("selected_action") or "")
    consequence = (
        recommendation.get("trace", {})
        .get("candidate_consequences", {})
        .get(f"cand.{action_type}", {})
    )
    metadata = consequence.get("metadata", {}) if isinstance(consequence, dict) else {}
    if isinstance(metadata, dict) and metadata.get("executor"):
        return str(metadata["executor"])
    return None


def _trace_ref_from_request(request: ExecutionRequest) -> str | None:
    raw = request.params.get("trace_ref")
    if raw is None:
        return None
    return str(raw)


def _target_work_item(recommendation: dict[str, Any]) -> dict[str, Any]:
    acted_on = recommendation.get("acted_on")
    active_context = recommendation.get("trace", {}).get("active_context", {})
    for item in active_context.get("open_work_items", []) or []:
        if item.get("id") == acted_on:
            return dict(item)
    return {}


def _execution_scope(action_type: str, consequence: dict[str, Any]) -> str:
    metadata = consequence.get("metadata", {}) if isinstance(consequence, dict) else {}
    if isinstance(metadata, dict) and metadata.get("required_scope"):
        return str(metadata["required_scope"])
    if action_type == "quick_triage_then_defer":
        return "triage"
    if action_type == "handle_now":
        return "handle"
    return action_type


def _time_budget(action_type: str, consequence: dict[str, Any]) -> int:
    metadata = consequence.get("metadata", {}) if isinstance(consequence, dict) else {}
    if isinstance(metadata, dict):
        raw = metadata.get("default_time_budget_minutes")
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    try:
        expected = int(consequence.get("expected_time_cost_minutes") or 0)
    except (TypeError, ValueError):
        expected = 0
    if expected > 0:
        return expected
    if action_type == "quick_triage_then_defer":
        return 5
    return 10


def _success_criteria(action_type: str) -> str:
    if action_type == "delegate_to_executor":
        return "Return status, blocker, risk_change, followup_needed, and a concise summary."
    if action_type == "quick_triage_then_defer":
        return "Return triage status, blocker if any, risk_change, followup_needed, and remaining work summary."
    if action_type == "handle_now":
        return "Return completion status, blocker if any, risk_change, followup_needed, and summary."
    return "Return structured outcome fields only."
