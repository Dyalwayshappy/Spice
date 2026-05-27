from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping

from spice.llm.candidate_expander import build_candidate_expander_client
from spice.llm.core import LLMClient, LLMRequest, LLMTaskHook
from spice.runtime.composer_context import compact_composer_context
from spice.runtime.composer_parser import parse_composer_response_text
from spice.runtime.composer_prompt import build_slim_composer_prompt_payload, slim_recent_context
from spice.runtime.composer_result import ComposerResult
from spice.runtime.composer_streaming import (
    ComposerStreamError,
    generate_or_stream_composer_output,
    mark_streaming_invalid,
    mark_streaming_valid,
)
from spice.runtime.composer_workspace_validator import (
    WORKSPACE_COMPOSER_CONSTRAINTS,
    validate_workspace_claims,
)
from spice.runtime.response_depth import resolve_response_depth_budget


EXECUTION_RESPONSE_COMPOSER_SCHEMA_VERSION = "spice.execution_response_composer.v1"

_ARTIFACT_ID_PATTERN = re.compile(
    r"\b(?:approval|decision|candidate|outcome|execution|request)\.[A-Za-z0-9_.:-]+\b"
)

_SUCCESS_CLAIMS = (
    "completed",
    "finished",
    "succeeded",
    "successfully",
    "all set",
    "done",
    "worked",
    "resolved",
    "went through",
    "完成",
    "成功",
    "搞定",
    "执行完",
    "跑完",
)

_FAILURE_CLAIMS = (
    "failed",
    "error",
    "did not complete",
    "didn't complete",
    "did not run",
    "didn't run",
    "did not call",
    "didn't call",
    "could not complete",
    "couldn't complete",
    "timed out",
    "permission denied",
    "blocked",
    "失败",
    "出错",
    "报错",
    "没有完成",
    "未完成",
    "没有执行",
    "未执行",
    "没有调用",
    "未调用",
    "被阻塞",
    "权限不足",
)

_PENDING_APPROVAL_CLAIMS = (
    "pending approval",
    "approval is ready",
    "approval was created",
    "needs approval",
    "waiting for approval",
    "需要审批",
    "需要批准",
    "等待审批",
    "等待批准",
    "已生成 approval",
)

_MEMORY_WRITE_CLAIMS = (
    "recorded in memory",
    "recorded into memory",
    "saved to memory",
    "stored in memory",
    "wrote to memory",
    "written to memory",
    "memory was updated",
    "memory is updated",
    "写入记忆",
    "记入记忆",
    "保存到记忆",
    "记录到记忆",
    "写入 memory",
    "记录到 memory",
)

_MEMORY_NOT_WRITTEN_CLAIMS = (
    "not recorded in memory",
    "not saved to memory",
    "not written to memory",
    "wasn't recorded in memory",
    "wasn't saved to memory",
    "wasn't written to memory",
    "没有写入记忆",
    "未写入记忆",
    "没有记录到记忆",
    "未记录到记忆",
)

_STATE_UPDATE_CLAIMS = (
    "state was updated",
    "state is updated",
    "updated state",
    "recorded back into state",
    "state changed",
    "状态已更新",
    "更新了状态",
    "写入状态",
    "记录到状态",
)

_STATE_NOT_UPDATED_CLAIMS = (
    "state was not updated",
    "state wasn't updated",
    "did not update state",
    "didn't update state",
    "没有更新状态",
    "未更新状态",
)

_REAL_EXECUTION_CLAIMS = (
    "real executor",
    "actually executed",
    "executed for real",
    "handed off to hermes",
    "handed off to codex",
    "handed off to openclaw",
    "真实执行",
    "实际执行",
)

_DRY_RUN_ONLY_CLAIMS = (
    "dry run only",
    "dry-run only",
    "only a dry run",
    "not actually executed",
    "没有真实执行",
    "只是 dry run",
    "仅 dry run",
)

_CHANGED_FILES_CLAIMS = (
    "changed files",
    "modified files",
    "created files",
    "deleted files",
    "updated files",
    "file changes",
    "改了文件",
    "修改了文件",
    "创建了文件",
    "删除了文件",
    "更新了文件",
)

