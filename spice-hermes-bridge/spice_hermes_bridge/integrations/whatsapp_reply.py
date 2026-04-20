from __future__ import annotations

from typing import Any

from examples.decision_hub_demo.confirmation import (
    ConfirmationResolution,
    ControlLoopResult,
    format_confirmation_for_whatsapp,
)


def format_control_result_for_whatsapp(control: ControlLoopResult | dict[str, Any]) -> str:
    payload = _payload(control)
    confirmation = payload.get("confirmation_request")
    if confirmation:
        return format_confirmation_for_whatsapp(confirmation)

    ask_user = payload.get("ask_user")
    if ask_user:
        reasons = _bullet_list(ask_user.get("reason_summary", []))
        return (
            "我需要你补充信息：\n"
            f"{ask_user.get('message') or '当前信息不足，无法安全执行。'}\n\n"
            "原因：\n"
            f"{reasons or '- 信息不足'}"
        )

    execution = payload.get("execution")
    if execution:
        return format_execution_result_for_whatsapp(execution)

    if payload.get("status") == "no_execution":
        recommendation = payload.get("recommendation", {})
        return (
            "Spice 已给出不执行建议：\n"
            f"{recommendation.get('human_summary') or recommendation.get('selected_action')}\n\n"
            f"原因：{payload.get('reason') or '该动作在当前 demo 中不触发执行。'}"
        )

    return f"Spice control result: {payload.get('status', 'unknown')}"


def format_confirmation_resolution_for_whatsapp(
    resolution: ConfirmationResolution | dict[str, Any],
) -> str:
    payload = _payload(resolution)
    status = payload.get("status")
    if status == "executed":
        return format_execution_result_for_whatsapp(payload.get("execution", {}))
    if status == "rejected":
        request = payload.get("confirmation_request") or {}
        return (
            "已取消执行：\n"
            f"{request.get('selected_action') or 'selected action'}\n\n"
            "不会创建 execution request，也不会伪装成执行结果。"
        )
    if status == "details":
        details = payload.get("details") or {}
        reasons = _bullet_list(details.get("reason_summary", []))
        score = details.get("score_breakdown") or {}
        score_lines = _score_lines(score)
        return (
            "决策详情：\n"
            f"- decision_id: {details.get('decision_id')}\n"
            f"- selected_action: {details.get('selected_action')}\n"
            f"- trace_ref: {details.get('trace_ref')}\n\n"
            "原因：\n"
            f"{reasons or '- 见 trace'}\n\n"
            "核心评分：\n"
            f"{score_lines or '- 暂无评分'}"
        )
    if status == "missing_confirmation":
        return "找不到这个 confirmation_id，无法继续执行。"
    if status == "already_resolved":
        return "这个确认请求已经处理过，不会重复执行。"
    return f"confirmation result: {status or 'unknown'}"


def format_execution_result_for_whatsapp(execution: dict[str, Any]) -> str:
    outcome = execution.get("outcome") or {}
    request = execution.get("execution_request") or {}
    if not outcome:
        return "当前没有执行结果。"

    followup = "需要" if outcome.get("followup_needed") else "不需要"
    blocking = outcome.get("blocking_issue")
    blocking_line = f"\n- 阻塞问题：{blocking}" if blocking else ""
    return (
        "已完成执行：\n"
        f"{request.get('executor') or 'executor'} / {request.get('action_type') or 'action'}\n\n"
        "结果：\n"
        f"- 状态：{outcome.get('status')}\n"
        f"- 风险变化：{outcome.get('risk_change')}\n"
        f"- 后续：{followup}\n"
        f"- 摘要：{outcome.get('summary') or '无摘要'}"
        f"{blocking_line}"
    )


def _payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_payload"):
        return value.to_payload()
    if isinstance(value, dict):
        return value
    return {}


def _bullet_list(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    return "\n".join(f"- {item}" for item in items)


def _score_lines(score: Any) -> str:
    if not isinstance(score, dict):
        return ""
    lines = []
    for key in sorted(score):
        value = score[key]
        if isinstance(value, int | float):
            lines.append(f"- {key}: {value:.3f}")
        else:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)
