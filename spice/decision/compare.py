from __future__ import annotations

import json
from typing import Any, Mapping

from spice.decision.compare_payload import normalize_compare_payload


def analyze_compare_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_compare_payload(payload)
    candidates = []
    score_candidates = normalized["score_breakdown"]["candidates"]
    for item in normalized["candidate_decisions"]:
        candidate_id = item["candidate_id"]
        score = score_candidates[candidate_id]
        candidates.append(
            {
                "candidate_id": candidate_id,
                "title": item["title"],
                "action": item["action"],
                "intent": item["intent"],
                "enabled_reason": item["enabled_reason"],
                "requires_confirmation": item["requires_confirmation"],
                "expected_effect": item["expected_effect"],
                "score_total": score["score_total"],
                "dimensions": sorted(
                    score["dimensions"],
                    key=lambda dimension: dimension["contribution"],
                    reverse=True,
                ),
                "constraints": score["constraints"],
                "vetoes": score["vetoes"],
                "tradeoff_rules": score["tradeoff_rules"],
                "is_vetoed": bool(score["vetoes"]),
                "is_selected": item["is_selected"],
            }
        )
    return {
        "decision_id": normalized["decision_id"],
        "trace_ref": normalized["trace_ref"],
        "decision_relevant_state_summary": normalized["decision_relevant_state_summary"],
        "candidates": candidates,
        "selected_recommendation": normalized["selected_recommendation"],
        "why_not_the_others": normalized["why_not_the_others"],
        "expected_outcome_or_risk": normalized["expected_outcome_or_risk"],
        "execution_boundary": normalized["execution_boundary"],
        "outcome_return": normalized["outcome_return"],
    }


def render_compare_text(
    payload: Mapping[str, Any],
    *,
    show_execution: bool = False,
    use_bars: bool = True,
) -> str:
    analysis = analyze_compare_payload(payload)
    lines: list[str] = []
    lines.append("DECISION COMPARISON")
    lines.append(f"decision_id: {analysis['decision_id']}")
    lines.append(f"trace_ref: {analysis['trace_ref']}")
    lines.append("")
    lines.append("DECISION-RELEVANT STATE")
    lines.extend(_render_state_summary(analysis["decision_relevant_state_summary"]))
    lines.append("")
    lines.append("CANDIDATES")
    lines.append("")

    for index, candidate in enumerate(analysis["candidates"]):
        prefix = chr(ord("A") + index)
        lines.append(f"{prefix}. {candidate['title']}")
        lines.append(f"   action: {candidate['action']}")
        if candidate["intent"]:
            lines.append(f"   intent: {candidate['intent']}")
        if candidate["enabled_reason"]:
            lines.append(f"   enabled because: {candidate['enabled_reason']}")
        lines.append("   score dimensions:")
        for dimension in candidate["dimensions"]:
            lines.append("   " + _format_dimension_line(dimension, use_bars=use_bars))
        score_line = f"   guided score: {candidate['score_total']:.2f}"
        if candidate["is_vetoed"]:
            score_line += " (blocked by veto)"
        lines.append(score_line)
        lines.append("   veto: " + _render_veto(candidate["vetoes"]))
        lines.append("   constraints: " + _render_constraints(candidate["constraints"]))
        lines.append("   tradeoff rules: " + _render_tradeoff_rules(candidate["tradeoff_rules"]))
        lines.append("   expected outcome / risk:")
        lines.extend("   " + item for item in _render_expected_effect(candidate["expected_effect"]))
        lines.append("")

    selected = analysis["selected_recommendation"]
    lines.append("SELECTED")
    lines.append(f"- {selected['title']} ({selected['candidate_id']})")
    if selected["selection_reason"]:
        lines.append(f"- selection summary: {selected['selection_reason']}")
    if selected["human_summary"]:
        lines.append(f"- recommendation: {selected['human_summary']}")
    lines.append("")
    lines.append("WHY THIS WON")
    rendered_basis = 0
    if selected["decision_basis"]:
        for basis in selected["decision_basis"]:
            lines.append(f"- {_render_selected_basis(basis)}")
            rendered_basis += 1
            if rendered_basis >= 3:
                break
    else:
        lines.append("- According to the current trace, no explicit selection basis was recorded.")
    rendered_notes = 0
    if selected["reason_summary"]:
        for reason in selected["reason_summary"]:
            lines.append(f"- supporting note: {reason}")
            rendered_notes += 1
            if rendered_basis + rendered_notes >= 3:
                break
    lines.append("")
    lines.append("WHY NOT OTHERS")
    for item in analysis["why_not_the_others"]:
        lines.append(f"- {item['title']} ({item['candidate_id']}):")
        if item["reasons"]:
            for reason in item["reasons"]:
                lines.append(f"  - {_render_why_not_reason(reason)}")
        else:
            lines.append("  - No explicit compare evidence was recorded for this candidate.")
    if show_execution:
        lines.append("")
        lines.append("EXECUTION BOUNDARY")
        execution_boundary = analysis["execution_boundary"]
        lines.append(
            f"- requires confirmation: {str(execution_boundary['requires_confirmation']).lower()}"
        )
        lines.append(f"- execution path: {execution_boundary['execution_path']}")
        if execution_boundary["executor"]:
            lines.append(f"- executor: {execution_boundary['executor']}")
        if execution_boundary["note"]:
            lines.append(f"- note: {execution_boundary['note']}")
    return "\n".join(lines)