_EXECUTOR_ALIASES = {
    "hermes": {"hermes"},
    "codex": {"codex"},
    "openclaw": {"openclaw", "open claw"},
    "claude_code": {"claude code", "claude"},
    "claude-code": {"claude code", "claude"},
    "dry_run": {"dry run", "dry-run"},
    "dry-run": {"dry run", "dry-run"},
    "sdep_subprocess": {"sdep subprocess", "sdep"},
}

_TECHNICAL_MISMATCH_MARKERS = (
    "approved approval does not match",
    "approval does not match the sdep request",
    "sdep request approval_id",
    "sdep request candidate_id",
    "sdep request decision_id",
    "sdep response attribution mismatch",
    "sdep request missing required attribution",
)


ExecutionResponseComposeResult = ComposerResult


def classify_execution_error(error_text: str) -> str:
    lower = str(error_text or "").strip().lower()
    if not lower:
        return ""
    if "approved approval does not match" in lower:
        return "approval_request_mismatch"
    if (
        "sdep response attribution mismatch" in lower
        or "sdep request missing required attribution" in lower
    ):
        return "executor_result_attribution_mismatch"
    return ""


def user_facing_execution_error(error_text: str) -> str:
    kind = classify_execution_error(error_text)
    if kind == "approval_request_mismatch":
        return "The current selection is not an executable task, so I did not call the executor."
    if kind == "executor_result_attribution_mismatch":
        return (
            "The executor result could not be safely verified, so Spice did not record it "
            "as completed. Use /details or /json for the technical trace."
        )
    return str(error_text or "").strip()


def compose_execution_response_from_runtime_config(
    *,
    config: Mapping[str, Any],
    execution_artifact: Mapping[str, Any] | None = None,
    error_artifact: Mapping[str, Any] | None = None,
    context_payload: Mapping[str, Any] | None = None,
    stream_callback: Callable[[str], None] | None = None,
) -> ExecutionResponseComposeResult:
    facts = execution_response_facts(
        execution_artifact=execution_artifact,
        error_artifact=error_artifact,
        context_payload=context_payload,
    )
    deterministic_text = render_execution_response_fallback(facts)
    provider_id = str(config.get("llm_provider") or "deterministic").strip()
    model_id = _runtime_model_id(config)
    if provider_id in {"", "deterministic"}:
        return ExecutionResponseComposeResult(
            enabled=False,
            status="disabled",
            response_text=deterministic_text,
            deterministic_text=deterministic_text,
            composer_kind="execution_response",
            model_provider=provider_id or "deterministic",
            model_id=model_id,
            facts=facts,
            metadata={
                "reason": "deterministic provider",
                "composer_schema_version": EXECUTION_RESPONSE_COMPOSER_SCHEMA_VERSION,
            },
        )
    if not model_id:
        return ExecutionResponseComposeResult(
            enabled=True,
            status="fallback",
            response_text=deterministic_text,
            deterministic_text=deterministic_text,
            composer_kind="execution_response",
            model_provider=provider_id,
            error="llm_model is required for execution response composition.",
            fallback_reason="missing_model",
            facts=facts,
            metadata={"composer_schema_version": EXECUTION_RESPONSE_COMPOSER_SCHEMA_VERSION},
        )

    try:
        client = build_candidate_expander_client(provider_id=provider_id, model_id=model_id)
        return compose_execution_response_with_llm(
            client=client,
            execution_artifact=execution_artifact,
            error_artifact=error_artifact,
            deterministic_text=deterministic_text,
            model_provider=provider_id,
            model_id=model_id,
            context_payload=context_payload,
            stream_callback=stream_callback,
            config=config,
        )
    except Exception as exc:
        return ExecutionResponseComposeResult(
            enabled=True,
            status="fallback",
            response_text=deterministic_text,
            deterministic_text=deterministic_text,
            composer_kind="execution_response",
            model_provider=provider_id,
            model_id=model_id,
            error=str(exc),
            fallback_reason="client_error",
            facts=facts,
            metadata={"composer_schema_version": EXECUTION_RESPONSE_COMPOSER_SCHEMA_VERSION},
        )


