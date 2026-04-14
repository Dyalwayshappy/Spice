from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from spice.entry.spec import DomainSpec, DomainSpecValidationError
from spice.llm.core import (
    LLMClient,
    LLMModelConfig,
    LLMModelConfigOverride,
    LLMRouter,
    LLMTaskHook,
    ProviderRegistry,
)
from spice.llm.providers import (
    DeterministicLLMProvider,
    OpenRouterLLMProvider,
    SubprocessLLMProvider,
)
from spice.llm.services.model_override import resolve_llm_model_override
from spice.llm.services import AssistDraftService
from spice.llm.util import extract_first_json_object, strip_markdown_fences


ASSIST_ARTIFACTS_DIRNAME = "assist"
ASSIST_MAX_TRIES_DEFAULT = 3
ASSIST_SUMMARY_SCHEMA_VERSION = "spice.assist.summary.v1"


@dataclass(slots=True)
class AssistDraftContract:
    draft_spec: dict[str, Any]
    assumptions: list[str]
    warnings: list[str]
    missing_info: list[str]
    confidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_spec": dict(self.draft_spec),
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
            "missing_info": list(self.missing_info),
            "confidence": dict(self.confidence),
        }


@dataclass(slots=True)
class AssistDraftResult:
    raw_response: str
    parsed_payload: dict[str, Any] | None
    contract: AssistDraftContract | None
    spec: DomainSpec | None
    errors: list[str]
    attempt_count: int


@dataclass(slots=True)
class AssistSessionResult:
    accepted_spec: DomainSpec
    brief: str
    draft_result: AssistDraftResult
    assumptions: list[str]
    warnings: list[str]
    missing_info: list[str]
    confidence: dict[str, Any]
    action_bindings: list[dict[str, str]]
    model_backend: str
    review_decision: str


def capture_brief(
    *,
    brief_file: Path | None,
    use_stdin: bool,
    input_stream: TextIO,
    output_stream: TextIO,
) -> str:
    if brief_file is not None:
        return brief_file.read_text(encoding="utf-8").strip()

    if use_stdin:
        output_stream.write(
            "Provide assist brief via stdin. End with line END or EOF.\n"
        )
        return _read_multiline_until_end_or_eof(input_stream, output_stream)

    output_stream.write(
        "Describe your domain brief (end with END or EOF):\n"
        "- domain purpose\n"
        "- observations / signals\n"
        "- actions\n"
        "- outcomes\n"
        "- state fields\n"
    )
    return _read_multiline_until_end_or_eof(input_stream, output_stream)


def resolve_assist_model(
    *,
    model: str | None,
) -> tuple[AssistDraftService, str]:
    model_override = _resolve_assist_model_override(model)
    router = _build_assist_router()
    registry = _build_assist_registry()
    client = LLMClient(registry=registry, router=router)
    service = AssistDraftService(
        client=client,
        model_override=model_override,
    )
    return service, service.resolved_provider_id()