def render_compare_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(normalize_compare_payload(payload), indent=2, sort_keys=True)


def _render_state_summary(summary: Mapping[str, Any]) -> list[str]:
    lines = []
    if summary.get("now"):
        lines.append(f"- now: {summary['now']}")
    if summary.get("available_window_minutes"):
        lines.append(
            f"- available window before the next commitment boundary: "
            f"{int(summary['available_window_minutes'])} minutes"
        )
    commitments = summary.get("active_commitments", [])
    for item in commitments:
        lines.append(
            "- active commitment: "
            f"{item.get('summary', item.get('id', 'unknown commitment'))} "
            f"(prep_start={item.get('prep_start_time')}, start={item.get('start_time')})"
        )
    work_items = summary.get("open_work_items", [])
    for item in work_items:
        lines.append(
            "- open work item: "
            f"{item.get('title', item.get('id', 'unknown work item'))} "
            f"(urgency={item.get('urgency_hint')}, estimate={_format_minutes(item.get('estimated_minutes_hint'))})"
        )
    for item in summary.get("active_conflicts", []):
        detail = []
        if item.get("available_window_minutes"):
            detail.append(f"window={_format_minutes(item.get('available_window_minutes'))}")
        if item.get("estimated_work_minutes"):
            detail.append(f"estimated_work={_format_minutes(item.get('estimated_work_minutes'))}")
        suffix = f" [{', '.join(detail)}]" if detail else ""
        lines.append(f"- active conflict: {item.get('type')} ({item.get('severity')}){suffix}")
    lines.append(f"- executor available: {str(bool(summary.get('executor_available'))).lower()}")
    return lines


def _format_dimension_line(dimension: Mapping[str, Any], *, use_bars: bool) -> str:
    label = dimension.get("label") or dimension.get("dimension") or "unknown"
    value = float(dimension.get("value", 0.0))
    weight = float(dimension.get("weight", 0.0))
    contribution = float(dimension.get("contribution", 0.0))
    if use_bars:
        return (
            f"- {label}: {value:.2f} {_bar(value)}  "
            f"weight {weight:.2f}  contribution {contribution:.2f}"
        )
    return f"- {label}: value {value:.2f}  weight {weight:.2f}  contribution {contribution:.2f}"


def _render_veto(vetoes: list[Mapping[str, Any]]) -> str:
    if not vetoes:
        return "none"
    return "; ".join(
        f"{item.get('constraint_id')}: {item.get('reason')}" for item in vetoes
    )


def _render_constraints(constraints: list[Mapping[str, Any]]) -> str:
    if not constraints:
        return "none recorded"
    failed = [item for item in constraints if item.get("status") == "fail"]
    if failed:
        return "; ".join(
            f"{item.get('constraint_id')}={item.get('status')}" for item in failed
        )
    return "all recorded hard constraints passed"


def _render_tradeoff_rules(rules: list[Mapping[str, Any]]) -> str:
    if not rules:
        return "none recorded"
    return "; ".join(
        f"{item.get('rule_id')}={item.get('status')}" for item in rules
    )


def _render_expected_effect(expected: Mapping[str, Any]) -> list[str]:
    return [
        f"- commitment risk: {expected.get('commitment_risk') or 'unknown'}",
        f"- work-item risk change: {expected.get('work_item_risk_change') or 'unknown'}",
        f"- expected time cost: {_format_minutes(expected.get('expected_time_cost_minutes'))}",
        f"- follow-up needed: {str(bool(expected.get('followup_needed'))).lower()}",
    ]


def _render_selected_basis(reason: Mapping[str, Any]) -> str:
    kind = str(reason.get("kind", ""))
    if kind == "weighted_dimension":
        return (
            "According to the current compare payload, a high-weight dimension favored the selected "
            f"candidate: {reason.get('label')} "
            f"(weight {float(reason.get('weight', 0.0)):.2f}, "
            f"contribution {float(reason.get('contribution', 0.0)):.2f})."
        )
    if kind == "tradeoff_rule":
        return (
            "According to the current compare payload, a trade-off rule supported the selected action: "
            f"{reason.get('rule_id')}."
        )
    if kind == "constraint_clear":
        return str(reason.get("summary"))
    return "The current trace records additional selection support for the selected candidate."


def _render_why_not_reason(reason: Mapping[str, Any]) -> str:
    kind = str(reason.get("kind", ""))
    if kind == "veto":
        return (
            f"Vetoed by {reason.get('constraint_id')}: "
            f"{reason.get('reason')}"
        )
    if kind == "tradeoff_rule":
        return (
            "The selected candidate was preferred by trade-off rule "
            f"{reason.get('rule_id')}: {reason.get('reason')}"
        )
    if kind == "weighted_dimension_gap":
        return (
            "According to the current compare payload, the selected candidate leads on "
            f"{reason.get('label')} "
            f"(selected contribution {float(reason.get('selected_contribution', 0.0)):.2f} "
            f"vs {float(reason.get('candidate_contribution', 0.0)):.2f}, "
            f"weight {float(reason.get('weight', 0.0)):.2f})."
        )
    return "No explicit why-not reason was recorded."


def _bar(value: float) -> str:
    bounded = max(0.0, min(1.0, value))
    filled = int(round(bounded * 10))
    return "█" * filled + "░" * (10 - filled)


def _format_minutes(value: Any) -> str:
    try:
        number = int(float(value))
        return f"{number} minutes"
    except (TypeError, ValueError):
        return "unknown"
