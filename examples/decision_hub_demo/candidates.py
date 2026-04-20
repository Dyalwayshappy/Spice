from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from examples.decision_hub_demo.context import ActiveDecisionContext

DELEGATION_SCOPE = "triage"


@dataclass(frozen=True, slots=True)
class CandidateAction:
    action_type: str
    description: str
    executor_requirement: str = "none"
    requires_confirmation: bool = False


@dataclass(slots=True)
class CandidateRecord:
    candidate_id: str
    action_type: str
    params: dict[str, Any]
    grounding_refs: list[str]
    enabled_reason: str
    disabled_reason: str = ""
    requires_confirmation: bool = False
    executor_requirement: str = "none"

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CandidateGenerationReport:
    enabled: list[CandidateRecord] = field(default_factory=list)
    disabled: list[CandidateRecord] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": [item.to_payload() for item in self.enabled],
            "disabled": [item.to_payload() for item in self.disabled],
        }


CANDIDATE_REGISTRY: dict[str, CandidateAction] = {
    "handle_now": CandidateAction(
        action_type="handle_now",
        description="Work on the item immediately.",
    ),
    "quick_triage_then_defer": CandidateAction(
        action_type="quick_triage_then_defer",
        description="Spend a short fixed window reducing uncertainty, then defer.",
    ),
    "ignore_temporarily": CandidateAction(
        action_type="ignore_temporarily",
        description="Take no immediate action and revisit later.",
    ),
    "delegate_to_executor": CandidateAction(
        action_type="delegate_to_executor",
        description="Delegate the work item to an external executor.",
        executor_requirement="external_executor",
        requires_confirmation=True,
    ),
    "ask_user": CandidateAction(
        action_type="ask_user",
        description="Ask the user for missing information before deciding.",
        requires_confirmation=False,
    ),
}


def generate_candidates(context: ActiveDecisionContext) -> CandidateGenerationReport:
    report = CandidateGenerationReport()
    target = context.open_work_items[0] if context.open_work_items else {}
    grounding_refs = [
        *[str(item.get("id")) for item in context.relevant_commitments],
        *[str(item.get("id")) for item in context.open_work_items],
    ]

    for action_type in (
        "handle_now",
        "quick_triage_then_defer",
        "ignore_temporarily",
    ):
        action = CANDIDATE_REGISTRY[action_type]
        report.enabled.append(
            _record(
                action,
                context=context,
                target=target,
                grounding_refs=grounding_refs,
                enabled_reason="baseline candidate for time-sensitive work-item decisions",
            )
        )

    delegate = CANDIDATE_REGISTRY["delegate_to_executor"]
    delegate_capability = _delegate_capability(context)
    if delegate_capability:
        report.enabled.append(
            _record(
                delegate,
                context=context,
                target=target,
                grounding_refs=grounding_refs,
                enabled_reason=(
                    "executor capability observation is available for "
                    f"{DELEGATION_SCOPE}"
                ),
                executor_capability=delegate_capability,
            )
        )
    else:
        report.disabled.append(
            _record(
                delegate,
                context=context,
                target=target,
                grounding_refs=grounding_refs,
                enabled_reason="",
                disabled_reason=_delegate_disabled_reason(context),
            )
        )

    ask_user = CANDIDATE_REGISTRY["ask_user"]
    ask_user_reason = _ask_user_reason(context)
    if ask_user_reason:
        report.enabled.append(
            _record(
                ask_user,
                context=context,
                target=target,
                grounding_refs=grounding_refs,
                enabled_reason=ask_user_reason,
            )
        )
    else:
        report.disabled.append(
            _record(
                ask_user,
                context=context,
                target=target,
                grounding_refs=grounding_refs,
                enabled_reason="",
                disabled_reason="no missing critical information or high uncertainty",
            )
        )
    return report


def _record(
    action: CandidateAction,
    *,
    context: ActiveDecisionContext,
    target: dict[str, Any],
    grounding_refs: list[str],
    enabled_reason: str,
    disabled_reason: str = "",
    executor_capability: dict[str, Any] | None = None,
) -> CandidateRecord:
    params = {
        "target_work_item_id": target.get("id"),
        "target_work_item_title": target.get("title"),
        "available_window_minutes": context.available_window_minutes,
        "conflict_types": [item.type for item in context.conflict_facts],
    }
    if action.action_type == "delegate_to_executor":
        params["required_scope"] = DELEGATION_SCOPE
        if executor_capability:
            params["executor_capability"] = dict(executor_capability)
    requires_confirmation = action.requires_confirmation
    if action.action_type == "delegate_to_executor" and executor_capability:
        requires_confirmation = bool(executor_capability.get("requires_confirmation", True))
    return CandidateRecord(
        candidate_id=f"cand.{action.action_type}",
        action_type=action.action_type,
        params=params,
        grounding_refs=grounding_refs,
        enabled_reason=enabled_reason,
        disabled_reason=disabled_reason,
        requires_confirmation=requires_confirmation,
        executor_requirement=action.executor_requirement,
    )


def _ask_user_reason(context: ActiveDecisionContext) -> str:
    if context.missing_fields:
        return "critical fields are missing from the active decision context"
    if context.uncertainty_reasons:
        return "active context includes low-confidence facts"
    if any(item.type == "uncertainty" for item in context.conflict_facts):
        return "conflict facts include uncertainty"
    return ""


def _delegate_capability(context: ActiveDecisionContext) -> dict[str, Any] | None:
    if not context.available_capabilities:
        return None
    return dict(context.available_capabilities[0])


def _delegate_disabled_reason(context: ActiveDecisionContext) -> str:
    if not context.executor_capabilities:
        return "no delegate_to_executor capability observation is present in WorldState"
    if not any(item.get("availability") == "available" for item in context.executor_capabilities):
        return "delegate_to_executor capability is not available"
    return f"delegate_to_executor capability does not support required scope: {DELEGATION_SCOPE}"