def compose_execution_response_with_llm(
    *,
    client: LLMClient,
    execution_artifact: Mapping[str, Any] | None = None,
    error_artifact: Mapping[str, Any] | None = None,
    deterministic_text: str = "",
    model_provider: str = "",
    model_id: str = "",
    context_payload: Mapping[str, Any] | None = None,
    stream_callback: Callable[[str], None] | None = None,
    config: Mapping[str, Any] | None = None,
) -> ExecutionResponseComposeResult:
    facts = execution_response_facts(
        execution_artifact=execution_artifact,
        error_artifact=error_artifact,
        context_payload=context_payload,
    )
    depth = _resolve_response_depth_for_execution_facts(
        facts,
        config=config,
    )
    facts = {**facts, "response_depth": depth.to_payload()}
    resolved_deterministic_text = deterministic_text or render_execution_response_fallback(facts)
    request = LLMRequest(
        task_hook=LLMTaskHook.RESPONSE_COMPOSE,
        input_text=_execution_response_prompt(facts),
        system_text=_execution_response_system_prompt(),
        response_format_hint="",
        temperature=0.45,
        max_tokens=depth.max_tokens,
        timeout_sec=depth.timeout_sec,
        metadata={
            "purpose": "execution_response_composition",
            "model_provider": model_provider,
            "model_id": model_id,
            "approval_id": facts.get("approval_id"),
            "decision_id": facts.get("decision_id"),
            "candidate_id": facts.get("candidate_id"),
            "execution_status": facts.get("execution_status"),
            "response_depth": depth.to_payload(),
        },
    )
    try:
        output = generate_or_stream_composer_output(
            client=client,
            request=request,
            stream_callback=stream_callback,
        )
    except ComposerStreamError as exc:
        return ExecutionResponseComposeResult(
            enabled=True,
            status="fallback",
            response_text=resolved_deterministic_text,
            deterministic_text=resolved_deterministic_text,
            composer_kind="execution_response",
            model_provider=model_provider,
            model_id=model_id,
            error=str(exc),
            raw_output=exc.raw_output,
            fallback_reason="stream_error",
            facts=facts,
            metadata=mark_streaming_invalid(
                {
                    **exc.metadata,
                    "fallback_reason": "stream_error",
                    "composer_schema_version": EXECUTION_RESPONSE_COMPOSER_SCHEMA_VERSION,
                    "response_depth": depth.to_payload(),
                },
                reason="stream_error",
            ),
        )
    raw_output = output.raw_output
    try:
        text = parse_composer_response_text(raw_output, max_chars=depth.max_chars)
        _validate_composed_response(text, facts, max_chars=depth.max_chars)
    except Exception as exc:
        return ExecutionResponseComposeResult(
            enabled=True,
            status="fallback",
            response_text=resolved_deterministic_text,
            deterministic_text=resolved_deterministic_text,
            composer_kind="execution_response",
            model_provider=model_provider or output.provider_id,
            model_id=model_id or output.model_id,
            request_id=output.request_id,
            error=str(exc),
            raw_output=raw_output,
            fallback_reason="invalid_composed_response",
            facts=facts,
            metadata=mark_streaming_invalid(
                {
                    **output.metadata,
                    "fallback_reason": "invalid_composed_response",
                    "composer_schema_version": EXECUTION_RESPONSE_COMPOSER_SCHEMA_VERSION,
                    "response_depth": depth.to_payload(),
                },
                reason="invalid_composed_response",
            ),
        )
    return ExecutionResponseComposeResult(
        enabled=True,
        status="composed",
        response_text=text,
        deterministic_text=resolved_deterministic_text,
        composer_kind="execution_response",
        model_provider=model_provider or output.provider_id,
        model_id=model_id or output.model_id,
        request_id=output.request_id,
        raw_output=raw_output,
        facts=facts,
        metadata=mark_streaming_valid(
            {
                **output.metadata,
                "facts_schema": EXECUTION_RESPONSE_COMPOSER_SCHEMA_VERSION,
                "composer_schema_version": EXECUTION_RESPONSE_COMPOSER_SCHEMA_VERSION,
                "approval_id": facts.get("approval_id", ""),
                "decision_id": facts.get("decision_id", ""),
                "candidate_id": facts.get("candidate_id", ""),
                "execution_status": facts.get("execution_status", ""),
                "response_depth": depth.to_payload(),
            }
        ),
    )


