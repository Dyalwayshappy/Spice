from __future__ import annotations

from pathlib import Path
from typing import Any

from spice.decision.guidance import (
    DecisionGuidance,
    DecisionGuidanceSupport,
    GuidanceValidationIssue,
    TradeoffRuleGuidance,
    _dedupe_issues,
    _executable_rule_supported,
    issues_payload,
    load_decision_guidance,
    validate_decision_guidance_support,
    validation_summary_payload,
)


RUNTIME_ACTIVE_SECTIONS = (
    "Primary Objective",
    "Preferences / Weights",
    "Hard Constraints",
    "Trade-off Rules",
)

RUNTIME_INACTIVE_SECTIONS = (
    "Decision Principles",
    "Evaluation Criteria",
    "Reflection Guidance",
)

PARSE_ONLY_SECTIONS = ("Version / Metadata",)

NOT_PARSED_RUNTIME_SECTIONS = (
    "Decision Scope",
    "Secondary Objectives",
    "Soft Constraints",
    "Risk Budget",
)

SUPPORTED_TRADEOFF_RULE_SUBSET = {
    "when": [
        "always",
        "never",
        "candidates differ on <scoring_dimension>",
        "all candidates have <scoring_dimension>",
        "any action in [<action>, <action>]",
    ],
    "enforce": [
        "prefer higher <scoring_dimension>",
        "prefer lower <scoring_dimension>",
        "prefer higher score_total",
        "prefer lower risk",
        "prefer higher confidence",
        "prefer action in [<action>, <action>]",
    ],
    "unless": [
        "never",
        "<supported when condition>",
    ],
}


def describe_decision_guidance_support(
    support_or_policy: DecisionGuidanceSupport | dict[str, Any] | Any | None = None,
) -> dict[str, Any]:
    support = _resolve_support(support=support_or_policy)
    return {
        "declared": _support_declared(support),
        **support.to_payload(),
    }


def explain_decision_guidance(
    guidance_or_path: DecisionGuidance | str | Path,
    *,
    support: DecisionGuidanceSupport | dict[str, Any] | Any | None = None,
) -> dict[str, Any]:
    guidance = (
        guidance_or_path
        if isinstance(guidance_or_path, DecisionGuidance)
        else load_decision_guidance(guidance_or_path)
    )
    resolved_support = _resolve_support(support=support)
    support_issues = validate_decision_guidance_support(guidance, resolved_support)
    issues = _dedupe_issues([*guidance.validation_issues, *support_issues])
    validation = validation_summary_payload(issues)

    return {
        "artifact": {
            "artifact_id": guidance.artifact_id,
            "schema_version": guidance.schema_version,
            "artifact_version": guidance.artifact_version,
            "status": guidance.status,
            "source_path": guidance.source_path,
            "source_hash": guidance.source_hash,
        },
        "validation": validation,
        "sections": {
            "runtime_active": list(RUNTIME_ACTIVE_SECTIONS),
            "runtime_inactive": list(RUNTIME_INACTIVE_SECTIONS),
            "parse_only": list(PARSE_ONLY_SECTIONS),
            "not_parsed_for_runtime_v1": list(NOT_PARSED_RUNTIME_SECTIONS),
        },
        "support_contract": describe_decision_guidance_support(resolved_support),
        "active_guidance": {
            "primary_objective": {
                "text": guidance.primary_objective.text,
                "direction": guidance.primary_objective.direction,
                "runtime_effect": (
                    "sets guided score comparison direction"
                    if guidance.primary_objective.text
                    else "missing"
                ),
            },
            "weights": _weights_payload(guidance, resolved_support),
            "hard_constraints": _constraints_payload(guidance, resolved_support),
            "tradeoff_rules": _tradeoff_rules_payload(guidance, resolved_support),
        },
        "unsupported": _unsupported_payload(issues),
        "executable_tradeoff_subset": SUPPORTED_TRADEOFF_RULE_SUBSET,
        "selection_effect": {
            "primary_objective": "Primary Objective influences max/min comparison only in v1.",
            "weights": "Preferences / Weights recompute candidate score_total from declared dimensions.",
            "hard_constraints": "Hard Constraints can veto candidates only when matching candidate constraint checks are available.",
            "tradeoff_rules": "Trade-off Rules execute only when they match the constrained subset or are explicitly supported by candidate rule results.",
            "inactive_sections": "Decision Principles, Evaluation Criteria, and Reflection Guidance are not runtime-active in v1.",
        },
    }


