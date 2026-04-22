from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


_ACTION_TITLES = {
    "handle_now": "Handle Now",
    "quick_triage_then_defer": "Quick Triage Then Defer",
    "ignore_temporarily": "Ignore Temporarily",
    "delegate_to_executor": "Delegate To Executor",
    "ask_user": "Ask User",
}

_ACTION_INTENTS = {
    "handle_now": "Spend the current time window on the work item immediately.",
    "quick_triage_then_defer": "Use a short window to reduce uncertainty, then defer full handling.",
    "ignore_temporarily": "Preserve the current window and leave the work item unchanged for now.",
    "delegate_to_executor": "Use an available executor to reduce work-item risk without consuming the user's window.",
    "ask_user": "Request missing information before committing to action.",
}

_DIMENSION_LABELS = {
    "commitment_safety": "Commitment Safety",
    "work_item_risk_reduction": "Work-Item Risk Reduction",
    "reversibility": "Reversibility",
    "time_efficiency": "Time Efficiency",
    "attention_preservation": "Attention Preservation",
    "confidence_alignment": "Confidence Alignment",
}


def load_compare_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("decision compare input must be a JSON object")
    return normalize_compare_payload(payload)


def normalize_compare_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    decision_id = _string(payload.get("decision_id"))
    trace_ref = _string(payload.get("trace_ref"))
    if not decision_id:
        raise ValueError("compare payload requires decision_id")
    if not trace_ref:
        raise ValueError("compare payload requires trace_ref")

    summary = payload.get("decision_relevant_state_summary", {})
    candidates = payload.get("candidate_decisions", [])
    score_breakdown = payload.get("score_breakdown", {})
    selected = payload.get("selected_recommendation", {})
    why_not = payload.get("why_not_the_others", [])
    expected = payload.get("expected_outcome_or_risk", {})
    execution_boundary = payload.get("execution_boundary", {})
    outcome_return = payload.get("outcome_return", {})

    if not isinstance(summary, Mapping):
        raise ValueError("decision_relevant_state_summary must be an object")
    if not isinstance(candidates, list):
        raise ValueError("candidate_decisions must be a list")
    if not isinstance(score_breakdown, Mapping):
        raise ValueError("score_breakdown must be an object")
    if not isinstance(selected, Mapping):
        raise ValueError("selected_recommendation must be an object")
    if not isinstance(why_not, list):
        raise ValueError("why_not_the_others must be a list")

    normalized = {
        "decision_id": decision_id,
        "trace_ref": trace_ref,
        "decision_relevant_state_summary": _normalize_state_summary(summary),
        "candidate_decisions": [_normalize_candidate(item) for item in candidates],
        "score_breakdown": _normalize_score_breakdown(score_breakdown),
        "selected_recommendation": _normalize_selected_recommendation(selected),
        "why_not_the_others": [_normalize_why_not(item) for item in why_not],
        "expected_outcome_or_risk": _normalize_expected_effect(expected),
        "execution_boundary": _normalize_execution_boundary(execution_boundary),
        "outcome_return": _normalize_outcome_return(outcome_return),
    }
    _validate_candidate_alignment(normalized)
    return normalized