def execution_response_facts(
    *,
    execution_artifact: Mapping[str, Any] | None = None,
    error_artifact: Mapping[str, Any] | None = None,
    context_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    artifact = _mapping(execution_artifact)
    error = _mapping(error_artifact)
    outcome_record = _mapping(artifact.get("outcome_record"))
    outcome = _mapping(artifact.get("outcome"))
    outcome_metadata = _mapping(outcome_record.get("metadata"))
    output = _mapping(outcome_metadata.get("output"))
    memory_writeback = _mapping(artifact.get("memory_writeback"))
    return {
        "schema_version": EXECUTION_RESPONSE_COMPOSER_SCHEMA_VERSION,
        "execution_status": _execution_status(artifact, error),
        "approval_id": _first_text(artifact, error, key="approval_id"),
        "decision_id": _first_text(artifact, error, key="decision_id"),
        "trace_ref": _first_text(artifact, error, key="trace_ref"),
        "candidate_id": _first_text(artifact, error, key="candidate_id", aliases=("selected_candidate_id",)),
        "candidate_title": _shorten(_first_text(artifact, error, key="candidate_title", aliases=("title",)), 180),
        "candidate_summary": _shorten(
            _first_text(artifact, error, key="candidate_summary", aliases=("recommendation", "executor_task")),
            360,
        ),
        "executor_provider": _executor_provider(artifact, error),
        "executor_id": _first_text(artifact, error, key="executor_id"),
        "protocol_status": _first_text(artifact, error, key="protocol_status"),
        "task_status": _first_text(artifact, error, key="task_status"),
        "outcome_id": _first_text(artifact, error, key="outcome_id"),
        "execution_id": _first_text(artifact, error, key="execution_id"),
        "request_id": _first_text(artifact, error, key="request_id"),
        "permission": _compact_permission(artifact, error),
        "executor_summary": _shorten(_executor_summary(artifact, outcome_record, outcome, output), 700),
        "state_delta_summary": _compact_state_delta(artifact, outcome_record, output),
        "memory_written": _memory_written(memory_writeback),
        "state_updated": bool(artifact.get("state_updated")),
        "dry_run": bool(artifact.get("dry_run")),
        "real_executor_called": bool(artifact.get("real_executor_called")),
        "error": _shorten(_error_summary(error, artifact), 500),
        "technical_error": _shorten(_technical_error_summary(error, artifact), 500),
        "failure_kind": _failure_kind(error, artifact),
        "next_actions": _execution_next_actions(artifact, error),
        "decision_context": compact_composer_context(context_payload),
    }


def render_execution_response_fallback(facts: Mapping[str, Any]) -> str:
    status = str(facts.get("execution_status") or "unknown")
    executor = str(facts.get("executor_provider") or facts.get("executor_id") or "executor")
    task_status = str(facts.get("task_status") or facts.get("protocol_status") or "unknown")
    outcome_id = str(facts.get("outcome_id") or "")
    approval_id = str(facts.get("approval_id") or "")
    summary = str(facts.get("executor_summary") or facts.get("error") or "").strip()
    lines: list[str] = []
    if str(facts.get("failure_kind") or "") == "approval_request_mismatch":
        lines.extend(
            [
                "This execution did not run.",
                "",
                summary
                or "The current selection is not an executable task, so I did not call the executor.",
            ]
        )
        if approval_id:
            lines.append(f"approval: {approval_id}")
        lines.extend(
            [
                "",
                "Use /details or /json if you need the technical trace.",
                "",
                "Next: details, refine, or choose an executable task.",
            ]
        )
        return "\n".join(lines)
    if status == "completed":
        lines.append(f"{executor} finished the handoff.")
    elif status == "failed":
        lines.append(f"{executor} did not complete the handoff.")
    else:
        lines.append(f"{executor} returned an execution result.")
    lines.append("")
    lines.append(f"task_status: {task_status}")
    if approval_id:
        lines.append(f"approval: {approval_id}")
    if outcome_id:
        lines.append(f"outcome: {outcome_id}")
    if summary:
        lines.append(f"summary: {summary}")
    if bool(facts.get("memory_written")):
        lines.append("Spice recorded the outcome in memory.")
    lines.append("")
    next_actions = _strings(facts.get("next_actions")) or ["details", "continue", "refine"]
    lines.append(f"Next: {', '.join(next_actions)}.")
    return "\n".join(lines)


def _execution_response_system_prompt() -> str:
    return (
        "You are Spice's execution response composer. Do one thing: write a natural "
        "user-facing response for an executor result. It should not sound like a template, "
        "checklist, or log panel. Do not change the selected option, execution status, "
        "approval state, scores, artifact ids, or executor facts. Do not expose raw "
        "JSON/schema. Return only the response."
    )


def _execution_response_prompt(facts: Mapping[str, Any]) -> str:
    return json.dumps(
        build_slim_composer_prompt_payload(
            task="Write the natural response for this executor result. Do not re-decide or request approval.",
            facts=_slim_execution_prompt_facts(facts),
            tone="Natural post-execution agent voice. Be clear about success, failure, and what was recorded.",
            extra_constraints=(
                "Do not claim success unless execution_status is completed or task_status is success/completed.",
                "Do not hide failure, blocked status, stderr, or errors when provided.",
                "Do not say memory was written unless memory_written is true.",
                "Do not invent changed files, tools, commands, approvals, or executor capabilities.",
                "Do not ask for approval; this response describes an execution result that already happened.",
                "Match response_depth guidance and stay under response_depth.max_chars.",
                *WORKSPACE_COMPOSER_CONSTRAINTS,
            ),
        ),
        ensure_ascii=False,
        sort_keys=True,
    )


def _slim_execution_prompt_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "selected_candidate": {
            "candidate_id": str(facts.get("candidate_id") or ""),
            "title": str(facts.get("candidate_title") or ""),
            "summary": str(facts.get("candidate_summary") or ""),
        },
        "execution_result": {
            "execution_status": str(facts.get("execution_status") or ""),
            "task_status": str(facts.get("task_status") or ""),
            "protocol_status": str(facts.get("protocol_status") or ""),
            "executor_provider": str(facts.get("executor_provider") or ""),
            "executor_summary": str(facts.get("executor_summary") or ""),
            "error": str(facts.get("error") or ""),
            "memory_written": bool(facts.get("memory_written")),
            "state_updated": bool(facts.get("state_updated")),
            "dry_run": bool(facts.get("dry_run")),
            "real_executor_called": bool(facts.get("real_executor_called")),
            "failure_kind": str(facts.get("failure_kind") or ""),
        },
        "execution_affordance": {
            "permission": _mapping(facts.get("permission")),
            "executor_id": str(facts.get("executor_id") or ""),
            "executor_provider": str(facts.get("executor_provider") or ""),
        },
        "allowed_next_actions": _strings(facts.get("next_actions"))[:6],
        "recent_context": slim_recent_context(_mapping(facts.get("decision_context"))),
        "response_depth": _compact_response_depth(_mapping(facts.get("response_depth"))),
    }