def run_assist_session(
    *,
    domain_name: str,
    brief: str,
    draft_service: AssistDraftService,
    model_backend: str,
    max_tries: int,
    input_stream: TextIO,
    output_stream: TextIO,
) -> AssistSessionResult:
    draft_result = _draft_with_retry(
        draft_service=draft_service,
        domain_name=domain_name,
        brief=brief,
        max_tries=max_tries,
        feedback_hint="",
    )

    while True:
        _print_review_summary(draft_result, output_stream=output_stream)
        choice = _prompt_choice(
            input_stream=input_stream,
            output_stream=output_stream,
            label="Choose action",
            choices=("accept", "edit", "retry", "cancel"),
            default="accept",
        )

        if choice == "cancel":
            raise RuntimeError("Assist initialization cancelled by user.")

        if choice == "retry":
            note = _prompt_freeform(
                input_stream=input_stream,
                output_stream=output_stream,
                label="Optional retry note",
            )
            feedback_hint = _join_non_empty([note.strip(), *draft_result.errors[-3:]])
            draft_result = _draft_with_retry(
                draft_service=draft_service,
                domain_name=domain_name,
                brief=brief,
                max_tries=max_tries,
                feedback_hint=feedback_hint,
            )
            continue

        if choice == "edit":
            edited_payload = _edit_draft_spec_payload(
                draft_result=draft_result,
                input_stream=input_stream,
                output_stream=output_stream,
            )
            draft_result = _validate_edited_draft(
                draft_spec_payload=edited_payload,
                prior_raw_response=draft_result.raw_response,
                prior_payload=draft_result.parsed_payload,
                prior_contract=draft_result.contract,
                prior_attempt_count=draft_result.attempt_count,
                prior_errors=draft_result.errors,
            )
            continue

        if draft_result.spec is None:
            output_stream.write("Cannot accept: draft is invalid. Choose edit/retry/cancel.\n")
            continue

        assumptions = list(draft_result.contract.assumptions) if draft_result.contract else []
        warnings = list(draft_result.contract.warnings) if draft_result.contract else []
        missing_info = list(draft_result.contract.missing_info) if draft_result.contract else []
        confidence = dict(draft_result.contract.confidence) if draft_result.contract else {}
        return AssistSessionResult(
            accepted_spec=draft_result.spec,
            brief=brief,
            draft_result=draft_result,
            assumptions=assumptions,
            warnings=warnings,
            missing_info=missing_info,
            confidence=confidence,
            action_bindings=_domain_action_bindings(draft_result.spec),
            model_backend=model_backend,
            review_decision="accepted",
        )