def build_compare_payload_from_trace(
    trace: Mapping[str, Any],
    *,
    decision_id: str,
    trace_ref: str,
    recommendation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_payloads = trace.get("candidates", [])
    active_context = trace.get("active_context", {})
    candidate_generation = trace.get("candidate_generation", {})
    candidate_scores = trace.get("candidate_scores", {})
    consequences = trace.get("candidate_consequences", {})
    constraint_evaluations = trace.get("constraint_evaluations", [])
    veto_events = trace.get("veto_events", [])
    tradeoff_details = trace.get("applied_tradeoff_rules", [])
    selected_candidate_id = _string(trace.get("selected_candidate_id"))

    if not isinstance(candidate_payloads, list) or not candidate_payloads:
        raise ValueError("trace is missing candidates")
    if not selected_candidate_id:
        raise ValueError("trace is missing selected_candidate_id")

    enabled_map = {
        _string(item.get("candidate_id")): item
        for item in _list(candidate_generation.get("enabled"))
        if isinstance(item, Mapping)
    }
    disabled_map = {
        _string(item.get("candidate_id")): item
        for item in _list(candidate_generation.get("disabled"))
        if isinstance(item, Mapping)
    }

    candidate_decisions: list[dict[str, Any]] = []
    score_candidates: dict[str, Any] = {}
    why_not_the_others: list[dict[str, Any]] = []

    selected_payload = None
    for item in candidate_payloads:
        if not isinstance(item, Mapping):
            continue
        candidate_id = _string(item.get("id"))
        if not candidate_id:
            continue
        if candidate_id == selected_candidate_id:
            selected_payload = item
        generation_entry = enabled_map.get(candidate_id) or disabled_map.get(candidate_id) or {}
        consequence = _mapping(consequences.get(candidate_id))
        score_entry = _mapping(candidate_scores.get(candidate_id))
        constraint_entries = [
            record
            for record in _list(constraint_evaluations)
            if isinstance(record, Mapping) and _string(record.get("candidate_id")) == candidate_id
        ]
        veto_entries = [
            record
            for record in _list(veto_events)
            if isinstance(record, Mapping) and _string(record.get("candidate_id")) == candidate_id
        ]
        tradeoff_entries = _candidate_tradeoff_entries(
            candidate_id=candidate_id,
            candidate_payload=item,
            applied_tradeoff_rules=tradeoff_details,
        )
        candidate_decisions.append(
            _build_candidate_decision(
                candidate_payload=item,
                generation_entry=generation_entry,
                consequence=consequence,
                constraint_entries=constraint_entries,
                veto_entries=veto_entries,
                tradeoff_entries=tradeoff_entries,
                selected_candidate_id=selected_candidate_id,
            )
        )
        score_candidates[candidate_id] = _build_score_candidate(
            candidate_payload=item,
            score_entry=score_entry,
            constraint_entries=constraint_entries,
            veto_entries=veto_entries,
            tradeoff_entries=tradeoff_entries,
        )

    if selected_payload is None:
        raise ValueError("trace selected_candidate_id does not match any candidate")

    selected_tradeoff_entries = _candidate_tradeoff_entries(
        candidate_id=selected_candidate_id,
        candidate_payload=selected_payload,
        applied_tradeoff_rules=tradeoff_details,
    )
    selected_veto_entries = [
        record
        for record in _list(veto_events)
        if isinstance(record, Mapping) and _string(record.get("candidate_id")) == selected_candidate_id
    ]
    selected_basis = _build_selected_basis(
        candidate_id=selected_candidate_id,
        score_candidate=_mapping(score_candidates.get(selected_candidate_id)),
        tradeoff_entries=selected_tradeoff_entries,
        veto_entries=selected_veto_entries,
    )

    for candidate in candidate_decisions:
        if candidate["candidate_id"] == selected_candidate_id:
            continue
        why_not_the_others.append(
            _build_why_not_entry(
                candidate=candidate,
                selected_candidate_id=selected_candidate_id,
                selected_score=_mapping(score_candidates.get(selected_candidate_id)),
                candidate_score=_mapping(score_candidates.get(candidate["candidate_id"])),
                selected_tradeoffs=selected_tradeoff_entries,
            )
        )

    recommendation = _mapping(recommendation or {})
    selected_consequence = _mapping(consequences.get(selected_candidate_id))

    payload = {
        "decision_id": decision_id,
        "trace_ref": trace_ref,
        "decision_relevant_state_summary": _build_state_summary(active_context),
        "candidate_decisions": candidate_decisions,
        "score_breakdown": {
            "selection_direction": _string(trace.get("selection_direction")) or "max",
            "candidates": score_candidates,
        },
        "selected_recommendation": {
            "candidate_id": selected_candidate_id,
            "action": _string(selected_payload.get("action")),
            "title": _action_title(_string(selected_payload.get("action"))),
            "selection_reason": _string(trace.get("selection_reason")),
            "decision_basis": selected_basis,
            "human_summary": _string(recommendation.get("human_summary")),
            "reason_summary": _string_list(recommendation.get("reason_summary")),
            "requires_confirmation": bool(trace.get("requires_confirmation", False)),
        },
        "why_not_the_others": why_not_the_others,
        "expected_outcome_or_risk": _expected_effect_from_consequence(selected_consequence),
        "execution_boundary": _build_execution_boundary(
            selected_payload=selected_payload,
            selected_consequence=selected_consequence,
            trace=trace,
        ),
    }
    return normalize_compare_payload(payload)


def _build_state_summary(active_context: Mapping[str, Any]) -> dict[str, Any]:
    commitments = []
    for item in _list(active_context.get("relevant_commitments")):
        if not isinstance(item, Mapping):
            continue
        commitments.append(
            {
                "id": _string(item.get("id")),
                "summary": _string(item.get("summary")),
                "start_time": _string(item.get("start_time")),
                "prep_start_time": _string(item.get("prep_start_time")),
                "priority_hint": _string(item.get("priority_hint")),
                "flexibility_hint": _string(item.get("flexibility_hint")),
                "constraint_hints": _string_list(item.get("constraint_hints")),
            }
        )
    work_items = []
    for item in _list(active_context.get("open_work_items")):
        if not isinstance(item, Mapping):
            continue
        work_items.append(
            {
                "id": _string(item.get("id")),
                "title": _string(item.get("title")),
                "kind": _string(item.get("kind")),
                "repo": _string(item.get("repo")),
                "urgency_hint": _string(item.get("urgency_hint")),
                "estimated_minutes_hint": _number(item.get("estimated_minutes_hint")),
                "requires_attention": bool(item.get("requires_attention", False)),
            }
        )
    conflicts = []
    for item in _list(active_context.get("conflict_facts")):
        if not isinstance(item, Mapping):
            continue
        facts = _mapping(item.get("facts"))
        summary: dict[str, Any] = {
            "type": _string(item.get("type")),
            "severity": _string(item.get("severity")),
        }
        if "available_window_minutes" in facts:
            summary["available_window_minutes"] = _number(facts.get("available_window_minutes"))
        if "estimated_work_minutes" in facts:
            summary["estimated_work_minutes"] = _number(facts.get("estimated_work_minutes"))
        if "executor_available" in facts:
            summary["executor_available"] = bool(facts.get("executor_available"))
        conflicts.append(
            summary
        )
    return {
        "now": _string(active_context.get("now")),
        "available_window_minutes": _number(active_context.get("available_window_minutes")),
        "active_commitments": commitments,
        "open_work_items": work_items,
        "active_conflicts": conflicts,
        "executor_available": bool(active_context.get("executor_available", False)),
    }


def _build_candidate_decision(
    *,
    candidate_payload: Mapping[str, Any],
    generation_entry: Mapping[str, Any],
    consequence: Mapping[str, Any],
    constraint_entries: list[Mapping[str, Any]],
    veto_entries: list[Mapping[str, Any]],
    tradeoff_entries: list[dict[str, Any]],
    selected_candidate_id: str,
) -> dict[str, Any]:
    action = _string(candidate_payload.get("action"))
    enabled_reason = _string(generation_entry.get("enabled_reason"))
    disabled_reason = _string(generation_entry.get("disabled_reason"))
    candidate_id = _string(candidate_payload.get("id"))
    candidate_generation = _mapping(_mapping(candidate_payload.get("params")).get("candidate_generation"))
    return {
        "candidate_id": candidate_id,
        "title": _action_title(action),
        "action": action,
        "intent": _ACTION_INTENTS.get(action, enabled_reason or f"Consider action {action}."),
        "enabled_reason": enabled_reason,
        "disabled_reason": disabled_reason,
        "requires_confirmation": bool(candidate_generation.get("requires_confirmation", False)),
        "key_constraints": [
            _constraint_reason(record)
            for record in constraint_entries
            if _string(record.get("status")) == "fail"
        ],
        "expected_effect": _expected_effect_from_consequence(consequence),
        "vetoes": [_veto_payload(item) for item in veto_entries],
        "tradeoff_rules": tradeoff_entries,
        "is_selected": candidate_id == selected_candidate_id,
    }


def _build_score_candidate(
    *,
    candidate_payload: Mapping[str, Any],
    score_entry: Mapping[str, Any],
    constraint_entries: list[Mapping[str, Any]],
    veto_entries: list[Mapping[str, Any]],
    tradeoff_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    contributions = _mapping(score_entry.get("weighted_contributions"))
    dimensions = []
    for dimension, raw in contributions.items():
        payload = _mapping(raw)
        dimensions.append(
            {
                "dimension": str(dimension),
                "label": _DIMENSION_LABELS.get(str(dimension), str(dimension)),
                "value": _number(payload.get("value")),
                "weight": _number(payload.get("weight")),
                "contribution": _number(payload.get("contribution")),
            }
        )
    dimensions.sort(key=lambda item: item["contribution"], reverse=True)
    return {
        "action": _string(candidate_payload.get("action")),
        "score_total": _number(score_entry.get("score_total")),
        "dimensions": dimensions,
        "constraints": [_constraint_payload(item) for item in constraint_entries],
        "vetoes": [_veto_payload(item) for item in veto_entries],
        "tradeoff_rules": tradeoff_entries,
    }


def _build_selected_basis(
    *,
    candidate_id: str,
    score_candidate: Mapping[str, Any],
    tradeoff_entries: list[dict[str, Any]],
    veto_entries: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    basis: list[dict[str, Any]] = []
    for item in _list(score_candidate.get("dimensions"))[:2]:
        if not isinstance(item, Mapping):
            continue
        contribution = _number(item.get("contribution"))
        if contribution <= 0:
            continue
        basis.append(
            {
                "kind": "weighted_dimension",
                "evidence_source": "score_breakdown",
                "candidate_id": candidate_id,
                "dimension": _string(item.get("dimension")),
                "label": _string(item.get("label")),
                "weight": _number(item.get("weight")),
                "contribution": contribution,
            }
        )
    for item in tradeoff_entries:
        if item.get("status") != "preferred":
            continue
        basis.append(
            {
                "kind": "tradeoff_rule",
                "evidence_source": "tradeoff_rules",
                "candidate_id": candidate_id,
                "rule_id": item.get("rule_id", ""),
                "status": item.get("status", ""),
                "reason": item.get("reason", ""),
            }
        )
    if not veto_entries:
        basis.append(
            {
                "kind": "constraint_clear",
                "evidence_source": "constraints",
                "candidate_id": candidate_id,
                "summary": "No hard-constraint veto was recorded for the selected candidate.",
            }
        )
    return basis


def _build_why_not_entry(
    *,
    candidate: Mapping[str, Any],
    selected_candidate_id: str,
    selected_score: Mapping[str, Any],
    candidate_score: Mapping[str, Any],
    selected_tradeoffs: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_id = _string(candidate.get("candidate_id"))
    reasons: list[dict[str, Any]] = []
    for veto in _list(candidate_score.get("vetoes")):
        if not isinstance(veto, Mapping):
            continue
        reasons.append(
            {
                "kind": "veto",
                "evidence_source": "veto_events",
                "constraint_id": _string(veto.get("constraint_id")),
                "reason": _string(veto.get("reason")),
            }
        )

    if not reasons:
        for item in selected_tradeoffs:
            if item.get("status") != "preferred":
                continue
            reasons.append(
                {
                    "kind": "tradeoff_rule",
                    "evidence_source": "tradeoff_rules",
                    "selected_candidate_id": selected_candidate_id,
                    "rule_id": item.get("rule_id", ""),
                    "reason": item.get("reason", ""),
                }
            )
            break

    if not reasons:
        selected_dimensions = {
            _string(item.get("dimension")): item
            for item in _list(selected_score.get("dimensions"))
            if isinstance(item, Mapping)
        }
        candidate_dimensions = {
            _string(item.get("dimension")): item
            for item in _list(candidate_score.get("dimensions"))
            if isinstance(item, Mapping)
        }
        ranked = []
        for key, selected_dimension in selected_dimensions.items():
            if key not in candidate_dimensions:
                continue
            candidate_dimension = candidate_dimensions[key]
            delta = _number(selected_dimension.get("contribution")) - _number(candidate_dimension.get("contribution"))
            if delta <= 0:
                continue
            ranked.append(
                (
                    delta,
                    {
                        "kind": "weighted_dimension_gap",
                        "evidence_source": "score_breakdown",
                        "dimension": key,
                        "label": _string(selected_dimension.get("label")) or key,
                        "selected_contribution": _number(selected_dimension.get("contribution")),
                        "candidate_contribution": _number(candidate_dimension.get("contribution")),
                        "weight": _number(selected_dimension.get("weight")),
                    },
                )
            )
        ranked.sort(key=lambda item: item[0], reverse=True)
        reasons.extend(reason for _, reason in ranked[:2])

    return {
        "candidate_id": candidate_id,
        "title": _string(candidate.get("title")),
        "reasons": reasons,
    }


def _build_execution_boundary(
    *,
    selected_payload: Mapping[str, Any],
    selected_consequence: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> dict[str, Any]:
    action = _string(selected_payload.get("action"))
    consequence_metadata = _mapping(selected_consequence.get("metadata"))
    requires_confirmation = bool(trace.get("requires_confirmation", False))
    path = "Decision boundary only"
    executor = ""
    if action == "delegate_to_executor":
        executor = _string(consequence_metadata.get("executor")) or "external executor"
        path = "SDEP -> Hermes/Codex"
    return {
        "selected_action": action,
        "requires_confirmation": requires_confirmation,
        "execution_path": path,
        "executor": executor,
        "note": "Execution is downstream of decision selection and is shown separately from the compare object.",
    }


def _constraint_reason(record: Mapping[str, Any]) -> str:
    return _string(record.get("rule")) or _string(record.get("constraint_id"))


def _constraint_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "constraint_id": _string(record.get("constraint_id")),
        "status": _string(record.get("status")) or "unknown",
        "severity": _string(record.get("severity")) or "unknown",
        "rule": _string(record.get("rule")),
        "supported": bool(record.get("supported", False)),
    }


def _veto_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "constraint_id": _string(record.get("constraint_id")),
        "reason": _string(record.get("reason")),
        "status": _string(record.get("status")) or "fail",
    }


def _candidate_tradeoff_entries(
    *,
    candidate_id: str,
    candidate_payload: Mapping[str, Any],
    applied_tradeoff_rules: Any,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    candidate_params = _mapping(candidate_payload.get("params"))
    candidate_rule_results = _mapping(candidate_params.get("tradeoff_rule_results"))
    for rule_id, rule_payload in candidate_rule_results.items():
        item = _mapping(rule_payload)
        result.append(
            {
                "rule_id": str(rule_id),
                "status": _string(item.get("status")) or "unknown",
                "reason": _string(item.get("reason")),
                "applied_to_selected": False,
            }
        )
    for item in _list(applied_tradeoff_rules):
        if not isinstance(item, Mapping):
            continue
        selected_ids = _string_list(item.get("selected_candidate_ids"))
        if candidate_id not in selected_ids:
            continue
        rule_id = _string(item.get("rule_id"))
        existing = next((entry for entry in result if entry["rule_id"] == rule_id), None)
        if existing is not None:
            existing["applied_to_selected"] = True
            if not existing["status"] or existing["status"] == "unknown":
                existing["status"] = _string(item.get("status")) or "applied"
            continue
        result.append(
            {
                "rule_id": rule_id,
                "status": _string(item.get("status")) or "applied",
                "reason": _string(item.get("reason")),
                "applied_to_selected": True,
            }
        )
    result.sort(key=lambda entry: entry["rule_id"])
    return result


def _expected_effect_from_consequence(consequence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "expected_time_cost_minutes": _number(consequence.get("expected_time_cost_minutes")),
        "commitment_risk": _string(consequence.get("commitment_risk")),
        "work_item_risk_change": _string(consequence.get("work_item_risk_change")),
        "followup_needed": bool(consequence.get("followup_needed", False)),
        "followup_summary": _string(consequence.get("followup_summary")),
        "reversibility": _string(consequence.get("reversibility")),
        "attention_cost": _string(consequence.get("attention_cost")),
    }


def _normalize_state_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "now": _string(value.get("now")),
        "available_window_minutes": _number(value.get("available_window_minutes")),
        "active_commitments": [_mapping(item) for item in _list(value.get("active_commitments"))],
        "open_work_items": [_mapping(item) for item in _list(value.get("open_work_items"))],
        "active_conflicts": [_mapping(item) for item in _list(value.get("active_conflicts"))],
        "executor_available": bool(value.get("executor_available", False)),
    }


def _normalize_candidate(value: Any) -> dict[str, Any]:
    item = _mapping(value)
    return {
        "candidate_id": _string(item.get("candidate_id")),
        "title": _string(item.get("title")),
        "action": _string(item.get("action")),
        "intent": _string(item.get("intent")),
        "enabled_reason": _string(item.get("enabled_reason")),
        "disabled_reason": _string(item.get("disabled_reason")),
        "requires_confirmation": bool(item.get("requires_confirmation", False)),
        "key_constraints": _string_list(item.get("key_constraints")),
        "expected_effect": _normalize_expected_effect(item.get("expected_effect", {})),
        "vetoes": [_mapping(entry) for entry in _list(item.get("vetoes"))],
        "tradeoff_rules": [_mapping(entry) for entry in _list(item.get("tradeoff_rules"))],
        "is_selected": bool(item.get("is_selected", False)),
    }


def _normalize_score_breakdown(value: Mapping[str, Any]) -> dict[str, Any]:
    candidates = {}
    raw_candidates = _mapping(value.get("candidates"))
    for candidate_id, entry in raw_candidates.items():
        item = _mapping(entry)
        dimensions = []
        for dimension in _list(item.get("dimensions")):
            raw = _mapping(dimension)
            dimensions.append(
                {
                    "dimension": _string(raw.get("dimension")),
                    "label": _string(raw.get("label")),
                    "value": _number(raw.get("value")),
                    "weight": _number(raw.get("weight")),
                    "contribution": _number(raw.get("contribution")),
                }
            )
        candidates[str(candidate_id)] = {
            "action": _string(item.get("action")),
            "score_total": _number(item.get("score_total")),
            "dimensions": dimensions,
            "constraints": [_mapping(entry) for entry in _list(item.get("constraints"))],
            "vetoes": [_mapping(entry) for entry in _list(item.get("vetoes"))],
            "tradeoff_rules": [_mapping(entry) for entry in _list(item.get("tradeoff_rules"))],
        }
    return {
        "selection_direction": _string(value.get("selection_direction")) or "max",
        "candidates": candidates,
    }


def _normalize_selected_recommendation(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": _string(value.get("candidate_id")),
        "action": _string(value.get("action")),
        "title": _string(value.get("title")),
        "selection_reason": _string(value.get("selection_reason")),
        "decision_basis": [_mapping(item) for item in _list(value.get("decision_basis"))],
        "human_summary": _string(value.get("human_summary")),
        "reason_summary": _string_list(value.get("reason_summary")),
        "requires_confirmation": bool(value.get("requires_confirmation", False)),
    }


def _normalize_why_not(value: Any) -> dict[str, Any]:
    item = _mapping(value)
    return {
        "candidate_id": _string(item.get("candidate_id")),
        "title": _string(item.get("title")),
        "reasons": [_mapping(reason) for reason in _list(item.get("reasons"))],
    }


def _normalize_expected_effect(value: Any) -> dict[str, Any]:
    item = _mapping(value)
    return {
        "expected_time_cost_minutes": _number(item.get("expected_time_cost_minutes")),
        "commitment_risk": _string(item.get("commitment_risk")),
        "work_item_risk_change": _string(item.get("work_item_risk_change")),
        "followup_needed": bool(item.get("followup_needed", False)),
        "followup_summary": _string(item.get("followup_summary")),
        "reversibility": _string(item.get("reversibility")),
        "attention_cost": _string(item.get("attention_cost")),
    }


def _normalize_execution_boundary(value: Any) -> dict[str, Any]:
    item = _mapping(value)
    return {
        "selected_action": _string(item.get("selected_action")),
        "requires_confirmation": bool(item.get("requires_confirmation", False)),
        "execution_path": _string(item.get("execution_path")),
        "executor": _string(item.get("executor")),
        "note": _string(item.get("note")),
    }


def _normalize_outcome_return(value: Any) -> dict[str, Any]:
    item = _mapping(value)
    return {
        "observation_type": _string(item.get("observation_type")),
        "note": _string(item.get("note")),
    }


def _validate_candidate_alignment(payload: Mapping[str, Any]) -> None:
    candidate_ids = {
        _string(item.get("candidate_id"))
        for item in _list(payload.get("candidate_decisions"))
        if isinstance(item, Mapping)
    }
    score_candidate_ids = set(_mapping(_mapping(payload.get("score_breakdown")).get("candidates")).keys())
    selected_candidate_id = _string(_mapping(payload.get("selected_recommendation")).get("candidate_id"))
    if not candidate_ids:
        raise ValueError("compare payload requires at least one candidate_decision")
    if candidate_ids != score_candidate_ids:
        raise ValueError("candidate_decisions and score_breakdown.candidates are misaligned")
    if selected_candidate_id not in candidate_ids:
        raise ValueError("selected_recommendation.candidate_id must reference a known candidate")


def _action_title(action: str) -> str:
    return _ACTION_TITLES.get(action, action.replace("_", " ").title())


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _string(value: Any) -> str:
    return str(value) if value is not None else ""


def _number(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]