def _resolve_response_depth_for_execution_facts(
    facts: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None,
) -> Any:
    context = _mapping(facts.get("decision_context"))
    evidence_context = _mapping(context.get("evidence_context"))
    requirements = _mapping(evidence_context.get("requirements"))
    return resolve_response_depth_budget(
        answer_mode=str(requirements.get("answer_mode") or ""),
        evidence_domain=str(requirements.get("evidence_domain") or ""),
        evidence_context=evidence_context,
        user_input=str(facts.get("candidate_summary") or facts.get("executor_summary") or ""),
        config=config,
        composer_kind="execution_response",
    )


def _compact_response_depth(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "answer_mode": str(payload.get("answer_mode") or ""),
        "max_chars": payload.get("max_chars"),
        "max_tokens": payload.get("max_tokens"),
        "native": bool(payload.get("native")),
        "guidance": _response_depth_guidance(str(payload.get("answer_mode") or "")),
    }


def _response_depth_guidance(answer_mode: str) -> str:
    if answer_mode == "brief":
        return "Keep this compact."
    if answer_mode == "detailed":
        return "Give concrete reasoning, steps, and caveats."
    if answer_mode == "report":
        return "Use evidence, sources, limitations, and tradeoffs."
    if answer_mode == "native":
        return "Use the model-native budget while staying factual."
    return "Give a normal conversational answer with enough context to act."