def write_assist_artifacts(
    *,
    artifacts_root: Path,
    session: AssistSessionResult,
) -> Path:
    assist_dir = artifacts_root / ASSIST_ARTIFACTS_DIRNAME
    assist_dir.mkdir(parents=True, exist_ok=True)

    (assist_dir / "brief.txt").write_text(session.brief, encoding="utf-8")
    (assist_dir / "llm_draft.raw.json").write_text(
        session.draft_result.raw_response,
        encoding="utf-8",
    )

    parsed_payload = session.draft_result.parsed_payload or {}
    (assist_dir / "llm_draft.parsed.json").write_text(
        json.dumps(parsed_payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    draft_spec = (
        dict(session.draft_result.contract.draft_spec)
        if session.draft_result.contract is not None
        else {}
    )
    (assist_dir / "draft_domain_spec.json").write_text(
        json.dumps(draft_spec, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (assist_dir / "accepted_domain_spec.json").write_text(
        json.dumps(session.accepted_spec.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if session.draft_result.errors:
        (assist_dir / "validation_errors.log").write_text(
            "\n".join(session.draft_result.errors) + "\n",
            encoding="utf-8",
        )

    summary_payload = {
        "schema_version": ASSIST_SUMMARY_SCHEMA_VERSION,
        "model_backend": session.model_backend,
        "review_decision": session.review_decision,
        "attempt_count": session.draft_result.attempt_count,
        "assumptions": list(session.assumptions),
        "warnings": list(session.warnings),
        "missing_info": list(session.missing_info),
        "confidence": dict(session.confidence),
        "action_bindings": [dict(item) for item in session.action_bindings],
    }
    summary_path = assist_dir / "assist_summary.json"
    summary_path.write_text(
        json.dumps(summary_payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary_path


def _build_assist_registry() -> ProviderRegistry:
    return (
        ProviderRegistry.empty()
        .register(DeterministicLLMProvider())
        .register(OpenRouterLLMProvider())
        .register(SubprocessLLMProvider())
    )


def _build_assist_router() -> LLMRouter:
    assist_default = LLMModelConfig(
        provider_id="deterministic",
        model_id="deterministic.v1",
        temperature=0.0,
        max_tokens=2500,
        timeout_sec=60.0,
        response_format_hint="json_object",
    )
    return LLMRouter(
        global_default=assist_default,
        hook_defaults={
            LLMTaskHook.ASSIST_DRAFT: assist_default,
        },
    )


def _resolve_assist_model_override(model: str | None) -> LLMModelConfigOverride | None:
    raw = model if model is not None else os.environ.get("SPICE_ASSIST_MODEL")
    return resolve_llm_model_override(
        raw,
        deterministic_model_id="deterministic.v1",
    )


def _draft_with_retry(
    *,
    draft_service: AssistDraftService,
    domain_name: str,
    brief: str,
    max_tries: int,
    feedback_hint: str,
) -> AssistDraftResult:
    attempts = max(1, int(max_tries))
    errors: list[str] = []
    last_raw = ""
    last_parsed: dict[str, Any] | None = None
    last_contract: AssistDraftContract | None = None

    for attempt in range(1, attempts + 1):
        feedback = feedback_hint.strip() if attempt == 1 else _join_non_empty(errors[-3:])
        try:
            raw = draft_service.draft(
                domain_name=domain_name,
                brief=brief,
                attempt=attempt,
                feedback=feedback,
            )
        except Exception as exc:
            errors.append(f"attempt {attempt}: model error: {exc}")
            continue

        last_raw = raw
        try:
            parsed_payload = _parse_assist_response(raw)
        except ValueError as exc:
            errors.append(f"attempt {attempt}: parse error: {exc}")
            continue
        last_parsed = parsed_payload

        try:
            contract = _validate_assist_contract(parsed_payload)
        except ValueError as exc:
            errors.append(f"attempt {attempt}: contract error: {exc}")
            continue
        last_contract = contract

        try:
            spec = DomainSpec.from_dict(contract.draft_spec)
        except DomainSpecValidationError as exc:
            errors.append(f"attempt {attempt}: domain spec validation error: {exc}")
            continue

        return AssistDraftResult(
            raw_response=raw,
            parsed_payload=parsed_payload,
            contract=contract,
            spec=spec,
            errors=errors,
            attempt_count=attempt,
        )

    return AssistDraftResult(
        raw_response=last_raw,
        parsed_payload=last_parsed,
        contract=last_contract,
        spec=None,
        errors=errors or ["assist drafting failed without any model response."],
        attempt_count=attempts,
    )


def _parse_assist_response(raw: str) -> dict[str, Any]:
    normalized = strip_markdown_fences(raw)
    candidate = extract_first_json_object(normalized)
    if candidate is None:
        raise ValueError("no JSON object start token found.")
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("assist response root must be a JSON object.")
    return payload


def _validate_assist_contract(payload: dict[str, Any]) -> AssistDraftContract:
    draft_spec = payload.get("draft_spec")
    if not isinstance(draft_spec, dict):
        raise ValueError("draft_spec is required and must be an object.")

    assumptions = _as_string_list(payload.get("assumptions", []), field_name="assumptions")
    warnings = _as_string_list(payload.get("warnings", []), field_name="warnings")
    missing_info = _as_string_list(payload.get("missing_info", []), field_name="missing_info")

    confidence_raw = payload.get("confidence", {})
    if not isinstance(confidence_raw, dict):
        raise ValueError("confidence must be an object.")
    return AssistDraftContract(
        draft_spec=dict(draft_spec),
        assumptions=assumptions,
        warnings=warnings,
        missing_info=missing_info,
        confidence=dict(confidence_raw),
    )


def _validate_edited_draft(
    *,
    draft_spec_payload: dict[str, Any],
    prior_raw_response: str,
    prior_payload: dict[str, Any] | None,
    prior_contract: AssistDraftContract | None,
    prior_attempt_count: int,
    prior_errors: list[str],
) -> AssistDraftResult:
    errors = list(prior_errors)
    try:
        spec = DomainSpec.from_dict(draft_spec_payload)
    except DomainSpecValidationError as exc:
        errors.append(f"edited draft validation error: {exc}")
        spec = None

    assumptions = list(prior_contract.assumptions) if prior_contract else []
    warnings = list(prior_contract.warnings) if prior_contract else []
    missing_info = list(prior_contract.missing_info) if prior_contract else []
    confidence = dict(prior_contract.confidence) if prior_contract else {}
    contract = AssistDraftContract(
        draft_spec=dict(draft_spec_payload),
        assumptions=assumptions,
        warnings=warnings,
        missing_info=missing_info,
        confidence=confidence,
    )
    return AssistDraftResult(
        raw_response=prior_raw_response,
        parsed_payload=prior_payload,
        contract=contract,
        spec=spec,
        errors=errors,
        attempt_count=prior_attempt_count,
    )


def _print_review_summary(draft: AssistDraftResult, *, output_stream: TextIO) -> None:
    output_stream.write("\nAssist Draft Review\n")
    if draft.contract is None:
        output_stream.write("- domain.id: n/a\n")
        output_stream.write("- observation_types: n/a\n")
        output_stream.write("- action_types: n/a\n")
        output_stream.write("- outcome_types: n/a\n")
        output_stream.write("- state fields: n/a\n")
        output_stream.write("- default_action: n/a\n")
        output_stream.write("- action -> executor mapping: unavailable\n")
    else:
        spec_payload = draft.contract.draft_spec
        output_stream.write(f"- domain.id: {_extract_domain_id(spec_payload) or 'n/a'}\n")
        output_stream.write(
            "- observation_types: {items}\n".format(
                items=", ".join(_extract_vocab_list(spec_payload, "observation_types")) or "n/a"
            )
        )
        output_stream.write(
            "- action_types: {items}\n".format(
                items=", ".join(_extract_vocab_list(spec_payload, "action_types")) or "n/a"
            )
        )
        output_stream.write(
            "- outcome_types: {items}\n".format(
                items=", ".join(_extract_vocab_list(spec_payload, "outcome_types")) or "n/a"
            )
        )

        state_fields = _extract_state_fields(spec_payload)
        if state_fields:
            output_stream.write("- state fields:\n")
            for field_name, field_type in state_fields:
                output_stream.write(f"  - {field_name} ({field_type})\n")
        else:
            output_stream.write("- state fields: n/a\n")

        output_stream.write(
            f"- default_action: {_extract_default_action(spec_payload) or 'n/a'}\n"
        )
        action_rows = _action_rows_from_draft_spec(spec_payload)
        if action_rows:
            output_stream.write("- action -> executor mapping:\n")
            for row in action_rows:
                output_stream.write(
                    "  - action_id={action_id}; executor.type={executor_type}; "
                    "executor.operation={executor_operation}; expected_outcome_type={expected_outcome_type}\n".format(
                        action_id=row["action_id"],
                        executor_type=row["executor_type"],
                        executor_operation=row["executor_operation"],
                        expected_outcome_type=row["expected_outcome_type"],
                    )
                )
        else:
            output_stream.write("- action -> executor mapping: n/a\n")

        output_stream.write(
            "- assumptions: {items}\n".format(
                items=", ".join(draft.contract.assumptions) or "none"
            )
        )
        output_stream.write(
            "- warnings: {items}\n".format(
                items=", ".join(draft.contract.warnings) or "none"
            )
        )
        output_stream.write(
            "- missing_info: {items}\n".format(
                items=", ".join(draft.contract.missing_info) or "none"
            )
        )

    output_stream.write(f"- validation: {'OK' if draft.spec is not None else 'INVALID'}\n")
    if draft.errors:
        output_stream.write("- recent errors:\n")
        for item in draft.errors[-3:]:
            output_stream.write(f"  - {item}\n")


def _edit_draft_spec_payload(
    *,
    draft_result: AssistDraftResult,
    input_stream: TextIO,
    output_stream: TextIO,
) -> dict[str, Any]:
    base_payload = (
        dict(draft_result.contract.draft_spec)
        if draft_result.contract is not None
        else {}
    )
    editor = (os.environ.get("EDITOR", "") or "").strip()
    if editor:
        try:
            return _edit_with_editor(payload=base_payload, editor=editor)
        except Exception as exc:
            output_stream.write(f"$EDITOR edit failed: {exc}\n")

    output_stream.write(
        "Inline edit mode. Paste full draft_spec JSON, then a line containing END.\n"
    )
    while True:
        raw_payload = _read_multiline_until_end_or_eof(input_stream, output_stream)
        if not raw_payload.strip():
            output_stream.write("No JSON provided. Paste a JSON object.\n")
            continue
        try:
            parsed = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            output_stream.write(f"Invalid JSON: {exc}\n")
            continue
        if not isinstance(parsed, dict):
            output_stream.write("Draft spec must be a JSON object.\n")
            continue
        return dict(parsed)


def _edit_with_editor(*, payload: dict[str, Any], editor: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(
        mode="w+",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
        tmp.flush()

    try:
        command = [*shlex.split(editor), str(tmp_path)]
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"editor exited with code {completed.returncode}")
        edited_text = tmp_path.read_text(encoding="utf-8")
        parsed = json.loads(edited_text)
        if not isinstance(parsed, dict):
            raise RuntimeError("edited draft must be a JSON object.")
        return dict(parsed)
    finally:
        tmp_path.unlink(missing_ok=True)


def _prompt_choice(
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    label: str,
    choices: tuple[str, ...],
    default: str,
) -> str:
    options = "/".join(choices)
    alias_map = _build_choice_alias_map(choices)
    while True:
        output_stream.write(f"{label} ({options}) [{default}]: ")
        output_stream.flush()
        raw = input_stream.readline()
        if raw == "":
            raise RuntimeError("Input ended during assist review.")
        token = raw.strip().lower()
        if not token:
            token = default
        elif token in alias_map:
            token = alias_map[token]
        if token in choices:
            return token
        output_stream.write(f"Invalid choice. Use one of: {', '.join(choices)}.\n")


def _prompt_freeform(
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    label: str,
) -> str:
    output_stream.write(f"{label}: ")
    output_stream.flush()
    raw = input_stream.readline()
    if raw == "":
        return ""
    return raw.rstrip("\n")


def _read_multiline_until_end_or_eof(input_stream: TextIO, output_stream: TextIO) -> str:
    lines: list[str] = []
    while True:
        output_stream.write("> ")
        output_stream.flush()
        raw = input_stream.readline()
        if raw == "":
            break
        line = raw.rstrip("\n")
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _domain_action_bindings(spec: DomainSpec) -> list[dict[str, str]]:
    return [
        {
            "action_id": action.id,
            "executor_type": action.executor.type,
            "executor_operation": action.executor.operation,
            "expected_outcome_type": action.expected_outcome_type,
        }
        for action in spec.actions
    ]


def _action_rows_from_draft_spec(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    actions = payload.get("actions")
    if not isinstance(actions, list):
        return rows
    for item in actions:
        if not isinstance(item, dict):
            continue
        executor = item.get("executor")
        executor_type = ""
        executor_operation = ""
        if isinstance(executor, dict):
            executor_type = str(executor.get("type", ""))
            executor_operation = str(executor.get("operation", ""))
        rows.append(
            {
                "action_id": str(item.get("id", "")),
                "executor_type": executor_type,
                "executor_operation": executor_operation,
                "expected_outcome_type": str(item.get("expected_outcome_type", "")),
            }
        )
    return rows


def _extract_domain_id(payload: dict[str, Any]) -> str:
    domain = payload.get("domain")
    if not isinstance(domain, dict):
        return ""
    value = domain.get("id")
    return value.strip() if isinstance(value, str) else ""


def _extract_vocab_list(payload: dict[str, Any], key: str) -> list[str]:
    vocabulary = payload.get("vocabulary")
    if not isinstance(vocabulary, dict):
        return []
    values = vocabulary.get(key)
    if not isinstance(values, list):
        return []
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def _extract_state_fields(payload: dict[str, Any]) -> list[tuple[str, str]]:
    state = payload.get("state")
    if not isinstance(state, dict):
        return []
    fields = state.get("fields")
    if not isinstance(fields, list):
        return []
    rows: list[tuple[str, str]] = []
    for item in fields:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        field_type = str(item.get("type", "string")).strip() or "string"
        if not name:
            continue
        rows.append((name, field_type))
    return rows


def _extract_default_action(payload: dict[str, Any]) -> str:
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        return ""
    value = decision.get("default_action")
    return value.strip() if isinstance(value, str) else ""


def _build_choice_alias_map(choices: tuple[str, ...]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    counts: dict[str, int] = {}
    for choice in choices:
        if not choice:
            continue
        alias = choice[0]
        counts[alias] = counts.get(alias, 0) + 1
        alias_map[alias] = choice
    return {alias: value for alias, value in alias_map.items() if counts.get(alias, 0) == 1}


def _as_string_list(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings.")
    items: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_name}[{idx}] must be a string.")
        items.append(item)
    return items


def _join_non_empty(parts: list[str]) -> str:
    return "\n".join(part for part in parts if part)
