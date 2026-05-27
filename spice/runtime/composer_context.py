from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from spice.perception import build_evidence_context, compact_evidence_context
from spice.runtime.context_debug import compile_workspace_decision_context_payload
from spice.runtime.session import load_or_create_session
from spice.runtime.store import LocalJsonStore
from spice.runtime.workspace import load_workspace_config


COMPOSER_CONTEXT_SCHEMA_VERSION = "spice.composer_context.v1"
COMPOSER_CONTEXT_RECENT_TURN_LIMIT = 6
COMPOSER_CONTEXT_RECENT_DECISION_LIMIT = 3
COMPOSER_CONTEXT_RECENT_APPROVAL_LIMIT = 3
COMPOSER_CONTEXT_RECENT_EXECUTION_LIMIT = 3
COMPOSER_CONTEXT_ACTIVE_CANDIDATE_LIMIT = 6
COMPOSER_CONTEXT_MEMORY_RECORD_LIMIT = 4
COMPOSER_CONTEXT_OPEN_THREAD_LIMIT = 4
COMPOSER_CONTEXT_PREFERENCE_LIMIT = 4
COMPOSER_CONTEXT_PENDING_APPROVAL_LIMIT = 3
COMPOSER_CONTEXT_SESSION_SUMMARY_LIMIT = 1200
COMPOSER_CONTEXT_MEMORY_SUMMARY_LIMIT = 1200
COMPOSER_CONTEXT_WORKSPACE_FACT_LIMIT = 8
COMPOSER_CONTEXT_WORKSPACE_FILE_LIMIT = 8
COMPOSER_CONTEXT_WORKSPACE_QUERY_LIMIT = 6
COMPOSER_CONTEXT_URL_FACT_LIMIT = 8
COMPOSER_CONTEXT_URL_DOCUMENT_LIMIT = 5
COMPOSER_CONTEXT_URL_SNIPPET_LIMIT = 5
COMPOSER_CONTEXT_DELEGATED_FINDING_LIMIT = 6
COMPOSER_CONTEXT_DELEGATED_SOURCE_LIMIT = 6


def build_composer_context_payload(
    *,
    project_root: str | Path = ".",
    session_id: str | None = None,
    latest_artifact: Mapping[str, Any] | None = None,
    conversation_turn_limit: int = COMPOSER_CONTEXT_RECENT_TURN_LIMIT,
) -> dict[str, Any]:
    """Build the compact decision-state context used by response composers."""

    try:
        raw_context = compile_workspace_decision_context_payload(
            project_root=project_root,
            session_id=session_id,
        )
        store = LocalJsonStore.from_project_root(project_root)
        config = load_workspace_config(project_root)
        active_session_id = session_id or config.active_session_id
        session = load_or_create_session(store, session_id=active_session_id)
        recent_turns = _recent_conversation_turns(
            store,
            list(session.conversation_turn_ids),
            limit=conversation_turn_limit,
        )
        enriched = {
            **raw_context,
            "recent_conversation_turns": recent_turns,
            "latest_decision_artifact": _compact_latest_artifact(latest_artifact or {}),
        }
        workspace_context = _mapping((latest_artifact or {}).get("workspace_context"))
        if workspace_context:
            enriched["workspace_context"] = workspace_context
        url_context = _mapping((latest_artifact or {}).get("url_context"))
        if url_context:
            enriched["url_context"] = url_context
        delegated_context = _mapping(
            (latest_artifact or {}).get("delegated_perception_context")
        )
        if delegated_context:
            enriched["delegated_perception_context"] = delegated_context
        evidence_context = _mapping((latest_artifact or {}).get("evidence_context"))
        if evidence_context:
            enriched["evidence_context"] = evidence_context
        elif workspace_context or url_context or delegated_context:
            enriched["evidence_context"] = build_evidence_context(
                workspace_context=workspace_context,
                url_context=url_context,
                delegated_perception_context=delegated_context,
            )
        return compact_composer_context(enriched)
    except Exception as exc:
        return {
            "schema_version": COMPOSER_CONTEXT_SCHEMA_VERSION,
            "status": "unavailable",
            "error": str(exc),
        }