def _validate_composed_response(
    text: str,
    facts: Mapping[str, Any],
    *,
    max_chars: int = 2400,
) -> None:
    if not text:
        raise ValueError("execution response composer returned empty response")
    if len(text) > max_chars:
        raise ValueError("execution response composer returned overly long response")
    stripped = text.strip()
    if stripped.startswith(("{", "[")) or "```" in stripped:
        raise ValueError("execution response composer returned raw structured output")

    lower = stripped.lower()
    execution_status = str(facts.get("execution_status") or "").strip().lower()
    task_status = str(facts.get("task_status") or "").strip().lower()
    success_allowed = execution_status == "completed" or task_status in {"success", "completed", "ok"}
    failed = execution_status == "failed" or task_status in {"failed", "error", "blocked", "cancelled", "canceled"}
    failure_kind = str(facts.get("failure_kind") or "")

    if not success_allowed and _contains_claim(lower, _SUCCESS_CLAIMS):
        raise ValueError("execution response composer contradicted execution status with a success claim")
    if success_allowed and _contains_claim(lower, _FAILURE_CLAIMS):
        raise ValueError("execution response composer contradicted execution status with a failure claim")
    if failure_kind in {"approval_request_mismatch", "executor_result_attribution_mismatch"}:
        if _contains_technical_mismatch_detail(lower):
            raise ValueError("execution response composer exposed technical approval/SDEP mismatch details")
    if failed and not (_contains_claim(lower, _FAILURE_CLAIMS) or _mentions_error_detail(lower, facts)):
        raise ValueError("execution response composer hid a failed execution result")

    memory_written = bool(facts.get("memory_written"))
    if not memory_written and _claims_memory_write(lower):
        raise ValueError("execution response composer claimed memory write without memory_writeback")
    if memory_written and _contains_claim(lower, _MEMORY_NOT_WRITTEN_CLAIMS):
        raise ValueError("execution response composer denied recorded memory_writeback")

    state_updated = bool(facts.get("state_updated"))
    if not state_updated and _contains_claim(lower, _STATE_UPDATE_CLAIMS):
        raise ValueError("execution response composer claimed state update without state_updated")
    if state_updated and _contains_claim(lower, _STATE_NOT_UPDATED_CLAIMS):
        raise ValueError("execution response composer denied recorded state update")

    if _contains_claim(lower, _PENDING_APPROVAL_CLAIMS):
        raise ValueError("execution response composer described a pending approval instead of an execution result")

    dry_run = bool(facts.get("dry_run"))
    if dry_run and _contains_claim(lower, _REAL_EXECUTION_CLAIMS):
        raise ValueError("execution response composer claimed real execution for a dry run")
    if not dry_run and _contains_claim(lower, _DRY_RUN_ONLY_CLAIMS):
        raise ValueError("execution response composer claimed dry-run-only for a real execution")

    if _contains_claim(lower, _CHANGED_FILES_CLAIMS) and not _has_updated_refs(facts):
        raise ValueError("execution response composer invented changed files")

    _validate_artifact_ids(stripped, facts)
    _validate_executor_claims(lower, facts)
    validate_workspace_claims(stripped, facts, composer_kind="execution response composer")


def _execution_status(artifact: Mapping[str, Any], error: Mapping[str, Any]) -> str:
    explicit = str(error.get("execution_status") or error.get("status") or "").strip().lower()
    if explicit in {"failed", "error", "blocked"}:
        return "failed"
    protocol_status = str(artifact.get("protocol_status") or "").strip().lower()
    task_status = str(artifact.get("task_status") or "").strip().lower()
    if task_status in {"success", "completed", "ok"}:
        return "completed"
    if protocol_status in {"success", "completed", "ok"} and task_status in {"", "unknown"}:
        return "completed"
    if task_status in {"failed", "error", "blocked", "cancelled", "canceled"}:
        return "failed"
    if protocol_status in {"failed", "error", "blocked", "cancelled", "canceled"}:
        return "failed"
    return "unknown"


def _contains_claim(text_lower: str, claims: tuple[str, ...]) -> bool:
    for claim in claims:
        claim_lower = claim.lower()
        start = text_lower.find(claim_lower)
        while start >= 0:
            if not _negated_near(text_lower, start):
                return True
            start = text_lower.find(claim_lower, start + len(claim_lower))
    return False


def _contains_technical_mismatch_detail(text_lower: str) -> bool:
    return any(marker in text_lower for marker in _TECHNICAL_MISMATCH_MARKERS)


