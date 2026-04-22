from __future__ import annotations

from typing import Any


def format_recommendation(
    *,
    selected_action: str,
    acted_on: str | None,
    score_breakdown: dict[str, float],
    veto_reasons: list[dict[str, Any]],
    tradeoff_rules_applied: list[str],
    trace: dict[str, Any],
) -> dict[str, Any]:
    target = acted_on or "the active work item"
    human_summary = _human_summary(selected_action, target)
    reason_summary = _reason_summary(
        selected_action=selected_action,
        score_breakdown=score_breakdown,
        veto_reasons=veto_reasons,
        tradeoff_rules_applied=tradeoff_rules_applied,
        trace=trace,
    )
    return {
        "recommendation": selected_action,
        "human_summary": human_summary,
        "reason_summary": reason_summary,
    }


def _human_summary(selected_action: str, target: str) -> str:
    if selected_action == "delegate_to_executor":
        return f"Delegate {target} and review the outcome afterward."
    if selected_action == "quick_triage_then_defer":
        return f"Spend a short triage window on {target}, then defer full handling."
    if selected_action == "handle_now":
        return f"Handle {target} now."
    if selected_action == "ignore_temporarily":
        return f"Temporarily ignore {target} and preserve the current time window."
    if selected_action == "ask_user":
        return "Ask the user for missing decision information before acting."
    return f"Select {selected_action} for {target}."


def _reason_summary(
    *,
    selected_action: str,
    score_breakdown: dict[str, float],
    veto_reasons: list[dict[str, Any]],
    tradeoff_rules_applied: list[str],
    trace: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    consequence = trace.get("candidate_consequences", {}).get(f"cand.{selected_action}", {})

    if consequence.get("commitment_risk") == "low":
        reasons.append("low commitment risk")
    if consequence.get("work_item_risk_change") == "reduced":
        reasons.append("work-item risk is reduced")
    if selected_action == "delegate_to_executor" and consequence.get("metadata", {}).get("executor_available"):
        reasons.append("executor available")
    if selected_action == "ask_user":
        reasons.append("reduces uncertainty before execution")

    if tradeoff_rules_applied:
        reasons.extend(_tradeoff_reason(rule) for rule in tradeoff_rules_applied)
    if veto_reasons:
        vetoed = sorted({str(item.get("candidate_id")) for item in veto_reasons})
        reasons.append("unsafe alternatives vetoed: " + ", ".join(vetoed))

    top_dimensions = [
        name
        for name, value in sorted(score_breakdown.items(), key=lambda item: item[1], reverse=True)
        if value >= 0.70
    ][:2]
    for dimension in top_dimensions:
        reasons.append(f"strong {dimension}")

    deduped: list[str] = []
    for reason in reasons:
        if reason and reason not in deduped:
            deduped.append(reason)
    return deduped or ["selected by guided score after constraints and trade-off rules"]


def _tradeoff_reason(rule_id: str) -> str:
    if rule_id == "prefer_delegate_when_executor_available_and_time_pressure":
        return "time pressure favors delegation"
    if rule_id == "prefer_reversible_under_time_pressure":
        return "time pressure favors reversible action"
    return f"trade-off rule applied: {rule_id}"
