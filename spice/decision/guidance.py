from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from spice.decision.core import (
    CandidateDecision,
    DecisionObjective,
    DecisionPolicy,
    PolicyIdentity,
    SafetyConstraint,
)
from spice.protocols import Decision


@dataclass(slots=True)
class PrimaryObjectiveGuidance:
    text: str = ""
    direction: str = "unknown"


@dataclass(slots=True)
class HardConstraintGuidance:
    id: str
    rule: str
    severity: str = "veto"


@dataclass(slots=True)
class TradeoffRuleGuidance:
    id: str
    when: str
    enforce: str
    unless: str = ""
    priority: int | None = None
    executable: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GuidanceValidationIssue:
    severity: str
    section: str
    code: str
    message: str
    action: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity,
            "section": self.section,
            "code": self.code,
            "message": self.message,
        }
        if self.action:
            payload["action"] = self.action
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass(slots=True)
class DecisionGuidanceSupport:
    """Bounded runtime contract exposed by a decision policy or domain adapter."""

    score_dimensions: set[str] = field(default_factory=set)
    constraint_ids: set[str] = field(default_factory=set)
    tradeoff_rule_ids: set[str] = field(default_factory=set)

    @classmethod
    def from_policy(cls, policy: Any) -> "DecisionGuidanceSupport":
        declared = getattr(policy, "decision_guidance_support", None)
        if isinstance(declared, DecisionGuidanceSupport):
            return declared
        if callable(declared):
            resolved = declared()
            if isinstance(resolved, DecisionGuidanceSupport):
                return resolved
            if isinstance(resolved, dict):
                return cls.from_dict(resolved)
        if isinstance(declared, dict):
            return cls.from_dict(declared)

        return cls(
            score_dimensions=set(getattr(policy, "supported_score_dimensions", []) or []),
            constraint_ids=set(getattr(policy, "supported_constraint_ids", []) or []),
            tradeoff_rule_ids=set(getattr(policy, "supported_tradeoff_rule_ids", []) or []),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DecisionGuidanceSupport":
        return cls(
            score_dimensions={str(item) for item in payload.get("score_dimensions", [])},
            constraint_ids={str(item) for item in payload.get("constraint_ids", [])},
            tradeoff_rule_ids={str(item) for item in payload.get("tradeoff_rule_ids", [])},
        )

    def to_payload(self) -> dict[str, list[str]]:
        return {
            "score_dimensions": sorted(self.score_dimensions),
            "constraint_ids": sorted(self.constraint_ids),
            "tradeoff_rule_ids": sorted(self.tradeoff_rule_ids),
        }


@dataclass(slots=True)
class DecisionGuidance:
    source_path: str = ""
    source_hash: str = ""
    artifact_id: str = ""
    schema_version: str = ""
    artifact_version: str = ""
    status: str = ""
    primary_objective: PrimaryObjectiveGuidance = field(
        default_factory=PrimaryObjectiveGuidance
    )
    weights: dict[str, float] = field(default_factory=dict)
    weight_descriptions: dict[str, str] = field(default_factory=dict)
    hard_constraints: list[HardConstraintGuidance] = field(default_factory=list)
    tradeoff_rules: list[TradeoffRuleGuidance] = field(default_factory=list)
    rule_priority: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    validation_issues: list[GuidanceValidationIssue] = field(default_factory=list)

    def provenance_metadata(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "schema_version": self.schema_version,
            "artifact_version": self.artifact_version,
            "status": self.status,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "primary_objective": asdict(self.primary_objective),
            "weights": dict(self.weights),
            "hard_constraints": [constraint.id for constraint in self.hard_constraints],
            "tradeoff_rules": [rule.id for rule in self.tradeoff_rules],
            "rule_priority": list(self.rule_priority),
            "warnings": list(self.warnings),
            "validation_status": validation_status(self.validation_issues),
            "validation_issues": issues_payload(self.validation_issues),
        }

    def to_safety_constraints(self) -> list[SafetyConstraint]:
        return [
            SafetyConstraint(
                name=constraint.id,
                kind="decision_guidance.veto",
                params={
                    "rule": constraint.rule,
                    "severity": constraint.severity,
                    "artifact_id": self.artifact_id,
                    "source_hash": self.source_hash,
                },
            )
            for constraint in self.hard_constraints
        ]


def load_decision_guidance(path: str | Path) -> DecisionGuidance:
    source = Path(path)
    return parse_decision_guidance(
        source.read_text(encoding="utf-8"),
        source_path=str(source),
    )


def validation_status(issues: list[GuidanceValidationIssue]) -> str:
    severities = {issue.severity for issue in issues}
    if "error" in severities:
        return "invalid"
    if "unsupported" in severities:
        return "partially_supported"
    if "warning" in severities:
        return "parsed_with_warnings"
    return "valid"


def issues_payload(issues: list[GuidanceValidationIssue]) -> list[dict[str, Any]]:
    return [issue.to_payload() for issue in issues]


def validation_summary_payload(
    issues: list[GuidanceValidationIssue],
) -> dict[str, Any]:
    issues = _dedupe_issues(issues)
    return {
        "status": validation_status(issues),
        "issue_counts": {
            "errors": sum(1 for issue in issues if issue.severity == "error"),
            "warnings": sum(1 for issue in issues if issue.severity == "warning"),
            "unsupported": sum(1 for issue in issues if issue.severity == "unsupported"),
        },
        "issues": issues_payload(issues),
    }


def _dedupe_issues(
    issues: list[GuidanceValidationIssue],
) -> list[GuidanceValidationIssue]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[GuidanceValidationIssue] = []
    for issue in issues:
        key = (
            issue.severity,
            issue.section,
            issue.code,
            str(issue.details.get("rule_id") or issue.details.get("dimension") or issue.details.get("constraint_id") or issue.message),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def validate_decision_guidance_support(
    guidance: DecisionGuidance,
    support: DecisionGuidanceSupport,
) -> list[GuidanceValidationIssue]:
    issues: list[GuidanceValidationIssue] = []

    if guidance.weights and not support.score_dimensions:
        _add_issue(
            issues,
            [],
            severity="warning",
            section="Preferences / Weights",
            code="score_dimension_contract_missing",
            message="The active policy did not declare supported score dimensions.",
            action="Expose decision_guidance_support.score_dimensions on the policy or domain adapter.",
        )
    for dimension in guidance.weights:
        if support.score_dimensions and dimension not in support.score_dimensions:
            _add_issue(
                issues,
                [],
                severity="unsupported",
                section="Preferences / Weights",
                code="unsupported_score_dimension",
                message=f"Weight dimension '{dimension}' is not declared by the active policy.",
                action="Use a supported score dimension or add it to the policy score dimension contract.",
                details={
                    "dimension": dimension,
                    "supported_score_dimensions": sorted(support.score_dimensions),
                },
            )

    if guidance.hard_constraints and not support.constraint_ids:
        _add_issue(
            issues,
            [],
            severity="warning",
            section="Hard Constraints",
            code="constraint_contract_missing",
            message="The active policy did not declare supported hard constraint ids.",
            action="Expose decision_guidance_support.constraint_ids on the policy or domain adapter.",
        )
    for constraint in guidance.hard_constraints:
        if support.constraint_ids and constraint.id not in support.constraint_ids:
            _add_issue(
                issues,
                [],
                severity="unsupported",
                section="Hard Constraints",
                code="unsupported_constraint_id",
                message=f"Hard constraint '{constraint.id}' is not declared by the active policy.",
                action="Use a supported constraint id or add a matching constraint check.",
                details={
                    "constraint_id": constraint.id,
                    "supported_constraint_ids": sorted(support.constraint_ids),
                },
            )

    for rule in guidance.tradeoff_rules:
        if rule.executable:
            supported, reason = _executable_rule_supported(rule, support)
            if not supported:
                _add_issue(
                    issues,
                    [],
                    severity="unsupported",
                    section="Trade-off Rules",
                    code="unsupported_tradeoff_rule",
                    message=f"Trade-off rule '{rule.id}' cannot execute against the active policy contract.",
                    action="Use supported score dimensions/candidate fields or simplify the rule.",
                    details={"rule_id": rule.id, "reason": reason},
                )
            continue
        if rule.id in support.tradeoff_rule_ids:
            continue
        _add_issue(
            issues,
            [],
            severity="unsupported",
            section="Trade-off Rules",
            code="unsupported_tradeoff_rule",
            message=f"Trade-off rule '{rule.id}' is not executable by the supported subset.",
            action="Use supported syntax or have the policy provide a candidate tradeoff_rule_results entry.",
            details={"rule_id": rule.id},
        )

    return issues


def parse_decision_guidance(text: str, *, source_path: str = "") -> DecisionGuidance:
    warnings: list[str] = []
    issues: list[GuidanceValidationIssue] = []
    sections = _split_sections(text)
    source_hash = sha256(text.encode("utf-8")).hexdigest()

    metadata = _parse_version_metadata(
        sections.get("Version / Metadata", ""),
        warnings,
        issues,
    )
    objective = _parse_primary_objective(
        sections.get("Primary Objective", ""),
        warnings,
        issues,
    )
    weights, descriptions = _parse_weights(
        sections.get("Preferences / Weights", ""),
        warnings,
        issues,
    )
    hard_constraints = _parse_hard_constraints(
        sections.get("Hard Constraints", ""),
        warnings,
        issues,
    )
    rule_priority, tradeoff_rules = _parse_tradeoff_rules(
        sections.get("Trade-off Rules", ""),
        warnings,
        issues,
    )

    return DecisionGuidance(
        source_path=source_path,
        source_hash=source_hash,
        artifact_id=metadata.get("artifact_id", ""),
        schema_version=metadata.get("schema_version", ""),
        artifact_version=metadata.get("artifact_version", ""),
        status=metadata.get("status", ""),
        primary_objective=objective,
        weights=weights,
        weight_descriptions=descriptions,
        hard_constraints=hard_constraints,
        tradeoff_rules=tradeoff_rules,
        rule_priority=rule_priority,
        metadata=metadata,
        warnings=warnings,
        validation_issues=issues,
    )


class GuidedDecisionPolicy:
    """Apply bounded decision.md guidance around an existing candidate policy."""

    def __init__(
        self,
        base_policy: DecisionPolicy,
        guidance: DecisionGuidance,
        support: DecisionGuidanceSupport | None = None,
    ) -> None:
        self.base_policy = base_policy
        self.guidance = guidance
        self.support = support or DecisionGuidanceSupport.from_policy(base_policy)
        self.support_issues = validate_decision_guidance_support(
            guidance,
            self.support,
        )
        base_identity = base_policy.identity
        self.identity = PolicyIdentity.create(
            policy_name=f"{base_identity.policy_name}.guided",
            policy_version=base_identity.policy_version,
            implementation_fingerprint=(
                f"{base_identity.resolved_hash()}:{guidance.source_hash}"
            ),
        )

    def propose(self, state: Any, context: Any) -> list[CandidateDecision]:
        return self.base_policy.propose(state, context)

    def select(
        self,
        candidates: list[CandidateDecision],
        objective: DecisionObjective,
        constraints: list[SafetyConstraint],
    ) -> Decision:
        if not candidates:
            raise ValueError("At least one candidate is required for guided selection.")

        scored = [self._score_candidate(candidate) for candidate in candidates]
        veto_events: list[dict[str, Any]] = []
        constraint_evaluations: list[dict[str, Any]] = []
        eligible: list[CandidateDecision] = []

        for candidate in scored:
            results = self._constraint_results(candidate)
            constraint_evaluations.extend(results)
            failed = [
                result
                for result in results
                if result["status"] == "fail" and result["severity"] == "veto"
            ]
            if failed:
                for result in failed:
                    veto_events.append(
                        {
                            "candidate_id": candidate.id,
                            "constraint_id": result["constraint_id"],
                            "constraint_name": result["constraint_id"],
                            "status": "fail",
                            "reason": result["rule"],
                            "source": "decision_guidance",
                            "artifact_id": self.guidance.artifact_id,
                        }
                    )
                continue
            eligible.append(candidate)

        selection_pool = eligible or scored
        (
            applied_rules,
            applied_rule_details,
            unsupported_rule_details,
            selection_pool,
        ) = self._apply_tradeoff_rules(selection_pool)
        unsupported_rules = [
            str(detail["rule_id"]) for detail in unsupported_rule_details
        ]
        selected = self._select_by_direction(selection_pool)
        guidance_metadata = self.guidance.provenance_metadata()
        validation_issues = [
            *self.guidance.validation_issues,
            *self.support_issues,
            *_runtime_validation_issues(
                scored,
                constraint_evaluations,
                unsupported_rule_details,
            ),
        ]
        validation_summary = validation_summary_payload(validation_issues)
        explanation = self._explanation_payload(
            selected=selected,
            scored=scored,
            constraint_evaluations=constraint_evaluations,
            veto_events=veto_events,
            applied_rule_details=applied_rule_details,
            unsupported_rule_details=unsupported_rule_details,
            validation_summary=validation_summary,
        )
        all_constraints = [*constraints, *self.guidance.to_safety_constraints()]

        return Decision(
            id=f"decision.guided.{selected.id}",
            decision_type="decision_guidance.policy_decision",
            status="proposed",
            selected_action=selected.action,
            metadata={
                "decision_guidance": guidance_metadata,
                "decision_guidance_support": self.support.to_payload(),
                "decision_guidance_validation": validation_summary,
                "decision_guidance_explanation": explanation,
                "constraints_used": [_constraint_payload(item) for item in all_constraints],
                "applied_tradeoff_rules": applied_rules,
                "applied_tradeoff_rule_details": applied_rule_details,
                "unsupported_tradeoff_rules": unsupported_rules,
                "unsupported_tradeoff_rule_details": unsupported_rule_details,
            },
            attributes={
                "selected_candidate_id": selected.id,
                "all_candidates": [_candidate_payload(candidate) for candidate in scored],
                "veto_events": veto_events,
                "objective_used": {
                    "primary_objective": asdict(self.guidance.primary_objective),
                    "selection_direction": self._selection_direction(),
                },
                "decision_guidance": guidance_metadata,
                "decision_guidance_support": self.support.to_payload(),
                "decision_guidance_validation": validation_summary,
                "decision_guidance_explanation": explanation,
                "applied_tradeoff_rules": applied_rules,
                "applied_tradeoff_rule_details": applied_rule_details,
                "unsupported_tradeoff_rules": unsupported_rules,
                "unsupported_tradeoff_rule_details": unsupported_rule_details,
                "policy_name": self.identity.policy_name,
                "policy_version": self.identity.policy_version,
                "policy_hash": self.identity.resolved_hash(),
            },
        )

    def _score_candidate(self, candidate: CandidateDecision) -> CandidateDecision:
        if not self.guidance.weights:
            return candidate

        weighted_score = 0.0
        missing_dimensions: list[str] = []
        contributions: dict[str, dict[str, float]] = {}
        original_score = float(candidate.score_total)
        for dimension, weight in self.guidance.weights.items():
            value = float(candidate.score_breakdown.get(dimension, 0.0))
            if dimension not in candidate.score_breakdown:
                missing_dimensions.append(dimension)
            contribution = float(weight) * value
            contributions[dimension] = {
                "weight": float(weight),
                "value": value,
                "contribution": contribution,
            }
            weighted_score += contribution

        params = dict(candidate.params)
        params["decision_guidance_score"] = {
            "source": "decision_guidance",
            "original_score_total": original_score,
            "weighted_score_total": weighted_score,
            "weighted_dimensions": dict(self.guidance.weights),
            "contributions": contributions,
            "missing_dimensions": missing_dimensions,
        }
        candidate.score_total = weighted_score
        candidate.params = params
        return candidate

    def _constraint_results(
        self,
        candidate: CandidateDecision,
    ) -> list[dict[str, Any]]:
        checks = candidate.params.get("constraint_checks")
        checks_dict = checks if isinstance(checks, dict) else {}
        results: list[dict[str, Any]] = []
        for constraint in self.guidance.hard_constraints:
            status = _constraint_status(checks_dict.get(constraint.id))
            results.append(
                {
                    "candidate_id": candidate.id,
                    "constraint_id": constraint.id,
                    "status": status,
                    "severity": constraint.severity,
                    "rule": constraint.rule,
                    "supported": (
                        constraint.id in self.support.constraint_ids
                        if self.support.constraint_ids
                        else None
                    ),
                }
            )
        return results

    def _apply_tradeoff_rules(
        self,
        candidates: list[CandidateDecision],
    ) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]], list[CandidateDecision]]:
        if len(candidates) <= 1:
            return [], [], [], candidates

        by_id = {rule.id: rule for rule in self.guidance.tradeoff_rules}
        ordered_ids = [
            rule_id
            for rule_id in self.guidance.rule_priority
            if rule_id != "hard constraints" and rule_id in by_id
        ]
        for rule in self.guidance.tradeoff_rules:
            if rule.id not in ordered_ids:
                ordered_ids.append(rule.id)

        applied: list[str] = []
        applied_details: list[dict[str, Any]] = []
        unsupported_details: list[dict[str, Any]] = []
        current = list(candidates)

        for rule_id in ordered_ids:
            rule = by_id[rule_id]
            executed = self._execute_tradeoff_rule(rule, current)
            if executed["status"] == "applied":
                applied.append(rule_id)
                applied_details.append(executed)
                current = [
                    candidate
                    for candidate in current
                    if candidate.id in set(executed["selected_candidate_ids"])
                ]
                if len(current) == 1:
                    break
                continue
            if executed["status"] == "unsupported":
                pending_unsupported = executed
            else:
                pending_unsupported = None
            if executed["status"] == "not_applicable":
                continue

            preferred = [
                candidate
                for candidate in current
                if _tradeoff_status(candidate, rule_id) == "preferred"
            ]
            if preferred:
                applied.append(rule_id)
                applied_details.append(
                    {
                        "rule_id": rule_id,
                        "status": "applied",
                        "mode": "candidate_annotation",
                        "selected_candidate_ids": [candidate.id for candidate in preferred],
                    }
                )
                current = preferred
                if len(current) == 1:
                    break
                continue

            if not any(_tradeoff_status(candidate, rule_id) for candidate in current):
                unsupported_details.append(
                    pending_unsupported
                    or {
                        "rule_id": rule_id,
                        "status": "unsupported",
                        "mode": "candidate_annotation",
                        "reason": "no executable rule form and no candidate-provided tradeoff result",
                    }
                )

        return applied, applied_details, unsupported_details, current

    def _execute_tradeoff_rule(
        self,
        rule: TradeoffRuleGuidance,
        candidates: list[CandidateDecision],
    ) -> dict[str, Any]:
        if not rule.executable:
            return {
                "rule_id": rule.id,
                "status": "unsupported",
                "mode": "executable_subset",
                "reason": "rule does not match the supported executable subset",
            }

        supported, reason = _executable_rule_supported(rule, self.support)
        if not supported:
            return {
                "rule_id": rule.id,
                "status": "unsupported",
                "mode": "executable_subset",
                "reason": reason,
                "executable": dict(rule.executable),
            }

        when_applies = _condition_applies(rule.executable["when"], candidates)
        unless_applies = _condition_applies(rule.executable["unless"], candidates)
        if not when_applies or unless_applies:
            return {
                "rule_id": rule.id,
                "status": "not_applicable",
                "mode": "executable_subset",
                "when_applies": when_applies,
                "unless_applies": unless_applies,
            }

        selected = _preferred_candidates(rule.executable["enforce"], candidates)
        if not selected or len(selected) == len(candidates):
            return {
                "rule_id": rule.id,
                "status": "not_applicable",
                "mode": "executable_subset",
                "reason": "rule produced no narrowing of the candidate pool",
            }

        return {
            "rule_id": rule.id,
            "status": "applied",
            "mode": "executable_subset",
            "selected_candidate_ids": [candidate.id for candidate in selected],
            "executable": dict(rule.executable),
        }

    def _select_by_direction(self, candidates: list[CandidateDecision]) -> CandidateDecision:
        reverse = self._selection_direction() == "max"
        return sorted(
            candidates,
            key=lambda candidate: (candidate.score_total, candidate.confidence),
            reverse=reverse,
        )[0]

    def _selection_direction(self) -> str:
        direction = self.guidance.primary_objective.direction
        if direction in {"minimize", "reduce"}:
            return "min"
        return "max"

    def _explanation_payload(
        self,
        *,
        selected: CandidateDecision,
        scored: list[CandidateDecision],
        constraint_evaluations: list[dict[str, Any]],
        veto_events: list[dict[str, Any]],
        applied_rule_details: list[dict[str, Any]],
        unsupported_rule_details: list[dict[str, Any]],
        validation_summary: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_scores = {}
        for candidate in scored:
            guidance_score = candidate.params.get("decision_guidance_score", {})
            candidate_scores[candidate.id] = {
                "action": candidate.action,
                "score_total": candidate.score_total,
                "weighted_contributions": guidance_score.get("contributions", {}),
                "missing_dimensions": guidance_score.get("missing_dimensions", []),
            }

        return {
            "artifact": {
                "artifact_id": self.guidance.artifact_id,
                "schema_version": self.guidance.schema_version,
                "artifact_version": self.guidance.artifact_version,
                "source_hash": self.guidance.source_hash,
            },
            "validation": validation_summary,
            "selected_candidate_id": selected.id,
            "selection_direction": self._selection_direction(),
            "final_selection_reason": (
                "selected highest guided score after constraints and trade-off rules"
                if self._selection_direction() == "max"
                else "selected lowest guided score after constraints and trade-off rules"
            ),
            "candidate_scores": candidate_scores,
            "constraint_evaluations": constraint_evaluations,
            "veto_events": veto_events,
            "applied_tradeoff_rules": applied_rule_details,
            "unsupported_tradeoff_rules": unsupported_rule_details,
        }


def _split_sections(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip()] = text[start:end].strip()
    return sections


def _add_issue(
    issues: list[GuidanceValidationIssue],
    warnings: list[str],
    *,
    severity: str,
    section: str,
    code: str,
    message: str,
    action: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    issues.append(
        GuidanceValidationIssue(
            severity=severity,
            section=section,
            code=code,
            message=message,
            action=action,
            details=details or {},
        )
    )
    warnings.append(code)


def _runtime_validation_issues(
    candidates: list[CandidateDecision],
    constraint_evaluations: list[dict[str, Any]],
    unsupported_rule_details: list[dict[str, Any]],
) -> list[GuidanceValidationIssue]:
    issues: list[GuidanceValidationIssue] = []

    for candidate in candidates:
        guidance_score = candidate.params.get("decision_guidance_score", {})
        missing_dimensions = guidance_score.get("missing_dimensions", [])
        if missing_dimensions:
            _add_issue(
                issues,
                [],
                severity="warning",
                section="Preferences / Weights",
                code="candidate_missing_score_dimension",
                message=f"Candidate '{candidate.id}' is missing weighted score dimensions.",
                action="Ensure the candidate policy emits every weighted score dimension.",
                details={
                    "candidate_id": candidate.id,
                    "missing_dimensions": list(missing_dimensions),
                },
            )

    for result in constraint_evaluations:
        if result.get("supported") is False:
            _add_issue(
                issues,
                [],
                severity="unsupported",
                section="Hard Constraints",
                code="unsupported_constraint_id",
                message=f"Constraint '{result['constraint_id']}' is not supported by the active policy.",
                action="Use a supported constraint id or add a matching constraint check.",
                details={"constraint_id": result["constraint_id"]},
            )
        elif result.get("status") == "unknown":
            _add_issue(
                issues,
                [],
                severity="warning",
                section="Hard Constraints",
                code="constraint_check_missing",
                message=f"Candidate '{result['candidate_id']}' did not provide a check for constraint '{result['constraint_id']}'.",
                action="Emit pass/fail/unknown in candidate.params['constraint_checks'] for each hard constraint.",
                details={
                    "candidate_id": result["candidate_id"],
                    "constraint_id": result["constraint_id"],
                },
            )

    for detail in unsupported_rule_details:
        _add_issue(
            issues,
            [],
            severity="unsupported",
            section="Trade-off Rules",
            code="unsupported_tradeoff_rule",
            message=f"Trade-off rule '{detail['rule_id']}' was not executable at runtime.",
            action="Use the supported executable subset or provide candidate tradeoff_rule_results for the rule id.",
            details=dict(detail),
        )

    return issues


def _parse_executable_tradeoff_rule(
    *,
    rule_id: str,
    when: str,
    enforce: str,
    unless: str,
    issues: list[GuidanceValidationIssue],
    warnings: list[str],
) -> dict[str, Any]:
    del rule_id, issues, warnings
    parsed_when = _parse_tradeoff_condition(when)
    parsed_enforce = _parse_tradeoff_enforcement(enforce)
    parsed_unless = _parse_tradeoff_condition(unless or "never")
    if not parsed_when or not parsed_enforce or not parsed_unless:
        return {}
    return {
        "when": parsed_when,
        "enforce": parsed_enforce,
        "unless": parsed_unless,
    }


def _parse_tradeoff_condition(text: str) -> dict[str, Any]:
    normalized = text.strip().lower()
    if normalized == "always":
        return {"kind": "always"}
    if normalized in {"", "never", "none"}:
        return {"kind": "never"}

    match = re.match(r"^candidates differ on ([A-Za-z0-9_.-]+)$", text.strip())
    if match:
        return {"kind": "candidates_differ_on", "target": match.group(1)}

    match = re.match(r"^all candidates have ([A-Za-z0-9_.-]+)$", text.strip())
    if match:
        return {"kind": "all_candidates_have", "target": match.group(1)}

    match = re.match(r"^(?:any action|any candidate action) in \[(.*?)\]$", text.strip())
    if match:
        return {"kind": "any_action_in", "actions": _parse_bracket_list(match.group(1))}

    return {}


def _parse_tradeoff_enforcement(text: str) -> dict[str, Any]:
    stripped = text.strip()
    match = re.match(
        r"^prefer\s+(?:the\s+eligible\s+candidate\s+with\s+|candidate\s+with\s+)?(higher|lower)\s+([A-Za-z0-9_.-]+)(?:\s|$)",
        stripped,
        flags=re.IGNORECASE,
    )
    if match:
        direction, target = match.groups()
        return {
            "kind": "prefer_extreme",
            "direction": "max" if direction.lower() == "higher" else "min",
            "target": target,
        }

    match = re.match(r"^prefer action in \[(.*?)\]$", stripped, flags=re.IGNORECASE)
    if match:
        return {"kind": "prefer_action_in", "actions": _parse_bracket_list(match.group(1))}

    return {}


def _parse_bracket_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _executable_rule_supported(
    rule: TradeoffRuleGuidance,
    support: DecisionGuidanceSupport,
) -> tuple[bool, str]:
    targets = _executable_targets(rule.executable)
    unsupported_targets = [
        target
        for target in targets
        if not _target_supported(target, support)
    ]
    if unsupported_targets:
        return (
            False,
            "unsupported targets: " + ", ".join(sorted(unsupported_targets)),
        )
    return True, ""


def _executable_targets(executable: dict[str, Any]) -> set[str]:
    targets: set[str] = set()
    for key in ("when", "enforce", "unless"):
        payload = executable.get(key)
        if isinstance(payload, dict) and payload.get("target"):
            targets.add(str(payload["target"]))
    return targets


def _target_supported(target: str, support: DecisionGuidanceSupport) -> bool:
    if target in {"score_total", "risk", "confidence"}:
        return True
    if not support.score_dimensions:
        return True
    return target in support.score_dimensions


def _condition_applies(
    condition: dict[str, Any],
    candidates: list[CandidateDecision],
) -> bool:
    kind = condition.get("kind")
    if kind == "always":
        return True
    if kind == "never":
        return False
    if kind == "candidates_differ_on":
        values = [
            value
            for candidate in candidates
            if (value := _candidate_target_value(candidate, str(condition["target"]))) is not None
        ]
        return len(values) == len(candidates) and max(values) - min(values) > 1e-9
    if kind == "all_candidates_have":
        target = str(condition["target"])
        return all(_candidate_target_value(candidate, target) is not None for candidate in candidates)
    if kind == "any_action_in":
        actions = set(condition.get("actions", []))
        return any(candidate.action in actions for candidate in candidates)
    return False


def _preferred_candidates(
    enforcement: dict[str, Any],
    candidates: list[CandidateDecision],
) -> list[CandidateDecision]:
    kind = enforcement.get("kind")
    if kind == "prefer_extreme":
        target = str(enforcement["target"])
        scored = [
            (candidate, value)
            for candidate in candidates
            if (value := _candidate_target_value(candidate, target)) is not None
        ]
        if not scored:
            return []
        best = (
            max(value for _, value in scored)
            if enforcement.get("direction") == "max"
            else min(value for _, value in scored)
        )
        return [candidate for candidate, value in scored if abs(value - best) <= 1e-9]

    if kind == "prefer_action_in":
        actions = set(enforcement.get("actions", []))
        return [candidate for candidate in candidates if candidate.action in actions]

    return []


def _candidate_target_value(candidate: CandidateDecision, target: str) -> float | None:
    if target == "score_total":
        return float(candidate.score_total)
    if target == "risk":
        return float(candidate.risk)
    if target == "confidence":
        return float(candidate.confidence)
    if target in candidate.score_breakdown:
        return float(candidate.score_breakdown[target])
    return None


def _fenced_blocks(section: str) -> list[str]:
    return [
        match.group(1).strip()
        for match in re.finditer(
            r"```(?:[A-Za-z0-9_-]+)?\n(.*?)```",
            section,
            flags=re.DOTALL,
        )
    ]


def _parse_primary_objective(
    section: str,
    warnings: list[str],
    issues: list[GuidanceValidationIssue],
) -> PrimaryObjectiveGuidance:
    for block in _fenced_blocks(section):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line.rstrip(":").lower() == "primary objective" and index + 1 < len(lines):
                text = lines[index + 1]
                return PrimaryObjectiveGuidance(text=text, direction=_objective_direction(text))

    _add_issue(
        issues,
        warnings,
        severity="error",
        section="Primary Objective",
        code="primary_objective_missing",
        message="Primary Objective section is missing or does not contain a parseable objective block.",
        action="Add a fenced block with 'Primary Objective:' followed by one optimization objective.",
    )
    return PrimaryObjectiveGuidance()


def _objective_direction(text: str) -> str:
    first = text.strip().split(" ", 1)[0].lower().strip(":.,")
    if first in {"maximize", "minimize", "reduce", "preserve", "constrain"}:
        return first
    return "unknown"


def _parse_weights(
    section: str,
    warnings: list[str],
    issues: list[GuidanceValidationIssue],
) -> tuple[dict[str, float], dict[str, str]]:
    weights: dict[str, float] = {}
    descriptions: dict[str, str] = {}
    for block in _fenced_blocks(section):
        if block.startswith("Preferences:"):
            for raw in block.splitlines()[1:]:
                line = raw.strip()
                if not line:
                    continue
                match = re.match(r"^-\s+([A-Za-z0-9_.-]+):\s+(.+)$", line)
                if not match:
                    _add_issue(
                        issues,
                        warnings,
                        severity="warning",
                        section="Preferences / Weights",
                        code="malformed_weight",
                        message=f"Weight line is malformed: {line}",
                        action="Use '- <scoring_dimension>: <numeric_weight>'.",
                        details={"line": line},
                    )
                    continue
                name, value = match.groups()
                try:
                    weights[name] = float(value)
                except ValueError:
                    _add_issue(
                        issues,
                        warnings,
                        severity="warning",
                        section="Preferences / Weights",
                        code="malformed_weight_value",
                        message=f"Weight '{name}' is not numeric.",
                        action="Use a numeric weight value.",
                        details={"dimension": name, "value": value},
                    )
            continue

        parsed_descriptions = _parse_description_block(block)
        descriptions.update(parsed_descriptions)

    if weights:
        total = sum(weights.values())
        if abs(total - 1.0) > 0.001:
            _add_issue(
                issues,
                warnings,
                severity="warning",
                section="Preferences / Weights",
                code="weights_not_normalized",
                message=f"Weight values sum to {total:.6f}, not 1.0.",
                action="Normalize weights to sum to 1.0 unless this is intentional.",
                details={"total": total},
            )
    else:
        _add_issue(
            issues,
            warnings,
            severity="error",
            section="Preferences / Weights",
            code="preferences_weights_missing",
            message="Preferences / Weights section is missing or contains no parseable weights.",
            action="Add a fenced Preferences block with numeric score dimension weights.",
        )

    return weights, descriptions


def _parse_description_block(block: str) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    current_key = ""
    current_lines: list[str] = []

    for raw in block.splitlines():
        if not raw.strip():
            continue
        if not raw.startswith(" ") and raw.rstrip().endswith(":"):
            if current_key:
                descriptions[current_key] = " ".join(current_lines).strip()
            current_key = raw.strip().rstrip(":")
            current_lines = []
            continue
        if current_key:
            current_lines.append(raw.strip())

    if current_key:
        descriptions[current_key] = " ".join(current_lines).strip()
    return descriptions


def _parse_hard_constraints(
    section: str,
    warnings: list[str],
    issues: list[GuidanceValidationIssue],
) -> list[HardConstraintGuidance]:
    for block in _fenced_blocks(section):
        if block.startswith("Hard Constraints:"):
            items = _parse_item_block(
                block,
                heading="Hard Constraints:",
                warnings=warnings,
                issues=issues,
                section="Hard Constraints",
            )
            constraints: list[HardConstraintGuidance] = []
            for item in items:
                constraint_id = item.get("id", "")
                rule = item.get("rule", "")
                severity = item.get("severity", "veto")
                if not constraint_id or not rule:
                    _add_issue(
                        issues,
                        warnings,
                        severity="warning",
                        section="Hard Constraints",
                        code="invalid_hard_constraint",
                        message="Hard constraint item is missing id or rule.",
                        action="Each hard constraint needs id, rule, and severity.",
                        details={"item": dict(item)},
                    )
                    continue
                if severity != "veto":
                    _add_issue(
                        issues,
                        warnings,
                        severity="unsupported",
                        section="Hard Constraints",
                        code="unsupported_hard_constraint_severity",
                        message=f"Hard constraint '{constraint_id}' uses unsupported severity '{severity}'.",
                        action="Use severity: veto for runtime-active hard constraints.",
                        details={"constraint_id": constraint_id, "severity": severity},
                    )
                constraints.append(
                    HardConstraintGuidance(
                        id=constraint_id,
                        rule=rule,
                        severity=severity,
                    )
                )
            return constraints

    _add_issue(
        issues,
        warnings,
        severity="error",
        section="Hard Constraints",
        code="hard_constraints_missing",
        message="Hard Constraints section is missing or contains no parseable hard constraints.",
        action="Add a fenced Hard Constraints block with stable constraint ids.",
    )
    return []


def _parse_tradeoff_rules(
    section: str,
    warnings: list[str],
    issues: list[GuidanceValidationIssue],
) -> tuple[list[str], list[TradeoffRuleGuidance]]:
    rule_priority: list[str] = []
    rules: list[TradeoffRuleGuidance] = []

    for block in _fenced_blocks(section):
        if block.startswith("Rule Priority:"):
            for raw in block.splitlines()[1:]:
                match = re.match(r"^\s*\d+\.\s+(.+?)\s*$", raw)
                if match:
                    rule_priority.append(match.group(1))
            continue

        if block.startswith("Trade-off Rules:"):
            items = _parse_item_block(
                block,
                heading="Trade-off Rules:",
                warnings=warnings,
                issues=issues,
                section="Trade-off Rules",
            )
            priority_index = {
                rule_id: index for index, rule_id in enumerate(rule_priority, start=1)
            }
            for item in items:
                rule_id = item.get("id", "")
                when = item.get("when", "")
                enforce = item.get("enforce", "")
                if not rule_id or not when or not enforce:
                    _add_issue(
                        issues,
                        warnings,
                        severity="warning",
                        section="Trade-off Rules",
                        code="invalid_tradeoff_rule",
                        message="Trade-off rule item is missing id, when, or enforce.",
                        action="Each trade-off rule needs id, when, enforce, and optional unless.",
                        details={"item": dict(item)},
                    )
                    continue
                executable = _parse_executable_tradeoff_rule(
                    rule_id=rule_id,
                    when=when,
                    enforce=enforce,
                    unless=item.get("unless", ""),
                    issues=issues,
                    warnings=warnings,
                )
                rules.append(
                    TradeoffRuleGuidance(
                        id=rule_id,
                        when=when,
                        enforce=enforce,
                        unless=item.get("unless", ""),
                        priority=priority_index.get(rule_id),
                        executable=executable,
                    )
                )

    if not rules:
        _add_issue(
            issues,
            warnings,
            severity="error",
            section="Trade-off Rules",
            code="tradeoff_rules_missing",
            message="Trade-off Rules section is missing or contains no parseable rules.",
            action="Add a fenced Trade-off Rules block with stable rule ids.",
        )
    return rule_priority, rules


def _parse_version_metadata(
    section: str,
    warnings: list[str],
    issues: list[GuidanceValidationIssue],
) -> dict[str, str]:
    for block in _fenced_blocks(section):
        if not block.startswith("Version:"):
            continue
        metadata: dict[str, str] = {}
        for raw in block.splitlines()[1:]:
            match = re.match(r"^-\s+([A-Za-z0-9_.-]+):\s*(.*?)\s*$", raw.strip())
            if match:
                metadata[match.group(1)] = match.group(2)
        if not metadata.get("artifact_id"):
            _add_issue(
                issues,
                warnings,
                severity="warning",
                section="Version / Metadata",
                code="metadata_artifact_id_missing",
                message="Version / Metadata is missing artifact_id.",
                action="Add a stable artifact_id for trace provenance.",
            )
        return metadata

    _add_issue(
        issues,
        warnings,
        severity="warning",
        section="Version / Metadata",
        code="version_metadata_missing",
        message="Version / Metadata section is missing or not parseable.",
        action="Add a fenced Version block with artifact_id and schema_version.",
    )
    return {}


def _parse_item_block(
    block: str,
    *,
    heading: str,
    warnings: list[str],
    issues: list[GuidanceValidationIssue],
    section: str,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in block.splitlines()[1:] if block.startswith(heading) else block.splitlines():
        if not raw.strip():
            continue
        stripped = raw.strip()
        if stripped.startswith("- id:"):
            if current is not None:
                items.append(current)
            current = {"id": stripped.removeprefix("- id:").strip()}
            continue
        if current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = value.strip()
            continue
        _add_issue(
            issues,
            warnings,
            severity="warning",
            section=section,
            code="invalid_item_line",
            message=f"Item line is malformed: {stripped}",
            action="Use indented key/value lines below '- id: <id>'.",
            details={"line": stripped},
        )

    if current is not None:
        items.append(current)
    return items


def _constraint_status(value: Any) -> str:
    if isinstance(value, bool):
        return "pass" if value else "fail"
    if value is None:
        return "unknown"
    normalized = str(value).strip().lower()
    if normalized in {"pass", "passed", "ok", "true"}:
        return "pass"
    if normalized in {"fail", "failed", "false", "veto", "violated", "violate"}:
        return "fail"
    if normalized in {"unknown", "unset", ""}:
        return "unknown"
    return normalized


def _tradeoff_status(candidate: CandidateDecision, rule_id: str) -> str:
    raw = candidate.params.get("tradeoff_rule_results")
    if not isinstance(raw, dict):
        return ""
    value = raw.get(rule_id)
    if isinstance(value, dict):
        value = value.get("status")
    normalized = str(value).strip().lower() if value is not None else ""
    if normalized in {"preferred", "prefer", "selected", "apply", "applies"}:
        return "preferred"
    if normalized in {"disfavored", "avoid", "reject"}:
        return "disfavored"
    if normalized in {"neutral", "not_applicable", "none"}:
        return normalized
    return ""


def _candidate_payload(candidate: CandidateDecision) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "action": candidate.action,
        "params": dict(candidate.params),
        "score_total": float(candidate.score_total),
        "score_breakdown": {str(k): float(v) for k, v in candidate.score_breakdown.items()},
        "risk": float(candidate.risk),
        "confidence": float(candidate.confidence),
    }


def _constraint_payload(constraint: SafetyConstraint) -> dict[str, Any]:
    return {
        "name": constraint.name,
        "kind": constraint.kind,
        "params": dict(constraint.params),
    }