def _claims_memory_write(text_lower: str) -> bool:
    if _contains_claim(text_lower, _MEMORY_WRITE_CLAIMS):
        return True
    if "memory" not in text_lower and "记忆" not in text_lower:
        return False
    return _contains_claim(
        text_lower,
        (
            "recorded",
            "saved",
            "stored",
            "wrote",
            "written",
            "updated",
            "记录",
            "写入",
            "保存",
            "记入",
        ),
    )


def _negated_near(text_lower: str, claim_start: int) -> bool:
    window = text_lower[max(0, claim_start - 28) : claim_start]
    return any(
        token in window
        for token in (
            "not ",
            "no ",
            "never ",
            "without ",
            "didn't ",
            "did not ",
            "doesn't ",
            "does not ",
            "wasn't ",
            "was not ",
            "isn't ",
            "is not ",
            "failed to ",
            "没有",
            "没",
            "未",
            "并未",
            "不是",
            "不",
        )
    )


def _mentions_error_detail(text_lower: str, facts: Mapping[str, Any]) -> bool:
    error = str(facts.get("error") or "").strip().lower()
    if not error:
        return False
    meaningful_tokens = [
        token.strip(".,:;()[]{}")
        for token in error.replace("_", " ").replace("-", " ").split()
        if len(token.strip(".,:;()[]{}")) >= 4
    ]
    return any(token in text_lower for token in meaningful_tokens[:8])


def _validate_artifact_ids(text: str, facts: Mapping[str, Any]) -> None:
    allowed = {
        str(facts.get("approval_id") or ""),
        str(facts.get("decision_id") or ""),
        str(facts.get("candidate_id") or ""),
        str(facts.get("outcome_id") or ""),
        str(facts.get("execution_id") or ""),
        str(facts.get("request_id") or ""),
    }
    allowed = {item for item in allowed if item}
    for artifact_id in _ARTIFACT_ID_PATTERN.findall(text):
        if artifact_id not in allowed:
            raise ValueError(f"execution response composer invented artifact id: {artifact_id}")


def _validate_executor_claims(text_lower: str, facts: Mapping[str, Any]) -> None:
    executor = str(facts.get("executor_provider") or facts.get("executor_id") or "").strip().lower()
    if not executor:
        for aliases in _EXECUTOR_ALIASES.values():
            for alias in aliases:
                if _wordish_contains(text_lower, alias):
                    raise ValueError(f"execution response composer invented executor: {alias}")
        return
    current_aliases = _executor_aliases(executor)
    if not current_aliases:
        return
    for executor_key, aliases in _EXECUTOR_ALIASES.items():
        if aliases == current_aliases or executor_key in current_aliases:
            continue
        for alias in aliases:
            if _wordish_contains(text_lower, alias):
                raise ValueError(f"execution response composer mentioned a different executor: {alias}")


def _executor_aliases(executor: str) -> set[str]:
    normalized = executor.replace(".", "_").replace("-", "_").lower()
    for key, aliases in _EXECUTOR_ALIASES.items():
        if key.replace("-", "_") in normalized or any(alias in executor for alias in aliases):
            return set(aliases)
    return set()


def _wordish_contains(text_lower: str, phrase: str) -> bool:
    phrase_lower = phrase.lower()
    if " " in phrase_lower or "-" in phrase_lower:
        return phrase_lower in text_lower
    return re.search(rf"(?<![a-z0-9_]){re.escape(phrase_lower)}(?![a-z0-9_])", text_lower) is not None


def _has_updated_refs(facts: Mapping[str, Any]) -> bool:
    state_delta = _mapping(facts.get("state_delta_summary"))
    updated_refs = state_delta.get("updated_refs")
    if isinstance(updated_refs, list):
        return bool(updated_refs)
    return bool(updated_refs)


def _executor_provider(artifact: Mapping[str, Any], error: Mapping[str, Any]) -> str:
    for payload in (artifact, error):
        value = payload.get("executor_provider") or payload.get("executor") or payload.get("provider")
        if str(value or "").strip():
            return str(value).strip()
    outcome_record = _mapping(artifact.get("outcome_record"))
    metadata = _mapping(outcome_record.get("metadata"))
    value = metadata.get("executor_provider") or _mapping(metadata.get("responder")).get("id")
    return str(value or "").strip()


