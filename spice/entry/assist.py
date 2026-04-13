from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from spice.entry.spec import SCHEMA_VERSION_V1, DomainSpec, DomainSpecValidationError
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
    OpenAPICompatibleLLMProvider,
    SubprocessLLMProvider,
)
from spice.llm.services import AssistDraftService
from spice.llm.util import extract_first_json_object, strip_markdown_fences


ASSIST_ARTIFACTS_DIRNAME = "assist"
ASSIST_MAX_TRIES_DEFAULT = 3
ASSIST_SUMMARY_SCHEMA_VERSION = "spice.assist.summary.v1"
ASSIST_PROVIDER_IDS = ("deterministic", "subprocess", "openapi_compatible")
ASSIST_MODEL_ENV = "SPICE_ASSIST_MODEL"


@dataclass(slots=True, frozen=True)
class AssistModelSelection:
    provider_id: str
    model_id: str
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)


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
    provider: str | None = None,
    model: str | None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> tuple[AssistDraftService, str]:
    selection = resolve_assist_model_selection(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    model_override = _selection_to_model_override(selection)
    router = _build_assist_router()
    registry = _build_assist_registry()
    client = LLMClient(registry=registry, router=router)
    service = AssistDraftService(
        client=client,
        model_override=model_override,
    )
    return service, selection.provider_id


def resolve_assist_model_selection(
    *,
    provider: str | None = None,
    model: str | None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> AssistModelSelection:
    provider_token = _normalize_token(provider, lower=True)
    model_token = _normalize_token(model if model is not None else os.environ.get(ASSIST_MODEL_ENV))
    base_url_token = _normalize_token(base_url)
    api_key_token = _normalize_token(api_key)

    if provider_token is None:
        if base_url_token is not None or api_key_token is not None:
            raise ValueError(
                "Relay-specific assist options require --assist-provider openapi_compatible."
            )
        if model_token is None or model_token.lower() == "deterministic":
            return AssistModelSelection(
                provider_id="deterministic",
                model_id="deterministic.v1",
            )
        return AssistModelSelection(
            provider_id="subprocess",
            model_id=model_token,
        )

    if provider_token not in ASSIST_PROVIDER_IDS:
        supported = ", ".join(ASSIST_PROVIDER_IDS)
        raise ValueError(
            f"Unsupported assist provider {provider_token!r}. Expected one of: {supported}."
        )

    if provider_token == "deterministic":
        if base_url_token is not None or api_key_token is not None:
            raise ValueError(
                "deterministic assist provider does not accept --assist-base-url or --assist-api-key."
            )
        if model_token is None or model_token.lower() == "deterministic":
            return AssistModelSelection(
                provider_id="deterministic",
                model_id="deterministic.v1",
            )
        raise ValueError(
            "deterministic assist provider only accepts --assist-model deterministic."
        )

    if provider_token == "subprocess":
        if base_url_token is not None or api_key_token is not None:
            raise ValueError(
                "subprocess assist provider does not accept --assist-base-url or --assist-api-key."
            )
        if model_token is None:
            raise ValueError("subprocess assist provider requires --assist-model.")
        if model_token.lower() == "deterministic":
            raise ValueError(
                "subprocess assist provider requires a command, not --assist-model deterministic."
            )
        return AssistModelSelection(
            provider_id="subprocess",
            model_id=model_token,
        )

    missing: list[str] = []
    if model_token is None:
        missing.append("--assist-model")
    if base_url_token is None:
        missing.append("--assist-base-url")
    if api_key_token is None:
        missing.append("--assist-api-key")
    if missing:
        raise ValueError(
            "openapi_compatible assist provider requires "
            + ", ".join(missing)
            + "."
        )
    return AssistModelSelection(
        provider_id="openapi_compatible",
        model_id=model_token,
        base_url=base_url_token,
        api_key=api_key_token,
    )


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
        .register(OpenAPICompatibleLLMProvider())
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


def _selection_to_model_override(
    selection: AssistModelSelection,
) -> LLMModelConfigOverride | None:
    if (
        selection.provider_id == "deterministic"
        and selection.model_id == "deterministic.v1"
        and selection.base_url is None
        and selection.api_key is None
    ):
        return None
    return LLMModelConfigOverride(
        provider_id=selection.provider_id,
        model_id=selection.model_id,
        base_url=selection.base_url,
        api_key=selection.api_key,
    )


def _normalize_token(value: str | None, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    token = value.strip()
    if not token:
        return None
    if lower:
        return token.lower()
    return token


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
    normalized_draft_spec = _normalize_assist_draft_spec(draft_spec)

    assumptions = _as_string_list(payload.get("assumptions", []), field_name="assumptions")
    warnings = _as_string_list(payload.get("warnings", []), field_name="warnings")
    missing_info = _as_string_list(payload.get("missing_info", []), field_name="missing_info")

    confidence_raw = payload.get("confidence", {})
    if not isinstance(confidence_raw, dict):
        raise ValueError("confidence must be an object.")
    return AssistDraftContract(
        draft_spec=normalized_draft_spec,
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
    normalized_payload = _normalize_assist_draft_spec(draft_spec_payload)
    try:
        spec = DomainSpec.from_dict(normalized_payload)
    except DomainSpecValidationError as exc:
        errors.append(f"edited draft validation error: {exc}")
        spec = None

    assumptions = list(prior_contract.assumptions) if prior_contract else []
    warnings = list(prior_contract.warnings) if prior_contract else []
    missing_info = list(prior_contract.missing_info) if prior_contract else []
    confidence = dict(prior_contract.confidence) if prior_contract else {}
    contract = AssistDraftContract(
        draft_spec=normalized_payload,
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


def _normalize_assist_draft_spec(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    domain_id = _normalize_domain_id(_extract_domain_id(normalized) or "assist_domain")

    normalized["schema_version"] = _normalize_schema_version(normalized.get("schema_version"))

    domain_payload = normalized.get("domain")
    if isinstance(domain_payload, dict):
        domain_copy = dict(domain_payload)
        domain_copy["id"] = domain_id
        normalized["domain"] = domain_copy

    normalized["state"] = _normalize_state_payload(
        normalized.get("state"),
        domain_id=domain_id,
    )
    normalized["actions"] = _normalize_actions_payload(
        normalized.get("actions"),
        domain_id=domain_id,
        vocabulary=normalized.get("vocabulary"),
    )
    normalized["decision"] = _normalize_decision_payload(
        normalized.get("decision"),
        actions=normalized["actions"],
    )
    normalized["demo"] = _normalize_demo_payload(
        normalized.get("demo"),
        domain_id=domain_id,
    )
    normalized["vocabulary"] = _normalize_vocabulary_payload(
        normalized.get("vocabulary"),
        actions=normalized["actions"],
        demo=normalized["demo"],
    )
    return normalized


def _normalize_schema_version(value: Any) -> str:
    token = str(value or "").strip().lower().replace(" ", "")
    if token in {
        "",
        SCHEMA_VERSION_V1.lower(),
        "spice.domainspec.v1",
        "spice.domainspec.v1",
    }:
        return SCHEMA_VERSION_V1
    return str(value)


def _normalize_domain_id(value: str) -> str:
    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
    filtered = "".join(ch if (ch.isalnum() or ch in "._") else "_" for ch in cleaned)
    collapsed = filtered.strip("._")
    if not collapsed:
        return "assist_domain"
    parts = [part for part in collapsed.split(".") if part]
    normalized_parts: list[str] = []
    for part in parts:
        segment = part
        if not segment[0].isalpha():
            segment = f"a_{segment}"
        normalized_parts.append(segment)
    return ".".join(normalized_parts) or "assist_domain"


def _normalize_state_payload(value: Any, *, domain_id: str) -> dict[str, Any]:
    payload = dict(value) if isinstance(value, dict) else {}
    entity_id_raw = payload.get("entity_id")
    entity_id = (
        _normalize_domain_id(str(entity_id_raw))
        if isinstance(entity_id_raw, str) and entity_id_raw.strip()
        else f"{domain_id}.current"
    )
    return {
        "entity_id": entity_id,
        "fields": _normalize_state_fields(payload.get("fields")),
    }


def _normalize_state_fields(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = []
        for key, item_value in value.items():
            if isinstance(item_value, dict):
                item_payload = dict(item_value)
            else:
                item_payload = {"type": _infer_field_type(item_value), "default": item_value}
            item_payload.setdefault("name", str(key))
            items.append(item_payload)
    else:
        items = []

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        raw_name = item.get("name") or item.get("id") or item.get("field") or f"field_{index + 1}"
        name = _normalize_field_name(str(raw_name))
        if not name:
            continue
        field_payload: dict[str, Any] = {
            "name": name,
            "type": _normalize_field_type(item.get("type")),
        }
        if "default" in item:
            field_payload["default"] = item["default"]
        description = item.get("description")
        if isinstance(description, str) and description.strip():
            field_payload["description"] = description.strip()
        normalized.append(field_payload)

    if normalized:
        return _dedupe_named_objects(normalized, key="name")
    return [{"name": "status", "type": "string", "default": "unknown"}]


def _normalize_actions_payload(value: Any, *, domain_id: str, vocabulary: Any) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    vocabulary_action_types: list[str] = []
    if isinstance(vocabulary, dict):
        raw_action_types = vocabulary.get("action_types")
        if isinstance(raw_action_types, list):
            vocabulary_action_types = [str(item) for item in raw_action_types if isinstance(item, str)]

    vocabulary_outcome_types: list[str] = []
    if isinstance(vocabulary, dict):
        raw_outcome_types = vocabulary.get("outcome_types")
        if isinstance(raw_outcome_types, list):
            vocabulary_outcome_types = [str(item) for item in raw_outcome_types if isinstance(item, str)]

    fallback_outcome = (
        _normalize_domain_id(vocabulary_outcome_types[0])
        if vocabulary_outcome_types
        else f"{domain_id}.transition"
    )

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        raw_action_id = (
            item.get("id")
            or item.get("type")
            or (vocabulary_action_types[index] if index < len(vocabulary_action_types) else "")
            or f"{domain_id}.action_{index + 1}"
        )
        action_id = _normalize_domain_id(str(raw_action_id))
        normalized.append(
            {
                "id": action_id,
                "description": str(item.get("description", "")).strip(),
                "executor": _normalize_action_executor(item.get("executor"), action_id=action_id),
                "expected_outcome_type": _normalize_domain_id(
                    str(item.get("expected_outcome_type") or fallback_outcome)
                ),
            }
        )

    if normalized:
        return _dedupe_named_objects(normalized, key="id")
    fallback_action_id = f"{domain_id}.monitor"
    return [
        {
            "id": fallback_action_id,
            "description": "Observe current state.",
            "executor": {
                "type": "mock",
                "operation": fallback_action_id,
            },
            "expected_outcome_type": fallback_outcome,
        }
    ]


def _normalize_action_executor(value: Any, *, action_id: str) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = dict(value)
        executor_type = str(payload.get("type", "")).strip().lower()
        if executor_type not in {"mock", "cli", "sdep"}:
            executor_type = "mock"
        operation = str(payload.get("operation", "")).strip() or action_id
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        return {
            "type": executor_type,
            "operation": operation,
            "parameters": dict(parameters),
        }
    return {
        "type": "mock",
        "operation": action_id,
    }


def _normalize_decision_payload(value: Any, *, actions: list[dict[str, Any]]) -> dict[str, Any]:
    payload = dict(value) if isinstance(value, dict) else {}
    default_action = payload.get("default_action")
    normalized_default = _normalize_domain_id(str(default_action)) if isinstance(default_action, str) else ""
    action_ids = [str(item.get("id", "")) for item in actions if isinstance(item, dict)]
    if normalized_default not in action_ids and action_ids:
        normalized_default = action_ids[0]
    return {"default_action": normalized_default}


def _normalize_demo_payload(value: Any, *, domain_id: str) -> dict[str, Any]:
    payload = dict(value) if isinstance(value, dict) else {}
    observations = payload.get("observations")
    items = observations if isinstance(observations, list) else []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        obs_type = _normalize_domain_id(
            str(item.get("type") or f"{domain_id}.observation_{index + 1}")
        )
        source = str(item.get("source", "")).strip() or f"{domain_id}.demo"
        attributes = item.get("attributes")
        if isinstance(attributes, dict):
            attrs = dict(attributes)
        else:
            attrs = {
                key: val
                for key, val in item.items()
                if key not in {"type", "source", "attributes", "metadata"}
            }
        metadata = item.get("metadata")
        metadata_payload = dict(metadata) if isinstance(metadata, dict) else {}
        normalized.append(
            {
                "type": obs_type,
                "source": source,
                "attributes": attrs,
                "metadata": metadata_payload,
            }
        )
    if normalized:
        return {"observations": normalized}
    return {
        "observations": [
            {
                "type": f"{domain_id}.observation",
                "source": f"{domain_id}.demo",
                "attributes": {},
            }
        ]
    }


def _normalize_vocabulary_payload(value: Any, *, actions: list[dict[str, Any]], demo: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value) if isinstance(value, dict) else {}
    observation_types = _dedupe_strings(
        [
            _normalize_domain_id(str(item.get("type", "")))
            for item in demo.get("observations", [])
            if isinstance(item, dict) and str(item.get("type", "")).strip()
        ]
    )
    action_types = _dedupe_strings(
        [
            _normalize_domain_id(str(item.get("id", "")))
            for item in actions
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        ]
    )
    outcome_types = _dedupe_strings(
        [
            _normalize_domain_id(str(item.get("expected_outcome_type", "")))
            for item in actions
            if isinstance(item, dict) and str(item.get("expected_outcome_type", "")).strip()
        ]
    )

    fallback_observations = payload.get("observation_types")
    if not observation_types and isinstance(fallback_observations, list):
        observation_types = _dedupe_strings(
            [_normalize_domain_id(str(item)) for item in fallback_observations if isinstance(item, str)]
        )
    return {
        "observation_types": observation_types,
        "action_types": action_types,
        "outcome_types": outcome_types,
    }


def _normalize_field_name(value: str) -> str:
    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
    filtered = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in cleaned)
    filtered = filtered.strip("_")
    if not filtered:
        return ""
    if not filtered[0].isalpha():
        filtered = f"f_{filtered}"
    return filtered


def _normalize_field_type(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"string", "number", "integer", "boolean", "object", "array"}:
        return token
    if token in {"float", "double", "decimal"}:
        return "number"
    if token in {"int", "long"}:
        return "integer"
    if token in {"bool"}:
        return "boolean"
    if token in {"dict", "map"}:
        return "object"
    if token in {"list", "tuple", "set"}:
        return "array"
    if token in {"timestamp", "datetime", "date", "time"}:
        return "string"
    return "string"


def _infer_field_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "string"


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _dedupe_named_objects(values: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        token = str(value.get(key, ""))
        if not token or token in seen:
            continue
        seen.add(token)
        output.append(value)
    return output