def format_decision_guidance_explanation(report: dict[str, Any]) -> str:
    artifact = report.get("artifact", {})
    validation = report.get("validation", {})
    counts = validation.get("issue_counts", {})
    support = report.get("support_contract", {})
    sections = report.get("sections", {})
    active = report.get("active_guidance", {})
    unsupported = report.get("unsupported", {})

    lines = [
        "decision.md explain",
        f"artifact_id: {artifact.get('artifact_id') or '(missing)'}",
        f"schema_version: {artifact.get('schema_version') or '(missing)'}",
        f"artifact_version: {artifact.get('artifact_version') or '(missing)'}",
        (
            "validation_status: "
            f"{validation.get('status', 'unknown')} "
            f"(errors={counts.get('errors', 0)}, "
            f"warnings={counts.get('warnings', 0)}, "
            f"unsupported={counts.get('unsupported', 0)})"
        ),
        "",
        "runtime-active sections:",
        _list_line(sections.get("runtime_active", [])),
        "runtime-inactive sections:",
        _list_line(sections.get("runtime_inactive", [])),
        "parse-only sections:",
        _list_line(sections.get("parse_only", [])),
        "",
        "support contract:",
        f"  declared: {bool(support.get('declared'))}",
        f"  score_dimensions: {_inline_list(support.get('score_dimensions', []))}",
        f"  constraint_ids: {_inline_list(support.get('constraint_ids', []))}",
        f"  tradeoff_rule_ids: {_inline_list(support.get('tradeoff_rule_ids', []))}",
        "",
        "selection influence:",
        f"  primary_objective: {active.get('primary_objective', {}).get('runtime_effect', 'unknown')}",
        f"  weights: {len(active.get('weights', []))} dimensions",
        f"  hard_constraints: {len(active.get('hard_constraints', []))} constraints",
        f"  tradeoff_rules: {len(active.get('tradeoff_rules', []))} rules",
        "",
        "unsupported runtime semantics:",
        f"  score_dimensions: {_inline_list(unsupported.get('score_dimensions', []))}",
        f"  constraint_ids: {_inline_list(unsupported.get('constraint_ids', []))}",
        f"  tradeoff_rules: {_inline_list(unsupported.get('tradeoff_rules', []))}",
    ]

    issues = validation.get("issues", [])
    if issues:
        lines.extend(["", "validation issues:"])
        for issue in issues:
            action = issue.get("action", "")
            suffix = f" action={action}" if action else ""
            lines.append(
                "  "
                f"[{issue.get('severity')}] "
                f"{issue.get('section')}: "
                f"{issue.get('code')} - "
                f"{issue.get('message')}"
                f"{suffix}"
            )

    return "\n".join(lines)


def _resolve_support(
    *,
    support: DecisionGuidanceSupport | dict[str, Any] | Any | None = None,
) -> DecisionGuidanceSupport:
    if isinstance(support, DecisionGuidanceSupport):
        return support
    if isinstance(support, dict):
        return DecisionGuidanceSupport.from_dict(support)
    if support is not None:
        return DecisionGuidanceSupport.from_policy(support)
    return DecisionGuidanceSupport()


def _support_declared(support: DecisionGuidanceSupport) -> bool:
    return bool(
        support.score_dimensions
        or support.constraint_ids
        or support.tradeoff_rule_ids
    )


def _weights_payload(
    guidance: DecisionGuidance,
    support: DecisionGuidanceSupport,
) -> list[dict[str, Any]]:
    return [
        {
            "dimension": dimension,
            "weight": float(weight),
            "description": guidance.weight_descriptions.get(dimension, ""),
            "supported": (
                dimension in support.score_dimensions
                if support.score_dimensions
                else None
            ),
        }
        for dimension, weight in guidance.weights.items()
    ]


def _constraints_payload(
    guidance: DecisionGuidance,
    support: DecisionGuidanceSupport,
) -> list[dict[str, Any]]:
    return [
        {
            "id": constraint.id,
            "severity": constraint.severity,
            "rule": constraint.rule,
            "supported": (
                constraint.id in support.constraint_ids
                if support.constraint_ids
                else None
            ),
        }
        for constraint in guidance.hard_constraints
    ]


def _tradeoff_rules_payload(
    guidance: DecisionGuidance,
    support: DecisionGuidanceSupport,
) -> list[dict[str, Any]]:
    return [_tradeoff_rule_payload(rule, support) for rule in guidance.tradeoff_rules]


def _tradeoff_rule_payload(
    rule: TradeoffRuleGuidance,
    support: DecisionGuidanceSupport,
) -> dict[str, Any]:
    supported_by_subset = False
    unsupported_reason = ""
    if rule.executable:
        supported_by_subset, unsupported_reason = _executable_rule_supported(rule, support)

    supported_by_adapter = rule.id in support.tradeoff_rule_ids
    if supported_by_subset:
        runtime_support = "executable_subset"
    elif supported_by_adapter:
        runtime_support = "policy_or_candidate_result"
    else:
        runtime_support = "unsupported"

    return {
        "id": rule.id,
        "priority": rule.priority,
        "when": rule.when,
        "enforce": rule.enforce,
        "unless": rule.unless,
        "runtime_support": runtime_support,
        "executable_subset": bool(rule.executable),
        "supported_by_adapter": supported_by_adapter,
        "unsupported_reason": unsupported_reason,
    }


def _unsupported_payload(
    issues: list[GuidanceValidationIssue],
) -> dict[str, list[str]]:
    score_dimensions: set[str] = set()
    constraint_ids: set[str] = set()
    tradeoff_rules: set[str] = set()

    for issue in issues:
        if issue.severity != "unsupported":
            continue
        if issue.code == "unsupported_score_dimension":
            dimension = issue.details.get("dimension")
            if dimension:
                score_dimensions.add(str(dimension))
        elif issue.code == "unsupported_constraint_id":
            constraint_id = issue.details.get("constraint_id")
            if constraint_id:
                constraint_ids.add(str(constraint_id))
        elif issue.code == "unsupported_tradeoff_rule":
            rule_id = issue.details.get("rule_id")
            if rule_id:
                tradeoff_rules.add(str(rule_id))

    return {
        "score_dimensions": sorted(score_dimensions),
        "constraint_ids": sorted(constraint_ids),
        "tradeoff_rules": sorted(tradeoff_rules),
    }


def _list_line(values: list[Any]) -> str:
    return "  " + _inline_list(values)


def _inline_list(values: list[Any]) -> str:
    return ", ".join(str(value) for value in values) if values else "(none)"