def _executor_summary(
    artifact: Mapping[str, Any],
    outcome_record: Mapping[str, Any],
    outcome: Mapping[str, Any],
    output: Mapping[str, Any],
) -> str:
    candidates = [
        artifact.get("executor_summary"),
        artifact.get("summary"),
        outcome_record.get("summary"),
        outcome.get("summary"),
        output.get("summary"),
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _compact_state_delta(
    artifact: Mapping[str, Any],
    outcome_record: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, Any]:
    state_delta = _mapping(outcome_record.get("state_delta")) or _mapping(output.get("state_delta"))
    if not state_delta and artifact.get("state_updated"):
        state_delta = {"state_updated": True}
    result: dict[str, Any] = {}
    for key in ("task_status", "protocol_status", "executor_provider", "updated_refs", "dry_run"):
        if key in state_delta:
            result[key] = state_delta[key]
    if not result and state_delta:
        for key, value in list(state_delta.items())[:5]:
            result[str(key)] = value
    return result


def _compact_permission(artifact: Mapping[str, Any], error: Mapping[str, Any]) -> dict[str, Any]:
    permission = _mapping(artifact.get("permission")) or _mapping(error.get("permission"))
    if permission:
        return {
            "mode": str(permission.get("mode") or permission.get("permission_mode") or ""),
            "required": str(permission.get("required") or permission.get("required_permission") or ""),
            "granted": permission.get("granted"),
        }
    return {}


def _memory_written(memory_writeback: Mapping[str, Any]) -> bool:
    status = str(memory_writeback.get("status") or "").strip().lower()
    if not status:
        return False
    return status not in {"skipped", "failed", "error"}


def _error_summary(error: Mapping[str, Any], artifact: Mapping[str, Any]) -> str:
    for payload in (error, artifact):
        text = str(payload.get("user_facing_error") or "").strip()
        if text:
            return text
    for payload in (error, artifact):
        for key in ("error", "stderr", "message", "reason"):
            text = str(payload.get(key) or "").strip()
            if text:
                return user_facing_execution_error(text)
    outcome_record = _mapping(artifact.get("outcome_record"))
    metadata = _mapping(outcome_record.get("metadata"))
    output = _mapping(metadata.get("output"))
    return user_facing_execution_error(str(output.get("stderr") or "").strip())


def _technical_error_summary(error: Mapping[str, Any], artifact: Mapping[str, Any]) -> str:
    for payload in (error, artifact):
        text = str(payload.get("technical_error") or "").strip()
        if text:
            return text
    for payload in (error, artifact):
        for key in ("error", "stderr", "message", "reason"):
            text = str(payload.get(key) or "").strip()
            if text:
                return text
    outcome_record = _mapping(artifact.get("outcome_record"))
    metadata = _mapping(outcome_record.get("metadata"))
    output = _mapping(metadata.get("output"))
    return str(output.get("stderr") or "").strip()


def _failure_kind(error: Mapping[str, Any], artifact: Mapping[str, Any]) -> str:
    for payload in (error, artifact):
        text = str(payload.get("failure_kind") or "").strip()
        if text:
            return text
    return classify_execution_error(_technical_error_summary(error, artifact))


def _execution_next_actions(artifact: Mapping[str, Any], error: Mapping[str, Any]) -> list[str]:
    custom = _strings(artifact.get("next_actions")) or _strings(error.get("next_actions"))
    if custom:
        return custom[:5]
    status = _execution_status(artifact, error)
    if status == "failed":
        return ["details", "retry", "refine"]
    return ["details", "continue", "refine"]


def _first_text(
    artifact: Mapping[str, Any],
    error: Mapping[str, Any],
    *,
    key: str,
    aliases: tuple[str, ...] = (),
) -> str:
    keys = (key, *aliases)
    for payload in (artifact, error):
        for candidate_key in keys:
            text = str(payload.get(candidate_key) or "").strip()
            if text:
                return text
    outcome_record = _mapping(artifact.get("outcome_record"))
    for candidate_key in keys:
        text = str(outcome_record.get(candidate_key) or "").strip()
        if text:
            return text
    return ""


def _runtime_model_id(config: Mapping[str, Any]) -> str:
    return str(config.get("llm_model") or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


def _shorten(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "..."
