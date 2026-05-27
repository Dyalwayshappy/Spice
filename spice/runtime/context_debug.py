from __future__ import annotations

from pathlib import Path
from typing import Any

from spice.decision.general import load_general_state
from spice.decision.general.types import payload_value
from spice.perception import build_evidence_context, delegated_perception_context_from_artifact
from spice.protocols import WorldState
from spice.runtime.executor_capabilities import config_with_executor_capability_snapshot
from spice.runtime.session import load_or_create_session
from spice.runtime.store import LocalJsonStore
from spice.runtime.workspace import (
    load_workspace_config,
    load_workspace_context_compiler,
    require_workspace,
)


def compile_workspace_decision_context_payload(
    *,
    project_root: str | Path = ".",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Compile the same general decision context exposed by the TUI /context command."""

    paths = require_workspace(project_root)
    store = LocalJsonStore(paths)
    config = load_workspace_config(project_root)
    config_payload = config_with_executor_capability_snapshot(config)
    state_payload = store.load_state()
    world_state = _world_state_from_workspace_payload(state_payload)
    general_state = load_general_state(world_state)
    active_session_id = session_id or config.active_session_id
    session = load_or_create_session(store, session_id=active_session_id)
    frame = _active_decision_frame_from_general_state(general_state)
    workspace_context = latest_workspace_context_from_store(store, session, active_frame=frame)
    url_context = latest_url_context_from_store(store, session, active_frame=frame)
    delegated_perception_context = latest_delegated_perception_context_from_store(
        store,
        session,
        active_frame=frame,
    )
    evidence_context = build_evidence_context(
        workspace_context=workspace_context,
        url_context=url_context,
        delegated_perception_context=delegated_perception_context,
    )
    compiler = load_workspace_context_compiler(project_root, config=config)
    context = compiler.compile_general_decision_context(
        world_state,
        general_state,
        current_intent=_context_current_intent(frame),
        active_decision_frame=frame,
        session=payload_value(session),
        config=config_payload,
        domain="general",
        workspace_context=workspace_context or None,
        url_context=url_context or None,
        delegated_perception_context=delegated_perception_context or None,
        evidence_context=evidence_context,
    )
    return payload_value(context)


def compile_workspace_debug_payload(
    *,
    project_root: str | Path = ".",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Return the latest workspace perception/debug payload for audit commands."""

    paths = require_workspace(project_root)
    store = LocalJsonStore(paths)
    config = load_workspace_config(project_root)
    state_payload = store.load_state()
    world_state = _world_state_from_workspace_payload(state_payload)
    general_state = load_general_state(world_state)
    active_session_id = session_id or config.active_session_id
    session = load_or_create_session(store, session_id=active_session_id)
    frame = _active_decision_frame_from_general_state(general_state)
    workspace_context = latest_workspace_context_from_store(store, session, active_frame=frame)
    url_context = latest_url_context_from_store(store, session, active_frame=frame)
    delegated_perception_context = latest_delegated_perception_context_from_store(
        store,
        session,
        active_frame=frame,
    )
    perception_id = str(workspace_context.get("perception_id") or "").strip()
    perception = _load_workspace_perception(store, perception_id) if perception_id else {}
    url_perception_id = str(url_context.get("perception_id") or "").strip()
    url_perception = _load_workspace_perception(store, url_perception_id) if url_perception_id else {}
    delegated_perception_id = str(
        delegated_perception_context.get("perception_id") or ""
    ).strip()
    delegated_perception = (
        _load_workspace_perception(store, delegated_perception_id)
        if delegated_perception_id
        else {}
    )
    workspace_loop_metadata = _workspace_loop_metadata(perception)
    workspace_budget_used = _workspace_budget_used_debug(
        perception,
        workspace_context,
        workspace_loop_metadata,
    )
    workspace_sufficiency = _workspace_sufficiency_check(
        perception,
        workspace_context,
        workspace_loop_metadata,
    )
    workspace_limitations = _workspace_limitations_debug(
        perception,
        workspace_context,
        workspace_loop_metadata,
    )
    workspace_budget_pressure_events = _workspace_budget_pressure_events(
        perception,
        workspace_context,
        workspace_loop_metadata,
    )
    evidence_context = build_evidence_context(
        workspace_context=workspace_context,
        url_context=url_context,
        delegated_perception_context=delegated_perception_context,
    )
    return {
        "schema_version": "spice.workspace_debug.v1",
        "status": "available" if workspace_context or url_context or delegated_perception_context else "empty",
        "session_id": active_session_id,
        "perception_id": perception_id,
        "workspace_context": workspace_context,
        "workspace_perception": perception,
        "url_perception_id": url_perception_id,
        "url_context": url_context,
        "url_perception": url_perception,
        "delegated_perception_id": delegated_perception_id,
        "delegated_perception_context": delegated_perception_context,
        "delegated_perception": delegated_perception,
        "evidence_context": evidence_context,
        "summary": str(perception.get("summary") or workspace_context.get("summary") or ""),
        "query": str(perception.get("query") or workspace_context.get("query") or ""),
        "files_read": _list(perception.get("files_read")) or _list(workspace_context.get("files_read")),
        "files_skipped": _list(perception.get("files_skipped")) or _list(workspace_context.get("files_skipped")),
        "tool_calls": _list(perception.get("tool_calls")),
        "blocked_tool_calls": _list(perception.get("blocked_tool_calls")),
        "facts": _list(perception.get("facts")) or _list(workspace_context.get("facts")),
        "snippets": _list(perception.get("snippets")) or _list(workspace_context.get("snippets")),
        "workspace_summary_cache": _mapping(
            workspace_context.get("workspace_summary_cache")
        )
        or _mapping(_mapping(perception.get("metadata")).get("workspace_summary_cache")),
        "budget": _mapping(perception.get("budget")),
        "limits": _mapping(perception.get("limits")) or _mapping(workspace_context.get("limits")),
        "depth": _workspace_depth(perception, workspace_context, workspace_loop_metadata),
        "rounds_used": _optional_int(workspace_budget_used.get("rounds_used")) or 0,
        "tool_calls_executed": _optional_int(workspace_budget_used.get("tool_calls_executed")) or 0,
        "blocked_tool_calls_count": _optional_int(workspace_budget_used.get("tool_calls_blocked")) or len(_list(perception.get("blocked_tool_calls"))),
        "chars_used": _optional_int(workspace_budget_used.get("chars_used")) or 0,
        "total_char_budget": _optional_int(workspace_budget_used.get("total_char_budget")) or 0,
        "exploration_status": _workspace_exploration_status(
            perception,
            workspace_context,
            workspace_loop_metadata,
        ),
        "budget_used": workspace_budget_used,
        "budget_pressure_events": workspace_budget_pressure_events,
        "limitations": workspace_limitations,
        "sufficiency_check": workspace_sufficiency,
        "evidence_sufficiency": _evidence_sufficiency_debug(workspace_sufficiency),
        "remaining_gaps": _list(workspace_sufficiency.get("remaining_gaps")),
    }


def compile_sources_debug_payload(
    *,
    project_root: str | Path = ".",
    session_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Return the auditable source projection for the latest decision response."""

    paths = require_workspace(project_root)
    store = LocalJsonStore(paths)
    config = load_workspace_config(project_root)
    state_payload = store.load_state()
    world_state = _world_state_from_workspace_payload(state_payload)
    general_state = load_general_state(world_state)
    active_session_id = session_id or config.active_session_id
    session = load_or_create_session(store, session_id=active_session_id)
    frame = _active_decision_frame_from_general_state(general_state)
    run_payload = _load_sources_run(store, session, frame=frame, run_id=run_id)
    selected_run_id = str(run_payload.get("run_id") or run_id or "")
    workspace_context = _workspace_context_from_run(run_payload) or latest_workspace_context_from_store(
        store, session, active_frame=frame
    )
    url_context = _url_context_from_run(run_payload) or latest_url_context_from_store(
        store, session, active_frame=frame
    )
    delegated_context = _delegated_perception_context_from_run(
        run_payload
    ) or latest_delegated_perception_context_from_store(store, session, active_frame=frame)
    workspace_perception_id = str(workspace_context.get("perception_id") or "").strip()
    workspace_perception = (
        _load_workspace_perception(store, workspace_perception_id) if workspace_perception_id else {}
    )
    url_perception_id = str(url_context.get("perception_id") or "").strip()
    url_perception = _load_workspace_perception(store, url_perception_id) if url_perception_id else {}
    delegated_perception_id = str(delegated_context.get("perception_id") or "").strip()
    delegated_perception = (
        _load_workspace_perception(store, delegated_perception_id)
        if delegated_perception_id
        else {}
    )
    workspace_sources = _workspace_sources(workspace_context, workspace_perception)
    url_sources = _url_sources(url_context, url_perception)
    delegated_sources = _delegated_sources(delegated_context, delegated_perception)
    evidence_context = build_evidence_context(
        workspace_context=workspace_context,
        url_context=url_context,
        delegated_perception_context=delegated_context,
    )
    status = (
        "available"
        if _sources_available(workspace_sources, url_sources, delegated_sources)
        else "empty"
    )
    return {
        "schema_version": "spice.sources_debug.v1",
        "status": status,
        "session_id": active_session_id,
        "run_id": selected_run_id,
        "decision_id": str(run_payload.get("decision_id") or frame.get("decision_id") or ""),
        "workspace": workspace_sources,
        "url": url_sources,
        "delegated": delegated_sources,
        "evidence_context": evidence_context,
        "artifacts": {
            "run": f".spice/runs/{selected_run_id}.json" if selected_run_id else "",
            "decision": (
                f".spice/decisions/{run_payload.get('decision_id')}.json"
                if run_payload.get("decision_id")
                else ""
            ),
            "workspace_perception": (
                f".spice/perceptions/{workspace_perception_id}.json" if workspace_perception_id else ""
            ),
            "url_perception": f".spice/perceptions/{url_perception_id}.json" if url_perception_id else "",
            "delegated_perception": (
                f".spice/perceptions/{delegated_perception_id}.json"
                if delegated_perception_id
                else ""
            ),
        },
    }


def render_decision_context_text(payload: dict[str, Any]) -> str:
    frame = _mapping(payload.get("active_decision_frame"))
    return "\n".join(
        [
            "COMPILED DECISION CONTEXT",
            f"context_id: {payload.get('id') or ''}",
            f"context_type: {payload.get('context_type') or ''}",
            f"current_intent: {_shorten(str(_mapping(payload.get('current_intent')).get('text') or ''), 120)}",
            f"active_decision: {frame.get('decision_id') or ''}",
            f"selected: {_context_selected_summary(frame)}",
            f"recent_decisions: {len(_list(payload.get('recent_decisions')))}",
            f"recent_approvals: {len(_list(payload.get('recent_approvals')))}",
            f"recent_outcomes: {len(_list(payload.get('recent_outcomes')))}",
            f"retrieved_memory: {len(_list(payload.get('retrieved_memory')))}",
            f"executor: {_executor_context_summary(_mapping(payload.get('executor_affordance')))}",
            f"executor_capabilities: {_executor_capabilities_summary(_mapping(payload.get('executor_capabilities')))}",
            f"summary: {_summary_context_summary(_mapping(payload.get('session_summary')))}",
            f"session: {_session_context_summary(_mapping(payload.get('session_summary')))}",
            f"workspace: {_workspace_context_summary(_mapping(payload.get('workspace_context')))}",
            f"url_context: {_url_context_summary(_mapping(payload.get('url_context')))}",
            f"delegated_perception: {_delegated_context_summary(_mapping(payload.get('delegated_perception_context')))}",
            f"evidence: {_evidence_context_summary(_mapping(payload.get('evidence_context')))}",
            "Use `spice context --json` to inspect the exact payload.",
        ]
    )


def render_workspace_debug_text(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "empty")
    if status != "available":
        return "\n".join(
            [
                "WORKSPACE PERCEPTION",
                "status: empty",
                "No workspace perception has been recorded for this session yet.",
                "Ask a repo-aware question, then use /workspace or /workspace --json.",
            ]
        )

    files_read = _list(payload.get("files_read"))
    files_skipped = _list(payload.get("files_skipped"))
    facts = _list(payload.get("facts"))
    tool_calls = _list(payload.get("tool_calls"))
    blocked = _list(payload.get("blocked_tool_calls"))
    workspace_cache = _mapping(payload.get("workspace_summary_cache"))
    url_context = _mapping(payload.get("url_context"))
    url_perception = _mapping(payload.get("url_perception"))
    url_documents = _list(url_perception.get("documents")) or _list(url_context.get("documents"))
    urls_skipped = _list(url_perception.get("urls_skipped")) or _list(url_context.get("urls_skipped"))
    url_facts = _list(url_perception.get("facts")) or _list(url_context.get("facts"))
    delegated_context = _mapping(payload.get("delegated_perception_context"))
    delegated_perception = _mapping(payload.get("delegated_perception"))
    delegated_findings = _list(delegated_perception.get("findings")) or _list(
        delegated_context.get("findings")
    )
    delegated_sources = _list(delegated_perception.get("sources")) or _list(
        delegated_context.get("sources")
    )
    lines = [
        "WORKSPACE PERCEPTION",
        f"status: {status}",
        f"perception_id: {payload.get('perception_id') or ''}",
        f"query: {_shorten(str(payload.get('query') or ''), 160)}",
        f"summary: {_shorten(str(payload.get('summary') or ''), 220)}",
        f"depth: {payload.get('depth') or ''}",
        f"rounds_used: {payload.get('rounds_used') or 0}",
        f"tool_calls_executed: {payload.get('tool_calls_executed') or len([call for call in tool_calls if str(_mapping(call).get('status') or '') == 'executed'])}",
        f"blocked_tool_calls: {payload.get('blocked_tool_calls_count') or len(blocked)}",
        f"files_read: {len(files_read)}",
        f"files_skipped: {len(files_skipped)}",
        f"chars_used: {payload.get('chars_used') or 0} / {payload.get('total_char_budget') or 0}",
        f"exploration_status: {payload.get('exploration_status') or ''}",
        f"evidence_sufficiency: {payload.get('evidence_sufficiency') or 'unknown'}",
        f"facts: {len(facts)}",
    ]
    if workspace_cache:
        lines.append(
            "workspace_cache: "
            f"{workspace_cache.get('status') or 'available'}; "
            f"{len(_list(workspace_cache.get('directory_summaries')))} dirs; "
            f"{len(_list(workspace_cache.get('file_summaries')))} files"
        )
    budget = _mapping(payload.get("budget"))
    if budget:
        lines.append(f"budget: {_budget_summary(budget)}")
    budget_pressure_events = _list(payload.get("budget_pressure_events"))
    if budget_pressure_events:
        lines.append("")
        lines.append("Budget pressure events:")
        for item in budget_pressure_events[:6]:
            mapping = _mapping(item)
            pressure = str(mapping.get("budget_pressure") or mapping.get("pressure") or "")
            stage = str(mapping.get("stage") or "")
            round_value = mapping.get("round_index") or mapping.get("round")
            parts = [f"round={round_value}" if round_value is not None else "", f"stage={stage}" if stage else "", pressure]
            lines.append(f"- {' '.join(part for part in parts if part)}")
    remaining_gaps = _list(payload.get("remaining_gaps"))
    if remaining_gaps:
        lines.append("")
        lines.append("Remaining gaps:")
        for item in remaining_gaps[:6]:
            lines.append(f"- {_shorten(str(item), 180)}")
    limitations = _list(payload.get("limitations"))
    if limitations:
        lines.append("")
        lines.append("Limitations:")
        for item in limitations[:8]:
            lines.append(f"- {_shorten(str(item), 180)}")
    if files_read:
        lines.append("")
        lines.append("Files read:")
        for item in files_read[:8]:
            path = str(_mapping(item).get("path") or "")
            chars = _mapping(item).get("chars_read")
            suffix = f" ({chars} chars)" if chars is not None else ""
            lines.append(f"- {path}{suffix}")
    if facts:
        lines.append("")
        lines.append("Facts:")
        for item in facts[:8]:
            mapping = _mapping(item)
            text = _shorten(str(mapping.get("text") or ""), 180)
            source = str(mapping.get("source_path") or "")
            lines.append(f"- {text}" + (f" [{source}]" if source else ""))
    if url_context:
        lines.append("")
        lines.append("URL perception:")
        lines.append(f"- perception_id: {payload.get('url_perception_id') or url_context.get('perception_id') or ''}")
        lines.append(f"- query: {_shorten(str(url_perception.get('query') or url_context.get('query') or ''), 160)}")
        lines.append(f"- summary: {_shorten(str(url_perception.get('summary') or url_context.get('summary') or ''), 220)}")
        lines.append(f"- documents: {len(url_documents)}")
        lines.append(f"- urls_skipped: {len(urls_skipped)}")
        lines.append(f"- facts: {len(url_facts)}")
        if url_documents:
            lines.append("")
            lines.append("URLs read:")
            for item in url_documents[:6]:
                mapping = _mapping(item)
                title = _shorten(str(mapping.get("title") or ""), 90)
                url = _shorten(str(mapping.get("url") or mapping.get("final_url") or ""), 140)
                source = str(mapping.get("source_type") or "")
                parts = [part for part in [title, url, source] if part]
                lines.append(f"- {' | '.join(parts)}")
        if url_facts:
            lines.append("")
            lines.append("URL facts:")
            for item in url_facts[:6]:
                mapping = _mapping(item)
                text = _shorten(str(mapping.get("text") or ""), 180)
                source = str(mapping.get("source_url") or "")
                lines.append(f"- {text}" + (f" [{_shorten(source, 100)}]" if source else ""))
    if delegated_context:
        lines.append("")
        lines.append("Delegated perception:")
        lines.append(f"- perception_id: {payload.get('delegated_perception_id') or delegated_context.get('perception_id') or ''}")
        lines.append(f"- executor: {delegated_context.get('executor_id') or ''}")
        lines.append(f"- query: {_shorten(str(delegated_context.get('query') or ''), 160)}")
        lines.append(f"- summary: {_shorten(str(delegated_context.get('summary') or ''), 220)}")
        lines.append(f"- findings: {len(delegated_findings)}")
        lines.append(f"- sources: {len(delegated_sources)}")
        if delegated_findings:
            lines.append("")
            lines.append("Delegated findings:")
            for item in delegated_findings[:6]:
                mapping = _mapping(item)
                text = _shorten(str(mapping.get("text") or ""), 180)
                refs = ", ".join(str(ref) for ref in _list(mapping.get("source_refs"))[:3])
                lines.append(f"- {text}" + (f" [{refs}]" if refs else ""))
    lines.append("")
    lines.append("Use /workspace --json to inspect tool calls, skipped files, snippets, and budgets.")
    return "\n".join(lines)


def render_sources_debug_text(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "empty")
    if status != "available":
        return "\n".join(
            [
                "SOURCES",
                "status: empty",
                "No repo, URL, or delegated perception sources are linked to the latest decision yet.",
                "Ask a repo-aware, link-aware, or investigation-aware question, then use /sources or /sources --json.",
            ]
        )

    workspace = _mapping(payload.get("workspace"))
    url_sources = _mapping(payload.get("url"))
    delegated = _mapping(payload.get("delegated"))
    artifacts = _mapping(payload.get("artifacts"))
    lines = [
        "SOURCES",
        f"status: {status}",
        f"run_id: {payload.get('run_id') or ''}",
        f"decision_id: {payload.get('decision_id') or ''}",
    ]
    evidence = _mapping(payload.get("evidence_context"))
    if evidence:
        lines.append(f"evidence: {_evidence_context_summary(evidence)}")
    if _sources_available(workspace, {}):
        lines.extend(_render_workspace_sources_lines(workspace))
    if _sources_available({}, url_sources):
        lines.extend(_render_url_sources_lines(url_sources))
    if _sources_available({}, {}, delegated):
        lines.extend(_render_delegated_sources_lines(delegated))
    artifact_lines = [
        ("run", artifacts.get("run")),
        ("decision", artifacts.get("decision")),
        ("workspace_perception", artifacts.get("workspace_perception")),
        ("url_perception", artifacts.get("url_perception")),
        ("delegated_perception", artifacts.get("delegated_perception")),
    ]
    visible_artifacts = [(label, value) for label, value in artifact_lines if str(value or "")]
    if visible_artifacts:
        lines.append("")
        lines.append("Artifacts:")
        for label, value in visible_artifacts:
            lines.append(f"- {label}: {value}")
    lines.append("")
    lines.append("Use /sources --json for exact source records and snippets.")
    return "\n".join(lines)


def latest_workspace_context_from_store(
    store: LocalJsonStore,
    session: Any,
    *,
    active_frame: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the latest compact workspace perception context linked to the session."""

    for run_id in _candidate_run_ids(session, active_frame or {}):
        try:
            run = store.load_run(run_id)
        except Exception:
            continue
        workspace = _workspace_context_from_run(run)
        if workspace:
            return workspace
    return {}


def latest_url_context_from_store(
    store: LocalJsonStore,
    session: Any,
    *,
    active_frame: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the latest compact URL perception context linked to the session."""

    for run_id in _candidate_run_ids(session, active_frame or {}):
        try:
            run = store.load_run(run_id)
        except Exception:
            continue
        url_context = _url_context_from_run(run)
        if url_context:
            return url_context
    return {}


def latest_delegated_perception_context_from_store(
    store: LocalJsonStore,
    session: Any,
    *,
    active_frame: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the latest delegated perception context linked to the session."""

    for run_id in _candidate_run_ids(session, active_frame or {}):
        try:
            run = store.load_run(run_id)
        except Exception:
            continue
        delegated = _delegated_perception_context_from_run(run)
        if delegated:
            return delegated
    return _latest_delegated_perception_context_from_perceptions(store)


def _latest_delegated_perception_context_from_perceptions(store: LocalJsonStore) -> dict[str, Any]:
    for perception_id in reversed(store.list_record_ids("perceptions")):
        try:
            perception = store.load_perception(perception_id)
        except Exception:
            continue
        if str(perception.get("schema_version") or "") != "spice.delegated_perception.v1":
            continue
        try:
            return delegated_perception_context_from_artifact(perception)
        except Exception:
            continue
    return {}


def _load_workspace_perception(store: LocalJsonStore, perception_id: str) -> dict[str, Any]:
    try:
        return store.load_perception(perception_id)
    except Exception:
        return {}


def _load_sources_run(
    store: LocalJsonStore,
    session: Any,
    *,
    frame: dict[str, Any],
    run_id: str | None,
) -> dict[str, Any]:
    requested = str(run_id or "").strip()
    if requested:
        try:
            return store.load_run(requested)
        except Exception:
            return {"run_id": requested}
    for candidate in _candidate_run_ids(session, frame):
        try:
            return store.load_run(candidate)
        except Exception:
            continue
    return {}


def _workspace_loop_metadata(workspace_perception: dict[str, Any]) -> dict[str, Any]:
    metadata = _mapping(workspace_perception.get("metadata"))
    return _mapping(metadata.get("loop"))


def _workspace_budget_used_debug(
    workspace_perception: dict[str, Any],
    workspace_context: dict[str, Any],
    loop_metadata: dict[str, Any],
) -> dict[str, Any]:
    metadata = _mapping(workspace_perception.get("metadata"))
    for value in (
        workspace_perception.get("budget_used"),
        workspace_context.get("budget_used"),
        metadata.get("budget_used"),
        loop_metadata.get("budget_used"),
    ):
        payload = _mapping(value)
        if payload:
            return payload
    return {}


def _workspace_sufficiency_check(
    workspace_perception: dict[str, Any],
    workspace_context: dict[str, Any],
    loop_metadata: dict[str, Any],
) -> dict[str, Any]:
    metadata = _mapping(workspace_perception.get("metadata"))
    for value in (
        workspace_perception.get("sufficiency_check"),
        workspace_context.get("sufficiency_check"),
        metadata.get("sufficiency_check"),
        loop_metadata.get("sufficiency_check"),
    ):
        payload = _mapping(value)
        if payload:
            return payload
    return {}


def _workspace_limitations_debug(
    workspace_perception: dict[str, Any],
    workspace_context: dict[str, Any],
    loop_metadata: dict[str, Any],
) -> list[Any]:
    metadata = _mapping(workspace_perception.get("metadata"))
    for value in (
        workspace_perception.get("limitations"),
        workspace_context.get("limitations"),
        metadata.get("limitations"),
        loop_metadata.get("limitations"),
    ):
        items = _list(value)
        if items:
            return items
    return []


def _workspace_budget_pressure_events(
    workspace_perception: dict[str, Any],
    workspace_context: dict[str, Any],
    loop_metadata: dict[str, Any],
) -> list[Any]:
    metadata = _mapping(workspace_perception.get("metadata"))
    for value in (
        workspace_perception.get("budget_pressure_events"),
        workspace_context.get("budget_pressure_events"),
        metadata.get("budget_pressure_events"),
        loop_metadata.get("budget_pressure_events"),
    ):
        items = _list(value)
        if items:
            return items
    return []


def _workspace_depth(
    workspace_perception: dict[str, Any],
    workspace_context: dict[str, Any],
    loop_metadata: dict[str, Any],
) -> str:
    metadata = _mapping(workspace_perception.get("metadata"))
    return str(
        workspace_perception.get("depth")
        or workspace_context.get("depth")
        or metadata.get("depth")
        or loop_metadata.get("depth")
        or ""
    )


def _workspace_exploration_status(
    workspace_perception: dict[str, Any],
    workspace_context: dict[str, Any],
    loop_metadata: dict[str, Any],
) -> str:
    metadata = _mapping(workspace_perception.get("metadata"))
    return str(
        workspace_perception.get("exploration_status")
        or workspace_context.get("exploration_status")
        or metadata.get("exploration_status")
        or loop_metadata.get("exploration_status")
        or ""
    )


def _evidence_sufficiency_debug(sufficiency_check: dict[str, Any]) -> str:
    if not sufficiency_check:
        return "unknown"
    sufficient = bool(sufficiency_check.get("sufficient_evidence"))
    can_answer = bool(sufficiency_check.get("can_answer_user_question"))
    if sufficient and can_answer:
        return "sufficient"
    if can_answer:
        return "partial"
    return "insufficient"


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _workspace_sources(
    workspace_context: dict[str, Any],
    workspace_perception: dict[str, Any],
) -> dict[str, Any]:
    perception = workspace_perception or {}
    context = workspace_context or {}
    loop_metadata = _workspace_loop_metadata(perception)
    budget_used = _workspace_budget_used_debug(perception, context, loop_metadata)
    sufficiency_check = _workspace_sufficiency_check(perception, context, loop_metadata)
    tool_calls = _list(perception.get("tool_calls"))
    files_read = _list(perception.get("files_read")) or _list(context.get("files_read"))
    snippets = _list(perception.get("snippets")) or _list(context.get("snippets"))
    return {
        "source": "workspace_perception" if context or perception else "",
        "perception_id": str(perception.get("perception_id") or context.get("perception_id") or ""),
        "query": str(perception.get("query") or context.get("query") or ""),
        "summary": str(perception.get("summary") or context.get("summary") or ""),
        "files_read": files_read,
        "files_skipped": _list(perception.get("files_skipped")) or _list(context.get("files_skipped")),
        "search_matches": _search_matches_from_tool_calls(tool_calls),
        "snippets": snippets,
        "facts": _list(perception.get("facts")) or _list(context.get("facts")),
        "git_status": _tool_results(tool_calls, "git_status"),
        "git_diff": _tool_results(tool_calls, "git_diff"),
        "git_log": _tool_results(tool_calls, "git_log"),
        "python_symbol_index": _tool_results(tool_calls, "python_symbol_index"),
        "python_symbol_reads": _tool_results(tool_calls, "read_python_symbol"),
        "tool_calls": _compact_source_tool_calls(tool_calls),
        "blocked_tool_calls": _compact_source_tool_calls(_list(perception.get("blocked_tool_calls"))),
        "budget": _mapping(perception.get("budget")),
        "limits": _mapping(perception.get("limits")) or _mapping(context.get("limits")),
        "depth": _workspace_depth(perception, context, loop_metadata),
        "rounds_used": _optional_int(budget_used.get("rounds_used")) or 0,
        "tool_calls_executed": _optional_int(budget_used.get("tool_calls_executed")) or 0,
        "blocked_tool_calls_count": _optional_int(budget_used.get("tool_calls_blocked")) or len(_list(perception.get("blocked_tool_calls"))),
        "chars_used": _optional_int(budget_used.get("chars_used")) or 0,
        "total_char_budget": _optional_int(budget_used.get("total_char_budget")) or 0,
        "exploration_status": _workspace_exploration_status(perception, context, loop_metadata),
        "budget_used": budget_used,
        "budget_pressure_events": _workspace_budget_pressure_events(perception, context, loop_metadata),
        "limitations": _workspace_limitations_debug(perception, context, loop_metadata),
        "sufficiency_check": sufficiency_check,
        "evidence_sufficiency": _evidence_sufficiency_debug(sufficiency_check),
        "remaining_gaps": _list(sufficiency_check.get("remaining_gaps")),
    }


def _url_sources(url_context: dict[str, Any], url_perception: dict[str, Any]) -> dict[str, Any]:
    perception = url_perception or {}
    context = url_context or {}
    return {
        "source": "url_perception" if context or perception else "",
        "perception_id": str(perception.get("perception_id") or context.get("perception_id") or ""),
        "query": str(perception.get("query") or context.get("query") or ""),
        "summary": str(perception.get("summary") or context.get("summary") or ""),
        "urls": _list(perception.get("urls")) or _list(context.get("urls")),
        "documents": _list(perception.get("documents")) or _list(context.get("documents")),
        "urls_skipped": _list(perception.get("urls_skipped")) or _list(context.get("urls_skipped")),
        "facts": _list(perception.get("facts")) or _list(context.get("facts")),
        "snippets": _list(perception.get("snippets")) or _list(context.get("snippets")),
        "budget": _mapping(perception.get("budget")),
        "limits": _mapping(perception.get("limits")),
    }


def _delegated_sources(
    delegated_context: dict[str, Any],
    delegated_perception: dict[str, Any],
) -> dict[str, Any]:
    perception = delegated_perception or {}
    context = delegated_context or {}
    return {
        "source": "delegated_perception" if context or perception else "",
        "perception_id": str(perception.get("perception_id") or context.get("perception_id") or ""),
        "delegation_id": str(perception.get("delegation_id") or context.get("delegation_id") or ""),
        "executor_id": str(perception.get("executor_id") or context.get("executor_id") or ""),
        "consent_id": str(perception.get("consent_id") or context.get("consent_id") or ""),
        "executor_report_ref": str(
            perception.get("executor_report_ref") or context.get("executor_report_ref") or ""
        ),
        "executor_run_ref": str(
            perception.get("executor_run_ref") or context.get("executor_run_ref") or ""
        ),
        "query": str(perception.get("query") or context.get("query") or ""),
        "summary": str(perception.get("summary") or context.get("summary") or ""),
        "findings": _list(perception.get("findings")) or _list(context.get("findings")),
        "sources": _list(perception.get("sources")) or _list(context.get("sources")),
        "limitations": _list(perception.get("limitations")) or _list(context.get("limitations")),
        "confidence": str(perception.get("confidence") or context.get("confidence") or ""),
    }


def _sources_available(
    workspace: dict[str, Any],
    url_sources: dict[str, Any],
    delegated_sources: dict[str, Any] | None = None,
) -> bool:
    delegated_sources = delegated_sources or {}
    return bool(
        workspace.get("perception_id")
        or _list(workspace.get("files_read"))
        or _list(workspace.get("search_matches"))
        or _list(workspace.get("snippets"))
        or _list(workspace.get("git_diff"))
        or _list(workspace.get("git_log"))
        or _list(workspace.get("python_symbol_index"))
        or _list(workspace.get("python_symbol_reads"))
        or url_sources.get("perception_id")
        or _list(url_sources.get("documents"))
        or _list(url_sources.get("snippets"))
        or _list(url_sources.get("facts"))
        or delegated_sources.get("perception_id")
        or _list(delegated_sources.get("findings"))
        or _list(delegated_sources.get("sources"))
    )


def _search_matches_from_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for call in tool_calls:
        payload = _mapping(call)
        if str(payload.get("tool") or "") != "search":
            continue
        result = _mapping(payload.get("result"))
        for item in _list(result.get("matches")):
            match = _mapping(item)
            if match:
                matches.append(
                    {
                        "path": str(match.get("path") or ""),
                        "line": match.get("line") or match.get("line_number"),
                        "text": str(match.get("text") or match.get("line_text") or ""),
                        "pattern": str(_mapping(payload.get("args")).get("pattern") or ""),
                    }
                )
    return matches


def _tool_results(tool_calls: list[Any], tool: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for call in tool_calls:
        payload = _mapping(call)
        if str(payload.get("tool") or "") != tool:
            continue
        result = _mapping(payload.get("result"))
        if result:
            results.append(result)
    return results


def _compact_source_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for call in tool_calls:
        payload = _mapping(call)
        result = _mapping(payload.get("result"))
        compact.append(
            {
                "call_id": str(payload.get("call_id") or ""),
                "round_index": payload.get("round_index"),
                "tool": str(payload.get("tool") or ""),
                "status": str(payload.get("status") or ""),
                "reason": str(payload.get("reason") or ""),
                "args": _mapping(payload.get("args")),
                "result_summary": _tool_result_summary(result),
            }
        )
    return compact


def _tool_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("ok", "path", "mode", "reason", "truncated", "content_omitted"):
        if key in result:
            summary[key] = result.get(key)
    for key in (
        "matches",
        "entries",
        "files",
        "test_files",
        "files_read",
        "files_skipped",
        "symbols",
        "imports",
        "modules",
    ):
        if isinstance(result.get(key), list):
            summary[f"{key}_count"] = len(_list(result.get(key)))
    if result.get("chars_read") is not None:
        summary["chars_read"] = result.get("chars_read")
    return summary


def _render_workspace_sources_lines(workspace: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "Workspace sources: Spice inspected directly",
        f"- perception_id: {workspace.get('perception_id') or ''}",
        f"- query: {_shorten(str(workspace.get('query') or ''), 160)}",
        f"- summary: {_shorten(str(workspace.get('summary') or ''), 220)}",
        f"- depth: {workspace.get('depth') or ''}",
        f"- rounds_used: {workspace.get('rounds_used') or 0}",
        f"- tool_calls_executed: {workspace.get('tool_calls_executed') or 0}",
        f"- blocked_tool_calls: {workspace.get('blocked_tool_calls_count') or 0}",
        f"- chars_used: {workspace.get('chars_used') or 0} / {workspace.get('total_char_budget') or 0}",
        f"- exploration_status: {workspace.get('exploration_status') or ''}",
        f"- evidence_sufficiency: {workspace.get('evidence_sufficiency') or 'unknown'}",
    ]
    files_read = _list(workspace.get("files_read"))
    search_matches = _list(workspace.get("search_matches"))
    snippets = _list(workspace.get("snippets"))
    git_diff = _list(workspace.get("git_diff"))
    git_log = _list(workspace.get("git_log"))
    python_symbol_index = _list(workspace.get("python_symbol_index"))
    python_symbol_reads = _list(workspace.get("python_symbol_reads"))
    lines.append(f"- files_read: {len(files_read)}")
    lines.append(f"- search_matches: {len(search_matches)}")
    lines.append(f"- snippets: {len(snippets)}")
    lines.append(f"- git_diff: {len(git_diff)}")
    lines.append(f"- git_log: {len(git_log)}")
    lines.append(f"- python_symbol_index: {len(python_symbol_index)}")
    lines.append(f"- python_symbol_reads: {len(python_symbol_reads)}")
    budget_pressure_events = _list(workspace.get("budget_pressure_events"))
    if budget_pressure_events:
        lines.append("")
        lines.append("Budget pressure events:")
        for item in budget_pressure_events[:6]:
            mapping = _mapping(item)
            pressure = str(mapping.get("budget_pressure") or mapping.get("pressure") or "")
            stage = str(mapping.get("stage") or "")
            round_value = mapping.get("round_index") or mapping.get("round")
            parts = [f"round={round_value}" if round_value is not None else "", f"stage={stage}" if stage else "", pressure]
            lines.append(f"- {' '.join(part for part in parts if part)}")
    remaining_gaps = _list(workspace.get("remaining_gaps"))
    if remaining_gaps:
        lines.append("")
        lines.append("Remaining gaps:")
        for item in remaining_gaps[:6]:
            lines.append(f"- {_shorten(str(item), 180)}")
    limitations = _list(workspace.get("limitations"))
    if limitations:
        lines.append("")
        lines.append("Limitations:")
        for item in limitations[:8]:
            lines.append(f"- {_shorten(str(item), 180)}")
    if files_read:
        lines.append("")
        lines.append("Files read:")
        for item in files_read[:10]:
            mapping = _mapping(item)
            location = _line_range(mapping)
            chars = mapping.get("chars_read")
            suffix = f" ({chars} chars)" if chars is not None else ""
            lines.append(f"- {mapping.get('path') or ''}{location}{suffix}")
    if search_matches:
        lines.append("")
        lines.append("Search matches:")
        for item in search_matches[:10]:
            mapping = _mapping(item)
            location = f":{mapping.get('line')}" if mapping.get("line") else ""
            text = _shorten(str(mapping.get("text") or ""), 140)
            pattern = str(mapping.get("pattern") or "")
            lines.append(f"- {mapping.get('path') or ''}{location}: {text}" + (f" [pattern: {pattern}]" if pattern else ""))
    if snippets:
        lines.append("")
        lines.append("Snippets:")
        for item in snippets[:8]:
            mapping = _mapping(item)
            source = str(mapping.get("source") or "")
            text = _shorten(str(mapping.get("text") or ""), 160)
            lines.append(f"- {mapping.get('path') or ''}{_line_range(mapping)}: {text}" + (f" [{source}]" if source else ""))
    if git_diff:
        lines.append("")
        lines.append("Git diff:")
        for item in git_diff[:4]:
            mapping = _mapping(item)
            path = str(mapping.get("path") or "workspace")
            mode = str(mapping.get("mode") or "")
            preview = _shorten(str(mapping.get("content_preview") or mapping.get("summary") or ""), 160)
            lines.append(f"- {path} {mode}: {preview}".rstrip())
    if git_log:
        lines.append("")
        lines.append("Git log:")
        for result in git_log[:2]:
            for entry in _list(_mapping(result).get("entries"))[:5]:
                mapping = _mapping(entry)
                lines.append(
                    f"- {mapping.get('sha') or ''} {_shorten(str(mapping.get('subject') or ''), 120)}".rstrip()
                )
    if python_symbol_index:
        lines.append("")
        lines.append("Python symbol index:")
        for result in python_symbol_index[:3]:
            mapping = _mapping(result)
            modules = _list(mapping.get("modules"))
            symbols = _list(mapping.get("symbols"))
            imports = _list(mapping.get("imports"))
            lines.append(
                f"- {mapping.get('path') or '.'}: modules={len(modules)} symbols={len(symbols)} imports={len(imports)}"
            )
            for symbol in symbols[:8]:
                item = _mapping(symbol)
                location = _line_range(item)
                lines.append(
                    f"  - {item.get('qualified_name') or item.get('name') or ''} "
                    f"{item.get('kind') or ''} {item.get('path') or ''}{location}".rstrip()
                )
    if python_symbol_reads:
        lines.append("")
        lines.append("Python symbols read:")
        for result in python_symbol_reads[:8]:
            mapping = _mapping(result)
            qualified = str(mapping.get("qualified_name") or mapping.get("name") or "")
            lines.append(
                f"- {qualified} {mapping.get('path') or ''}{_line_range(mapping)}".rstrip()
            )
    return lines


def _render_url_sources_lines(url_sources: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "URL sources: Spice fetched directly",
        f"- perception_id: {url_sources.get('perception_id') or ''}",
        f"- query: {_shorten(str(url_sources.get('query') or ''), 160)}",
        f"- summary: {_shorten(str(url_sources.get('summary') or ''), 220)}",
    ]
    documents = _list(url_sources.get("documents"))
    snippets = _list(url_sources.get("snippets"))
    facts = _list(url_sources.get("facts"))
    skipped = _list(url_sources.get("urls_skipped"))
    lines.append(f"- documents: {len(documents)}")
    lines.append(f"- snippets: {len(snippets)}")
    lines.append(f"- facts: {len(facts)}")
    lines.append(f"- skipped: {len(skipped)}")
    if documents:
        lines.append("")
        lines.append("URLs read:")
        for item in documents[:8]:
            mapping = _mapping(item)
            title = _shorten(str(mapping.get("title") or ""), 90)
            url = _shorten(str(mapping.get("url") or mapping.get("final_url") or ""), 150)
            source_type = str(mapping.get("source_type") or "")
            parts = [part for part in [title, url, source_type] if part]
            lines.append(f"- {' | '.join(parts)}")
    if snippets:
        lines.append("")
        lines.append("URL snippets:")
        for item in snippets[:6]:
            mapping = _mapping(item)
            url = _shorten(str(mapping.get("url") or ""), 120)
            text = _shorten(str(mapping.get("text") or ""), 160)
            lines.append(f"- {url}: {text}")
    if facts:
        lines.append("")
        lines.append("URL facts:")
        for item in facts[:6]:
            mapping = _mapping(item)
            source = _shorten(str(mapping.get("source_url") or ""), 110)
            text = _shorten(str(mapping.get("text") or ""), 170)
            lines.append(f"- {text}" + (f" [{source}]" if source else ""))
    return lines


def _render_delegated_sources_lines(delegated: dict[str, Any]) -> list[str]:
    executor = str(delegated.get("executor_id") or "executor")
    executor_label = _executor_display_name(executor)
    lines = [
        "",
        f"Delegated sources: {executor_label} reported",
        f"- perception_id: {delegated.get('perception_id') or ''}",
        f"- delegation_id: {delegated.get('delegation_id') or ''}",
        f"- executor: {executor}",
        f"- consent_id: {delegated.get('consent_id') or ''}",
        f"- executor_report_ref: {delegated.get('executor_report_ref') or ''}",
        f"- executor_run_ref: {delegated.get('executor_run_ref') or ''}",
        f"- query: {_shorten(str(delegated.get('query') or ''), 160)}",
        f"- summary: {_shorten(str(delegated.get('summary') or ''), 220)}",
        f"- confidence: {delegated.get('confidence') or ''}",
    ]
    findings = _list(delegated.get("findings"))
    sources = _list(delegated.get("sources"))
    limitations = _list(delegated.get("limitations"))
    lines.append(f"- findings: {len(findings)}")
    lines.append(f"- sources: {len(sources)}")
    lines.append(f"- limitations: {len(limitations)}")
    if findings:
        lines.append("")
        lines.append("Findings:")
        for item in findings[:8]:
            mapping = _mapping(item)
            text = _shorten(str(mapping.get("text") or ""), 180)
            confidence = mapping.get("confidence")
            refs = ", ".join(str(ref) for ref in _list(mapping.get("source_refs"))[:4])
            limitations = ", ".join(
                _shorten(str(item), 80)
                for item in _list(mapping.get("limitations"))[:2]
                if str(item)
            )
            suffix_parts = []
            if confidence is not None:
                suffix_parts.append(f"confidence={confidence}")
            if refs:
                suffix_parts.append(f"source_refs={refs}")
            if limitations:
                suffix_parts.append(f"limitations={limitations}")
            suffix = f" [{'; '.join(suffix_parts)}]" if suffix_parts else ""
            lines.append(f"- {text}{suffix}")
    if sources:
        lines.append("")
        lines.append(f"{executor_label}-reported source refs:")
        for item in sources[:8]:
            mapping = _mapping(item)
            source_id = str(mapping.get("source_id") or "")
            source_type = str(mapping.get("source_type") or "")
            title = _shorten(str(mapping.get("title") or ""), 90)
            uri = _shorten(str(mapping.get("uri") or mapping.get("url") or ""), 150)
            observed_by = str(mapping.get("observed_by") or delegated.get("executor_id") or "")
            verification = str(mapping.get("verification_status") or "")
            accessed_at = str(mapping.get("accessed_at") or "")
            parts = [part for part in [source_id, source_type, title, uri] if part]
            tail = [
                part
                for part in [
                    f"observed_by={observed_by}" if observed_by else "",
                    f"verification_status={verification}" if verification else "",
                    f"accessed_at={accessed_at}" if accessed_at else "",
                ]
                if part
            ]
            line = f"- {' | '.join(parts)}"
            if tail:
                line += f" [{' ; '.join(tail)}]"
            lines.append(line)
    if limitations:
        lines.append("")
        lines.append("Limitations:")
        for item in limitations[:6]:
            lines.append(f"- {_shorten(str(item), 180)}")
    return lines


def _line_range(payload: dict[str, Any]) -> str:
    start = payload.get("line_start")
    end = payload.get("line_end")
    if start and end and start != end:
        return f":{start}-{end}"
    if start:
        return f":{start}"
    line = payload.get("line")
    return f":{line}" if line else ""


def _active_decision_frame_from_general_state(general_state: Any) -> dict[str, Any]:
    metadata = getattr(general_state, "metadata", None)
    if not isinstance(metadata, dict):
        return {}
    frame = metadata.get("active_decision_frame")
    return dict(frame) if isinstance(frame, dict) else {}


def _context_current_intent(frame: dict[str, Any]) -> dict[str, Any]:
    raw_input = frame.get("input") if isinstance(frame.get("input"), dict) else {}
    text = str(raw_input.get("text") or "").strip()
    return {
        "text": text,
        "source": str(frame.get("source") or "context_debug"),
        "kind": "context_debug",
        "run_intent_mode": str(frame.get("run_intent_mode") or ""),
        "display_language": str(frame.get("display_language") or ""),
        "decision_id": str(frame.get("decision_id") or ""),
        "run_id": str(frame.get("run_id") or ""),
    }


def _world_state_from_workspace_payload(payload: dict[str, Any]) -> WorldState:
    world_payload = payload.get("world_state")
    if not isinstance(world_payload, dict):
        raise ValueError("Workspace state must contain a world_state object.")
    return WorldState(
        id=str(world_payload.get("id") or "worldstate.local"),
        schema_version=str(world_payload.get("schema_version", "0.1")),
        status=str(world_payload.get("status", "current")),
        entities=_mapping(world_payload.get("entities")),
        relations=_list_of_mappings(world_payload.get("relations")),
        goals=_list_of_mappings(world_payload.get("goals")),
        constraints=_list_of_mappings(world_payload.get("constraints")),
        signals=_list_of_mappings(world_payload.get("signals")),
        risks=_list_of_mappings(world_payload.get("risks")),
        active_intents=_list_of_mappings(world_payload.get("active_intents")),
        recent_outcomes=_list_of_mappings(world_payload.get("recent_outcomes")),
        resources=_mapping(world_payload.get("resources")),
        confidence=_mapping(world_payload.get("confidence")),
        provenance=_mapping(world_payload.get("provenance")),
        domain_state=_mapping(world_payload.get("domain_state")),
    )


def _context_selected_summary(frame: dict[str, Any]) -> str:
    selected = frame.get("selected") if isinstance(frame.get("selected"), dict) else {}
    label = str(selected.get("label") or "").strip()
    title = str(selected.get("title") or selected.get("recommended_action") or "").strip()
    candidate_id = str(selected.get("candidate_id") or frame.get("selected_candidate_id") or "").strip()
    parts = [part for part in [label, _shorten(title, 80), candidate_id] if part]
    return " | ".join(parts)


def _executor_context_summary(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("executor") or ""),
        str(payload.get("status") or ""),
        str(payload.get("permission_mode") or ""),
    ]
    return " ".join(part for part in parts if part).strip()


def _executor_capabilities_summary(payload: dict[str, Any]) -> str:
    executor_id = str(payload.get("executor_id") or "").strip()
    source = str(payload.get("source") or "").strip()
    capabilities = _list(payload.get("capability_ids"))
    parts = [executor_id, source]
    if capabilities:
        parts.append(f"capabilities={len(capabilities)}")
    return " ".join(part for part in parts if part).strip() or "none"


def _session_context_summary(payload: dict[str, Any]) -> str:
    parts = []
    session_id = str(payload.get("session_id") or "")
    if session_id:
        parts.append(session_id)
    decisions = payload.get("decision_count")
    if decisions is not None:
        parts.append(f"decisions={decisions}")
    return " ".join(part for part in parts if part).strip()


def _summary_context_summary(payload: dict[str, Any]) -> str:
    rolling = payload.get("rolling_summary")
    if not isinstance(rolling, dict):
        return "none"
    summary_type = str(rolling.get("summary_type") or "deterministic")
    updated = str(rolling.get("updated_at") or "")
    model = rolling.get("model") if isinstance(rolling.get("model"), dict) else {}
    model_id = str(model.get("model_id") or "")
    parts = [summary_type]
    if model_id:
        parts.append(model_id)
    if updated:
        parts.append(f"updated={updated}")
    return " ".join(parts)


def _workspace_context_summary(payload: dict[str, Any]) -> str:
    if payload.get("perception_id") or payload.get("source") == "workspace_perception":
        facts = _list(payload.get("facts"))
        files_read = _list(payload.get("files_read"))
        parts = [
            "workspace_perception",
            str(payload.get("perception_id") or ""),
            f"facts={len(facts)}",
            f"files={len(files_read)}",
        ]
        return " ".join(part for part in parts if part)
    parts = [
        f"memory={payload.get('memory_provider')}" if payload.get("memory_provider") is not None else "",
        f"compiler={payload.get('context_compiler')}" if payload.get("context_compiler") is not None else "",
        f"summary={payload.get('memory_summary_provider')}" if payload.get("memory_summary_provider") is not None else "",
        f"executor={payload.get('executor')}" if payload.get("executor") is not None else "",
    ]
    return " ".join(part for part in parts if part)


def _url_context_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "none"
    facts = _list(payload.get("facts"))
    documents = _list(payload.get("documents"))
    urls = _list(payload.get("urls"))
    parts = [
        "url_perception",
        str(payload.get("perception_id") or ""),
        f"docs={len(documents)}",
        f"facts={len(facts)}",
        f"urls={len(urls)}",
    ]
    return " ".join(part for part in parts if part)


def _delegated_context_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "none"
    findings = _list(payload.get("findings"))
    sources = _list(payload.get("sources"))
    parts = [
        "delegated_perception",
        str(payload.get("perception_id") or ""),
        f"executor={payload.get('executor_id')}" if payload.get("executor_id") else "",
        f"findings={len(findings)}",
        f"sources={len(sources)}",
        f"confidence={payload.get('confidence')}" if payload.get("confidence") else "",
    ]
    return " ".join(part for part in parts if part)


def _evidence_context_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "none"
    workspace = _mapping(payload.get("workspace"))
    url = _mapping(payload.get("url"))
    delegated = _mapping(payload.get("delegated"))
    parts = [
        f"confidence={payload.get('confidence') or 'none'}",
        f"workspace={workspace.get('source_count') or 0}" if workspace.get("present") else "",
        f"url={url.get('source_count') or 0}" if url.get("present") else "",
        f"delegated={delegated.get('source_count') or 0}" if delegated.get("present") else "",
        f"limitations={len(_list(payload.get('limitations')))}",
    ]
    return " ".join(part for part in parts if part) or "none"


def _executor_display_name(executor_id: str) -> str:
    normalized = str(executor_id or "").strip()
    aliases = {
        "hermes": "Hermes",
        "codex": "Codex",
        "claude_code": "Claude Code",
        "claude-code": "Claude Code",
        "openclaw": "OpenClaw",
    }
    return aliases.get(normalized.lower(), normalized or "Executor")


def _candidate_run_ids(session: Any, frame: dict[str, Any]) -> list[str]:
    session_payload = payload_value(session)
    candidates: list[str] = []
    for value in (
        frame.get("run_id"),
        session_payload.get("last_run_id") if isinstance(session_payload, dict) else None,
    ):
        text = str(value or "").strip()
        if text:
            candidates.append(text)
    if isinstance(session_payload, dict):
        run_ids = _list(session_payload.get("run_ids"))
        candidates.extend(str(run_id) for run_id in reversed(run_ids) if str(run_id or "").strip())
    seen: set[str] = set()
    result: list[str] = []
    for run_id in candidates:
        if run_id in seen:
            continue
        seen.add(run_id)
        result.append(run_id)
    return result


def _workspace_context_from_run(run: dict[str, Any]) -> dict[str, Any]:
    workspace = _mapping(run.get("workspace_context"))
    if workspace:
        return workspace
    compiled = _mapping(run.get("compiled_context"))
    for key in ("decision_context", "simulation_context", "reflection_context"):
        workspace = _mapping(_mapping(compiled.get(key)).get("workspace_context"))
        if workspace.get("source") == "workspace_perception" or workspace.get("perception_id"):
            return workspace
    return {}


def _url_context_from_run(run: dict[str, Any]) -> dict[str, Any]:
    url_context = _mapping(run.get("url_context"))
    if url_context:
        return url_context
    compiled = _mapping(run.get("compiled_context"))
    for key in ("decision_context", "simulation_context", "reflection_context"):
        url_context = _mapping(_mapping(compiled.get(key)).get("url_context"))
        if url_context.get("source") == "url_perception" or url_context.get("perception_id"):
            return url_context
    return {}


def _delegated_perception_context_from_run(run: dict[str, Any]) -> dict[str, Any]:
    delegated_context = _mapping(run.get("delegated_perception_context"))
    if delegated_context:
        return delegated_context
    compiled = _mapping(run.get("compiled_context"))
    for key in ("decision_context", "simulation_context", "reflection_context"):
        delegated_context = _mapping(
            _mapping(compiled.get(key)).get("delegated_perception_context")
        )
        if (
            delegated_context.get("source") == "delegated_perception"
            or delegated_context.get("perception_id")
        ):
            return delegated_context
    return {}


def _budget_summary(payload: dict[str, Any]) -> str:
    parts = []
    for key in (
        "tool_calls_used",
        "tool_calls_executed",
        "tool_calls_blocked",
        "normal_tool_calls_used",
        "rounds_used",
        "files_read",
        "files_read_count",
        "chars_used",
        "total_char_budget",
        "budget_pressure",
        "chars_read",
        "total_chars_read",
        "remaining_char_budget",
    ):
        if key in payload:
            parts.append(f"{key}={payload.get(key)}")
    return ", ".join(parts) if parts else _shorten(str(payload), 160)


def _shorten(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