def compact_composer_context(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    session_summary = _mapping(payload.get("session_summary"))
    recent_executions = _list(payload.get("recent_executions")) or _list(payload.get("recent_outcomes"))
    status = str(payload.get("status") or "available")
    workspace_context = _compact_workspace_context(_mapping(payload.get("workspace_context")))
    url_context = _compact_url_context(_mapping(payload.get("url_context")))
    delegated_context = _compact_delegated_perception_context(
        _mapping(payload.get("delegated_perception_context"))
    )
    evidence_payload = _mapping(payload.get("evidence_context"))
    evidence_context = compact_evidence_context(evidence_payload) if evidence_payload else {}
    if not evidence_context and (workspace_context or url_context or delegated_context):
        evidence_context = compact_evidence_context(
            build_evidence_context(
                workspace_context=workspace_context,
                url_context=url_context,
                delegated_perception_context=delegated_context,
            )
        )
    return {
        "schema_version": COMPOSER_CONTEXT_SCHEMA_VERSION,
        "status": status,
        "error": _shorten(str(payload.get("error") or ""), 220),
        "current_intent": _compact_current_intent(_mapping(payload.get("current_intent"))),
        "active_decision_frame": _compact_active_frame(_mapping(payload.get("active_decision_frame"))),
        "latest_decision_artifact": _compact_latest_artifact(_mapping(payload.get("latest_decision_artifact"))),
        "recent_conversation_turns": [
            _compact_conversation_turn(_mapping(item))
            for item in _tail(_list(payload.get("recent_conversation_turns")), COMPOSER_CONTEXT_RECENT_TURN_LIMIT)
        ],
        "recent_decisions": [
            _compact_recent_decision(_mapping(item))
            for item in _tail(_list(payload.get("recent_decisions")), COMPOSER_CONTEXT_RECENT_DECISION_LIMIT)
        ],
        "recent_approvals": [
            _compact_recent_approval(_mapping(item))
            for item in _tail(_list(payload.get("recent_approvals")), COMPOSER_CONTEXT_RECENT_APPROVAL_LIMIT)
        ],
        "recent_executions": [
            _compact_recent_execution(_mapping(item))
            for item in _tail(recent_executions, COMPOSER_CONTEXT_RECENT_EXECUTION_LIMIT)
        ],
        "session_summary": _compact_session_summary(session_summary),
        "memory_summary": _compact_memory_summary(
            session_summary=session_summary,
            retrieved_memory=_list(payload.get("retrieved_memory")),
        ),
        "executor_affordance": _compact_executor_affordance(_mapping(payload.get("executor_affordance"))),
        "executor_capabilities": _compact_executor_capabilities(
            _mapping(payload.get("executor_capabilities"))
        ),
        "workspace_context": workspace_context,
        "url_context": url_context,
        "delegated_perception_context": delegated_context,
        "evidence_context": evidence_context,
    }


def _recent_conversation_turns(
    store: LocalJsonStore,
    turn_ids: list[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for turn_id in turn_ids[-max(0, limit) :]:
        try:
            result.append(_compact_conversation_turn(store.load_conversation_turn(turn_id)))
        except FileNotFoundError:
            continue
    return result


def _compact_current_intent(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "text": _shorten(str(payload.get("text") or ""), 360),
        "source": str(payload.get("source") or ""),
        "kind": str(payload.get("kind") or ""),
        "display_language": str(payload.get("display_language") or ""),
        "decision_id": str(payload.get("decision_id") or ""),
        "run_id": str(payload.get("run_id") or ""),
    }


def _compact_active_frame(payload: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(payload.get("selected"))
    candidates = []
    for item in _list(payload.get("candidates"))[:COMPOSER_CONTEXT_ACTIVE_CANDIDATE_LIMIT]:
        candidate = _mapping(item)
        candidates.append(
            {
                "label": str(candidate.get("label") or ""),
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "title": _shorten(str(candidate.get("title") or candidate.get("recommended_action") or ""), 180),
            }
        )
    return {
        "decision_id": str(payload.get("decision_id") or ""),
        "run_id": str(payload.get("run_id") or ""),
        "status": str(payload.get("status") or ""),
        "selected_candidate_id": str(payload.get("selected_candidate_id") or ""),
        "selected": {
            "label": str(selected.get("label") or ""),
            "candidate_id": str(selected.get("candidate_id") or ""),
            "title": _shorten(str(selected.get("title") or selected.get("recommended_action") or ""), 180),
        },
        "allowed_continuations": _strings(payload.get("allowed_continuations"))[:8],
        "candidates": candidates,
    }


def _compact_latest_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    brief = _mapping(payload.get("decision_brief"))
    selected = _mapping(brief.get("selected"))
    return {
        "run_id": str(payload.get("run_id") or brief.get("run_id") or ""),
        "decision_id": str(payload.get("decision_id") or brief.get("decision_id") or ""),
        "trace_ref": str(payload.get("trace_ref") or ""),
        "selected_candidate_id": str(payload.get("selected_candidate_id") or selected.get("candidate_id") or ""),
        "selected_title": _shorten(str(selected.get("title") or selected.get("recommendation") or ""), 180),
        "conversation_turn_id": str(payload.get("conversation_turn_id") or ""),
        "approval_id": str(payload.get("approval_id") or ""),
    }


def _compact_conversation_turn(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(payload.get("metadata"))
    follow_up = _mapping(metadata.get("follow_up_response"))
    execution = _mapping(metadata.get("execution_response"))
    response_summary = (
        follow_up.get("rendered_text")
        or follow_up.get("summary")
        or execution.get("response_text")
        or execution.get("summary")
        or payload.get("response_summary")
        or ""
    )
    return {
        "turn_id": str(payload.get("turn_id") or ""),
        "created_at": str(payload.get("created_at") or ""),
        "route": str(payload.get("route") or ""),
        "user_input": _shorten(str(payload.get("user_input") or ""), 300),
        "source_decision_id": str(payload.get("source_decision_id") or ""),
        "source_candidate_id": str(payload.get("source_candidate_id") or ""),
        "source_approval_id": str(payload.get("source_approval_id") or ""),
        "source_execution_id": str(payload.get("source_execution_id") or ""),
        "source_outcome_id": str(payload.get("source_outcome_id") or ""),
        "follow_up_action": str(
            metadata.get("follow_up_action")
            or follow_up.get("action")
            or execution.get("action")
            or payload.get("follow_up_action")
            or ""
        ),
        "response_summary": _shorten(str(response_summary), 360),
    }


def _compact_recent_decision(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": str(payload.get("decision_id") or ""),
        "trace_ref": str(payload.get("trace_ref") or ""),
        "selected_candidate_id": str(payload.get("selected_candidate_id") or ""),
        "status": str(payload.get("status") or ""),
        "recommendation": _shorten(str(payload.get("recommendation") or ""), 220),
        "approval_id": str(payload.get("approval_id") or ""),
    }


def _compact_recent_approval(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "approval_id": str(payload.get("approval_id") or ""),
        "decision_id": str(payload.get("decision_id") or ""),
        "candidate_id": str(payload.get("candidate_id") or ""),
        "status": str(payload.get("status") or ""),
        "execution_allowed": bool(payload.get("execution_allowed")),
    }


def _compact_recent_execution(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "outcome_id": str(payload.get("outcome_id") or payload.get("id") or ""),
        "decision_id": str(payload.get("decision_id") or ""),
        "candidate_id": str(payload.get("candidate_id") or ""),
        "executor": str(payload.get("executor") or ""),
        "status": str(payload.get("status") or payload.get("task_status") or ""),
        "summary": _shorten(str(payload.get("summary") or payload.get("state_delta_summary") or ""), 260),
    }


def _compact_session_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    rolling = _mapping(payload.get("rolling_summary"))
    return {
        "session_id": str(payload.get("session_id") or ""),
        "status": str(payload.get("status") or ""),
        "last_run_id": str(payload.get("last_run_id") or ""),
        "last_decision_id": str(payload.get("last_decision_id") or ""),
        "pending_approvals": _strings(payload.get("pending_approvals"))[:COMPOSER_CONTEXT_PENDING_APPROVAL_LIMIT],
        "summary_text": _shorten(str(payload.get("summary_text") or ""), COMPOSER_CONTEXT_SESSION_SUMMARY_LIMIT),
        "rolling_summary": {
            "id": str(rolling.get("id") or ""),
            "summary_type": str(rolling.get("summary_type") or ""),
            "updated_at": str(rolling.get("updated_at") or ""),
            "current_goal": _mapping(rolling.get("current_goal")),
            "active_decision": _mapping(rolling.get("active_decision")),
            "open_threads": _list(rolling.get("open_threads"))[:COMPOSER_CONTEXT_OPEN_THREAD_LIMIT],
            "user_preferences": _list(rolling.get("user_preferences"))[:COMPOSER_CONTEXT_PREFERENCE_LIMIT],
        },
    }


def _compact_memory_summary(
    *,
    session_summary: Mapping[str, Any],
    retrieved_memory: list[Any],
) -> dict[str, Any]:
    rolling = _mapping(session_summary.get("rolling_summary"))
    return {
        "summary_text": _shorten(str(session_summary.get("summary_text") or ""), COMPOSER_CONTEXT_MEMORY_SUMMARY_LIMIT),
        "current_goal": _mapping(rolling.get("current_goal")),
        "open_threads": _list(rolling.get("open_threads"))[:COMPOSER_CONTEXT_OPEN_THREAD_LIMIT],
        "retrieved": [
            _compact_memory_record(_mapping(item))
            for item in retrieved_memory[:COMPOSER_CONTEXT_MEMORY_RECORD_LIMIT]
        ],
    }


def _compact_memory_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(payload.get("id") or ""),
        "namespace": str(payload.get("namespace") or ""),
        "created_at": str(payload.get("created_at") or ""),
        "summary": _shorten(
            str(
                payload.get("response_summary")
                or payload.get("summary")
                or payload.get("markdown")
                or payload.get("user_input")
                or ""
            ),
            360,
        ),
    }


def _compact_executor_affordance(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "executor": str(payload.get("executor") or ""),
        "status": str(payload.get("status") or ""),
        "available": payload.get("available"),
        "permission_mode": str(payload.get("permission_mode") or ""),
        "approval_required": payload.get("approval_required"),
        "blocked_reason": str(payload.get("blocked_reason") or ""),
    }


def _compact_executor_capabilities(payload: Mapping[str, Any]) -> dict[str, Any]:
    compact = {
        "executor_id": str(payload.get("executor_id") or ""),
        "provider": str(payload.get("provider") or ""),
        "status": str(payload.get("status") or ""),
        "source": str(payload.get("source") or ""),
        "capability_ids": _strings(payload.get("capability_ids"))[:12],
        "skill_ids": _strings(payload.get("skill_ids"))[:12],
        "permission_modes": _strings(payload.get("permission_modes"))[:6],
        "summary": _shorten(str(payload.get("summary") or ""), 360),
        "limitations": [_shorten(item, 220) for item in _strings(payload.get("limitations"))[:6]],
    }
    metadata = _compact_executor_capability_metadata(_mapping(payload.get("metadata")))
    if metadata:
        compact["metadata"] = metadata
    return compact


def _compact_executor_capability_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed_scalar_keys = (
        "routing_model",
        "permission_enforcement",
        "permission_note",
    )
    compact: dict[str, Any] = {}
    for key in allowed_scalar_keys:
        value = str(payload.get(key) or "").strip()
        if value:
            compact[key] = _shorten(value, 260)
    policy_commands = _strings(payload.get("policy_commands"))[:4]
    if policy_commands:
        compact["policy_commands"] = [_shorten(item, 180) for item in policy_commands]
    recommended_policy = _mapping(payload.get("recommended_policy"))
    if recommended_policy:
        compact["recommended_policy"] = {
            str(key): _shorten(str(value or ""), 180)
            for key, value in sorted(recommended_policy.items(), key=lambda item: str(item[0]))
            if str(key).strip() and str(value or "").strip()
        }
    return compact


def _compact_workspace_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    compact = {
        "llm_provider": str(payload.get("llm_provider") or ""),
        "llm_model": str(payload.get("llm_model") or ""),
        "memory_provider": str(payload.get("memory_provider") or ""),
        "context_compiler": str(payload.get("context_compiler") or ""),
        "executor": str(payload.get("executor") or ""),
        "permission_mode": str(payload.get("permission_mode") or ""),
        "perception_provider": str(payload.get("perception_provider") or ""),
    }
    if payload.get("perception_id") or payload.get("source") == "workspace_perception":
        compact.update(
            {
                "schema_version": str(payload.get("schema_version") or ""),
                "source": str(payload.get("source") or "workspace_perception"),
                "perception_id": str(payload.get("perception_id") or ""),
                "workspace_root": _shorten(str(payload.get("workspace_root") or ""), 260),
                "trigger": str(payload.get("trigger") or ""),
                "summary": _shorten(str(payload.get("summary") or ""), 700),
                "queries": [
                    _compact_workspace_query(_mapping(item))
                    for item in _list(payload.get("queries"))[:COMPOSER_CONTEXT_WORKSPACE_QUERY_LIMIT]
                ],
                "files_read": [
                    _compact_workspace_file_read(_mapping(item))
                    for item in _list(payload.get("files_read"))[:COMPOSER_CONTEXT_WORKSPACE_FILE_LIMIT]
                ],
                "files_skipped": [
                    _compact_workspace_file_skipped(_mapping(item))
                    for item in _list(payload.get("files_skipped"))[:COMPOSER_CONTEXT_WORKSPACE_FILE_LIMIT]
                ],
                "facts": [
                    _compact_workspace_fact(_mapping(item))
                    for item in _list(payload.get("facts"))[:COMPOSER_CONTEXT_WORKSPACE_FACT_LIMIT]
                ],
                "snippets": [
                    _compact_workspace_snippet(_mapping(item))
                    for item in _list(payload.get("snippets"))[:COMPOSER_CONTEXT_WORKSPACE_FACT_LIMIT]
                ],
                "limits": _compact_workspace_limits(_mapping(payload.get("limits"))),
                "depth": str(payload.get("depth") or ""),
                "exploration_status": str(payload.get("exploration_status") or ""),
                "budget_used": _compact_workspace_budget_used(_mapping(payload.get("budget_used"))),
                "budget_pressure_events": [
                    _compact_budget_pressure_event(_mapping(item))
                    for item in _list(payload.get("budget_pressure_events"))[:8]
                ],
                "sufficiency_check": _compact_workspace_sufficiency_check(
                    _mapping(payload.get("sufficiency_check"))
                ),
                "limitations": [
                    _shorten(str(item), 220)
                    for item in _list(payload.get("limitations"))[:8]
                    if str(item)
                ],
            }
        )
        workspace_cache = _mapping(payload.get("workspace_summary_cache"))
        if workspace_cache:
            compact["workspace_summary_cache"] = _compact_workspace_summary_cache(workspace_cache)
    return compact


def _compact_workspace_summary_cache(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": str(payload.get("source") or "workspace_summary_cache"),
        "status": str(payload.get("status") or ""),
        "refreshed_at": str(payload.get("refreshed_at") or ""),
        "cache_key": str(payload.get("cache_key") or ""),
        "summary": _shorten(str(payload.get("summary") or ""), 500),
        "directory_summaries": [
            {
                "path": _shorten(str(item.get("path") or ""), 180),
                "purpose": _shorten(str(item.get("purpose") or ""), 220),
                "file_count": item.get("file_count"),
            }
            for item in _list(payload.get("directory_summaries"))[:16]
            if isinstance(item, Mapping)
        ],
        "file_summaries": [
            {
                "path": _shorten(str(item.get("path") or ""), 220),
                "purpose": _shorten(str(item.get("purpose") or ""), 220),
                "language": str(item.get("language") or ""),
            }
            for item in _list(payload.get("file_summaries"))[:24]
            if isinstance(item, Mapping)
        ],
        "package_metadata": _mapping(payload.get("package_metadata")),
        "test_structure": _mapping(payload.get("test_structure")),
    }


def _compact_workspace_query(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "query": _shorten(str(payload.get("query") or ""), 220),
        "query_type": str(payload.get("query_type") or ""),
        "path": _shorten(str(payload.get("path") or ""), 180),
        "file_glob": _shorten(str(payload.get("file_glob") or ""), 120),
        "limit": payload.get("limit"),
    }


def _compact_workspace_file_read(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _shorten(str(payload.get("path") or ""), 220),
        "chars_read": payload.get("chars_read"),
        "line_start": payload.get("line_start"),
        "line_end": payload.get("line_end"),
        "truncated": bool(payload.get("truncated")),
        "reason": _shorten(str(payload.get("reason") or ""), 180),
    }


def _compact_workspace_file_skipped(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _shorten(str(payload.get("path") or ""), 220),
        "reason": _shorten(str(payload.get("reason") or ""), 220),
    }


def _compact_workspace_fact(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "text": _shorten(str(payload.get("text") or ""), 360),
        "source_path": _shorten(str(payload.get("source_path") or ""), 220),
        "line_start": payload.get("line_start"),
        "line_end": payload.get("line_end"),
        "confidence": payload.get("confidence"),
    }


def _compact_workspace_snippet(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _shorten(str(payload.get("path") or ""), 220),
        "text": _shorten(str(payload.get("text") or ""), 500),
        "line_start": payload.get("line_start"),
        "line_end": payload.get("line_end"),
        "source": _shorten(str(payload.get("source") or ""), 80),
    }


def _compact_workspace_limits(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "max_files": payload.get("max_files"),
        "max_chars_per_file": payload.get("max_chars_per_file"),
        "total_char_budget": payload.get("total_char_budget"),
    }


def _compact_workspace_budget_used(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "depth": str(payload.get("depth") or ""),
        "rounds_used": payload.get("rounds_used"),
        "tool_calls_executed": payload.get("tool_calls_executed"),
        "tool_calls_blocked": payload.get("tool_calls_blocked"),
        "files_read_count": payload.get("files_read_count"),
        "chars_used": payload.get("chars_used"),
        "total_char_budget": payload.get("total_char_budget"),
        "budget_pressure": str(payload.get("budget_pressure") or ""),
    }


def _compact_budget_pressure_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "round_index": payload.get("round_index") or payload.get("round"),
        "stage": str(payload.get("stage") or ""),
        "budget_pressure": str(payload.get("budget_pressure") or payload.get("pressure") or ""),
    }


def _compact_workspace_sufficiency_check(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "sufficient_evidence": bool(payload.get("sufficient_evidence")),
        "can_answer_user_question": bool(payload.get("can_answer_user_question")),
        "remaining_gaps": [
            _shorten(str(item), 220)
            for item in _list(payload.get("remaining_gaps"))[:8]
            if str(item)
        ],
        "reason": _shorten(str(payload.get("reason") or ""), 300),
    }


def _compact_url_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "schema_version": str(payload.get("schema_version") or ""),
        "source": str(payload.get("source") or ""),
        "perception_id": str(payload.get("perception_id") or ""),
        "trigger": str(payload.get("trigger") or ""),
        "query": _shorten(str(payload.get("query") or ""), 220),
        "summary": _shorten(str(payload.get("summary") or ""), 700),
        "urls": _strings(payload.get("urls"))[:COMPOSER_CONTEXT_URL_DOCUMENT_LIMIT],
        "documents": [
            _compact_url_document(_mapping(item))
            for item in _list(payload.get("documents"))[:COMPOSER_CONTEXT_URL_DOCUMENT_LIMIT]
        ],
        "urls_skipped": [
            _compact_url_skipped(_mapping(item))
            for item in _list(payload.get("urls_skipped"))[:COMPOSER_CONTEXT_URL_DOCUMENT_LIMIT]
        ],
        "facts": [
            _compact_url_fact(_mapping(item))
            for item in _list(payload.get("facts"))[:COMPOSER_CONTEXT_URL_FACT_LIMIT]
        ],
        "snippets": [
            _compact_url_snippet(_mapping(item))
            for item in _list(payload.get("snippets"))[:COMPOSER_CONTEXT_URL_SNIPPET_LIMIT]
        ],
    }


def _compact_url_document(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "url": _shorten(str(payload.get("url") or ""), 360),
        "final_url": _shorten(str(payload.get("final_url") or ""), 360),
        "source_type": str(payload.get("source_type") or ""),
        "title": _shorten(str(payload.get("title") or ""), 220),
        "chars_read": payload.get("chars_read"),
        "truncated": bool(payload.get("truncated")),
    }


def _compact_url_skipped(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "url": _shorten(str(payload.get("url") or ""), 360),
        "reason": _shorten(str(payload.get("reason") or ""), 220),
    }


def _compact_url_fact(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "text": _shorten(str(payload.get("text") or ""), 420),
        "source_url": _shorten(str(payload.get("source_url") or ""), 360),
        "title": _shorten(str(payload.get("title") or ""), 220),
        "confidence": payload.get("confidence"),
    }


def _compact_url_snippet(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "url": _shorten(str(payload.get("url") or ""), 360),
        "title": _shorten(str(payload.get("title") or ""), 220),
        "text": _shorten(str(payload.get("text") or ""), 600),
        "source": _shorten(str(payload.get("source") or ""), 80),
    }


def _compact_delegated_perception_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "schema_version": str(payload.get("schema_version") or ""),
        "source": str(payload.get("source") or "delegated_perception"),
        "perception_id": str(payload.get("perception_id") or ""),
        "delegation_id": str(payload.get("delegation_id") or ""),
        "executor_id": str(payload.get("executor_id") or ""),
        "scope": str(payload.get("scope") or ""),
        "permission_mode": str(payload.get("permission_mode") or ""),
        "query": _shorten(str(payload.get("query") or ""), 260),
        "summary": _shorten(str(payload.get("summary") or ""), 700),
        "confidence": str(payload.get("confidence") or ""),
        "limitations": [
            _shorten(item, 240)
            for item in _strings(payload.get("limitations"))[:COMPOSER_CONTEXT_DELEGATED_SOURCE_LIMIT]
        ],
        "findings": [
            _compact_delegated_finding(_mapping(item))
            for item in _list(payload.get("findings"))[:COMPOSER_CONTEXT_DELEGATED_FINDING_LIMIT]
        ],
        "sources": [
            _compact_delegated_source(_mapping(item))
            for item in _list(payload.get("sources"))[:COMPOSER_CONTEXT_DELEGATED_SOURCE_LIMIT]
        ],
    }


def _compact_delegated_finding(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": str(payload.get("finding_id") or ""),
        "text": _shorten(str(payload.get("text") or ""), 420),
        "confidence": payload.get("confidence"),
        "source_refs": _strings(payload.get("source_refs"))[:6],
        "limitations": [_shorten(item, 180) for item in _strings(payload.get("limitations"))[:4]],
    }


def _compact_delegated_source(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": str(payload.get("source_id") or ""),
        "source_type": str(payload.get("source_type") or ""),
        "title": _shorten(str(payload.get("title") or ""), 220),
        "uri": _shorten(str(payload.get("uri") or ""), 360),
        "excerpt": _shorten(str(payload.get("excerpt") or ""), 520),
        "observed_by": str(payload.get("observed_by") or ""),
        "accessed_at": str(payload.get("accessed_at") or ""),
        "verification_status": str(payload.get("verification_status") or ""),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    return [str(item) for item in _list(value) if str(item)]


def _tail(values: list[Any], limit: int) -> list[Any]:
    if limit <= 0:
        return []
    return list(values[-limit:])


def _shorten(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    if limit <= 3:
        return "." * max(0, limit)
    return normalized[: max(0, limit - 3)].rstrip() + "..."
