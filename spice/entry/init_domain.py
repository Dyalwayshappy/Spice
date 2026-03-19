from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from spice.entry.scaffold import write_scaffold
from spice.entry.spec import DomainSpec, DomainSpecValidationError, load_domain_spec


INIT_REPORT_SCHEMA_VERSION = "spice.init.report.v1"
_ALLOWED_EXECUTOR_TYPES = ("mock", "cli", "sdep")
_ALLOWED_FIELD_TYPES = ("string", "number", "integer", "boolean", "object", "array")
_DOMAIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_FIELD_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}
_MISSING = object()


@dataclass(slots=True)
class InitDomainReport:
    output_dir: Path
    domain_id: str
    domain_spec_path: Path
    scaffold_files: list[str]
    interactive: bool
    from_spec_path: Path | None
    demo_ran: bool
    demo_command: list[str]
    demo_exit_code: int | None
    stdout_log_path: Path
    stderr_log_path: Path
    last_cycle: dict[str, Any] | None
    action_bindings: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": INIT_REPORT_SCHEMA_VERSION,
            "domain_id": self.domain_id,
            "output_dir": str(self.output_dir),
            "domain_spec_path": str(self.domain_spec_path),
            "scaffold_files": list(self.scaffold_files),
            "interactive": self.interactive,
            "from_spec_path": str(self.from_spec_path) if self.from_spec_path else None,
            "demo_ran": self.demo_ran,
            "demo_command": list(self.demo_command),
            "demo_exit_code": self.demo_exit_code,
            "stdout_log_path": str(self.stdout_log_path),
            "stderr_log_path": str(self.stderr_log_path),
            "last_cycle": dict(self.last_cycle) if isinstance(self.last_cycle, dict) else None,
            "action_bindings": [dict(item) for item in self.action_bindings],
        }


def run_init_domain(
    *,
    name: str,
    output_dir: str | Path,
    force: bool = False,
    no_run: bool = False,
    with_llm: bool = False,
    from_spec: str | Path | None = None,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> InitDomainReport:
    active_input = input_stream or sys.stdin
    active_output = output_stream or sys.stdout
    from_spec_path = Path(from_spec) if from_spec is not None else None

    if from_spec_path is not None:
        spec = load_domain_spec(from_spec_path)
        interactive = False
    else:
        spec = build_domain_spec_interactive(
            name=name,
            input_stream=active_input,
            output_stream=active_output,
        )
        interactive = True

    return run_init_domain_from_spec(
        spec=spec,
        output_dir=output_dir,
        force=force,
        no_run=no_run,
        with_llm=with_llm,
        interactive=interactive,
        from_spec_path=from_spec_path,
    )


def run_init_domain_from_spec(
    *,
    spec: DomainSpec,
    output_dir: str | Path,
    force: bool = False,
    no_run: bool = False,
    with_llm: bool = False,
    interactive: bool = False,
    from_spec_path: Path | None = None,
) -> InitDomainReport:
    target_output = Path(output_dir)

    _prepare_output_dir(target_output, force=force)
    written_paths = write_scaffold(
        spec,
        target_output,
        overwrite=False,
        with_llm=with_llm,
    )
    scaffold_files = sorted(str(path.relative_to(target_output)) for path in written_paths)

    artifacts_dir = target_output / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    stdout_log_path = artifacts_dir / "run_demo.stdout.log"
    stderr_log_path = artifacts_dir / "run_demo.stderr.log"
    demo_command = [sys.executable, "run_demo.py"]

    demo_exit_code: int | None
    last_cycle: dict[str, Any] | None
    if no_run:
        demo_exit_code = None
        last_cycle = None
        stdout_log_path.write_text("demo skipped (--no-run)\n", encoding="utf-8")
        stderr_log_path.write_text("", encoding="utf-8")
    else:
        completed = _run_generated_demo(target_output, command=demo_command)
        demo_exit_code = int(completed.returncode)
        stdout_log_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_log_path.write_text(completed.stderr or "", encoding="utf-8")
        last_cycle = _extract_last_cycle(completed.stdout or "")
        if completed.returncode != 0:
            raise RuntimeError(
                "Generated init demo failed with exit code "
                f"{completed.returncode}. See logs under {artifacts_dir}."
            )

    report = InitDomainReport(
        output_dir=target_output,
        domain_id=spec.domain.id,
        domain_spec_path=target_output / "domain_spec.json",
        scaffold_files=scaffold_files,
        interactive=interactive,
        from_spec_path=from_spec_path,
        demo_ran=not no_run,
        demo_command=demo_command,
        demo_exit_code=demo_exit_code,
        stdout_log_path=stdout_log_path,
        stderr_log_path=stderr_log_path,
        last_cycle=last_cycle,
        action_bindings=_action_bindings(spec),
    )

    summary_path = artifacts_dir / "init_summary.json"
    summary_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def build_domain_spec_interactive(
    *,
    name: str,
    input_stream: TextIO,
    output_stream: TextIO,
) -> DomainSpec:
    output_stream.write("Spice Domain Init\n")
    output_stream.write("This wizard builds a minimal runnable DomainSpec v1 scaffold.\n\n")

    default_domain_id = _derive_domain_id_from_name(name)
    domain_id = _prompt_domain_id(
        input_stream,
        output_stream,
        default=default_domain_id,
    )

    observation_types = _prompt_kind_list(
        input_stream,
        output_stream,
        label="Observation types",
        default=[f"{domain_id}.signal"],
    )
    action_types = _prompt_kind_list(
        input_stream,
        output_stream,
        label="Action types",
        default=[f"{domain_id}.monitor"],
    )
    outcome_types = _prompt_kind_list(
        input_stream,
        output_stream,
        label="Outcome types",
        default=[f"{domain_id}.transition"],
    )

    default_executor_type = _prompt_choice(
        input_stream,
        output_stream,
        label="Default executor.type for actions",
        choices=_ALLOWED_EXECUTOR_TYPES,
        default="mock",
    )

    output_stream.write("\nAction executor mapping (domain action id -> executor.operation)\n")
    actions: list[dict[str, Any]] = []
    for action_id in action_types:
        operation = _prompt_with_default(
            input_stream,
            output_stream,
            label=f"executor.operation for action {action_id}",
            default=action_id,
        )
        actions.append(
            {
                "id": action_id,
                "executor": {
                    "type": default_executor_type,
                    "operation": operation,
                    "parameters": {},
                },
                "expected_outcome_type": outcome_types[0],
            }
        )

    state_entity_id = _prompt_domain_id(
        input_stream,
        output_stream,
        default=f"{domain_id}.current",
        label="State entity id",
    )

    fields = _prompt_state_fields(
        input_stream,
        output_stream,
    )

    default_action = _prompt_choice(
        input_stream,
        output_stream,
        label="Default action",
        choices=tuple(action_types),
        default=action_types[0],
    )

    demo_observation_type = _prompt_choice(
        input_stream,
        output_stream,
        label="Demo observation type",
        choices=tuple(observation_types),
        default=observation_types[0],
    )
    demo_source = _prompt_with_default(
        input_stream,
        output_stream,
        label="Demo source",
        default=f"{domain_id}.demo",
    )
    extra_demo_attributes = _prompt_optional_json_object(
        input_stream,
        output_stream,
        label="Additional demo attributes JSON",
    )

    base_demo_attributes = _state_defaults_as_attributes(fields)
    base_demo_attributes.update(extra_demo_attributes)

    payload = {
        "schema_version": "spice.domain_spec.v1",
        "domain": {"id": domain_id},
        "vocabulary": {
            "observation_types": observation_types,
            "action_types": action_types,
            "outcome_types": outcome_types,
        },
        "state": {
            "entity_id": state_entity_id,
            "fields": fields,
        },
        "actions": actions,
        "decision": {"default_action": default_action},
        "demo": {
            "observations": [
                {
                    "type": demo_observation_type,
                    "source": demo_source,
                    "attributes": base_demo_attributes,
                }
            ]
        },
    }

    output_stream.write("\nSummary\n")
    output_stream.write(f"- domain.id: {domain_id}\n")
    output_stream.write(f"- observation_types: {', '.join(observation_types)}\n")
    output_stream.write(f"- action_types: {', '.join(action_types)}\n")
    output_stream.write(f"- outcome_types: {', '.join(outcome_types)}\n")
    output_stream.write(f"- state.entity_id: {state_entity_id}\n")
    output_stream.write(f"- state.fields: {len(fields)}\n")
    output_stream.write(f"- decision.default_action: {default_action}\n")
    for action in actions:
        output_stream.write(
            "- action mapping: {action_id} -> {operation} ({executor_type})\n".format(
                action_id=action["id"],
                operation=action["executor"]["operation"],
                executor_type=action["executor"]["type"],
            )
        )

    confirmed = _prompt_yes_no(
        input_stream,
        output_stream,
        label="Generate scaffold with this configuration?",
        default=True,
    )
    if not confirmed:
        raise RuntimeError("Initialization cancelled by user.")

    try:
        return DomainSpec.from_dict(payload)
    except DomainSpecValidationError as exc:
        raise RuntimeError(f"Built interactive DomainSpec was invalid: {exc}") from exc


def _prepare_output_dir(output_dir: Path, *, force: bool) -> None:
    if output_dir.exists():
        if not force:
            raise FileExistsError(
                f"Init output directory already exists: {output_dir}. Use --force to replace it."
            )
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def _run_generated_demo(
    output_dir: Path,
    *,
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[2])
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{package_root}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else package_root
    )
    return subprocess.run(
        command,
        cwd=output_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _extract_last_cycle(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        if not line.startswith("last_cycle="):
            continue
        raw = line.split("=", 1)[1].strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            return payload
        return None
    return None


def _action_bindings(spec: DomainSpec) -> list[dict[str, str]]:
    return [
        {
            "action_id": action.id,
            "executor_type": action.executor.type,
            "executor_operation": action.executor.operation,
            "expected_outcome_type": action.expected_outcome_type,
        }
        for action in spec.actions
    ]


def _derive_domain_id_from_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    normalized = normalized.strip("_")
    if not normalized:
        return "my_domain"
    if normalized[0].isdigit():
        normalized = f"domain_{normalized}"
    return normalized


def _prompt_with_default(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    label: str,
    default: str,
) -> str:
    while True:
        raw = _readline(input_stream, output_stream, f"{label} [{default}]: ")
        value = raw.strip()
        if not value:
            return default
        return value


def _prompt_domain_id(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    default: str,
    label: str = "Domain id",
) -> str:
    while True:
        value = _prompt_with_default(
            input_stream,
            output_stream,
            label=label,
            default=default,
        )
        if _DOMAIN_ID_PATTERN.fullmatch(value):
            return value
        output_stream.write("Invalid value. Use lowercase letters, digits, underscore, dot.\n")


def _prompt_kind_list(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    label: str,
    default: list[str],
) -> list[str]:
    default_raw = ",".join(default)
    while True:
        raw = _prompt_with_default(
            input_stream,
            output_stream,
            label=f"{label} (comma-separated)",
            default=default_raw,
        )
        items = [item.strip() for item in raw.split(",") if item.strip()]
        if not items:
            output_stream.write("At least one value is required.\n")
            continue
        if len(items) != len(dict.fromkeys(items)):
            output_stream.write("Duplicate values are not allowed.\n")
            continue
        invalid = [item for item in items if _DOMAIN_ID_PATTERN.fullmatch(item) is None]
        if invalid:
            output_stream.write(
                "Invalid ids: {invalid}. Use lowercase letters, digits, underscore, dot.\n".format(
                    invalid=", ".join(invalid)
                )
            )
            continue
        return items


def _prompt_choice(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    label: str,
    choices: tuple[str, ...],
    default: str,
) -> str:
    options = "/".join(choices)
    while True:
        raw = _prompt_with_default(
            input_stream,
            output_stream,
            label=f"{label} ({options})",
            default=default,
        )
        if raw in choices:
            return raw
        output_stream.write(f"Invalid value. Choose one of: {', '.join(choices)}.\n")


def _prompt_state_fields(
    input_stream: TextIO,
    output_stream: TextIO,
) -> list[dict[str, Any]]:
    output_stream.write(
        "\nState fields builder\n"
        "Add fields one by one. Leave field name blank to finish.\n"
    )
    fields: list[dict[str, Any]] = []
    index = 1
    while True:
        name = _readline(input_stream, output_stream, f"Field {index} name (blank to finish): ").strip()
        if not name:
            if fields:
                break
            output_stream.write(
                "No fields entered. Using default field: status (string, default=open).\n"
            )
            fields.append({"name": "status", "type": "string", "default": "open"})
            break
        if _FIELD_NAME_PATTERN.fullmatch(name) is None:
            output_stream.write(
                "Invalid field name. Use lowercase letters, digits, underscore.\n"
            )
            continue
        if any(entry["name"] == name for entry in fields):
            output_stream.write("Duplicate field name. Choose another name.\n")
            continue

        field_type = _prompt_choice(
            input_stream,
            output_stream,
            label=f"Field {index} type",
            choices=_ALLOWED_FIELD_TYPES,
            default="string",
        )
        default_value = _prompt_field_default(
            input_stream,
            output_stream,
            field_name=name,
            field_type=field_type,
        )
        field_payload: dict[str, Any] = {"name": name, "type": field_type}
        if default_value is not _MISSING:
            field_payload["default"] = default_value
        fields.append(field_payload)
        index += 1
    return fields


def _prompt_field_default(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    field_name: str,
    field_type: str,
) -> Any:
    while True:
        raw = _readline(
            input_stream,
            output_stream,
            f"Default for {field_name} ({field_type}, blank for none): ",
        ).strip()
        if raw == "":
            return _MISSING
        try:
            return _parse_default_value(raw, field_type=field_type)
        except ValueError as exc:
            output_stream.write(f"Invalid default: {exc}\n")


def _parse_default_value(raw: str, *, field_type: str) -> Any:
    if field_type == "string":
        return raw
    if field_type == "number":
        return float(raw)
    if field_type == "integer":
        return int(raw)
    if field_type == "boolean":
        token = raw.strip().lower()
        if token in _TRUE_VALUES:
            return True
        if token in _FALSE_VALUES:
            return False
        raise ValueError("boolean must be one of true/false/yes/no/1/0.")
    if field_type in {"object", "array"}:
        parsed = json.loads(raw)
        if field_type == "object" and not isinstance(parsed, dict):
            raise ValueError("object default must parse to a JSON object.")
        if field_type == "array" and not isinstance(parsed, list):
            raise ValueError("array default must parse to a JSON array.")
        return parsed
    raise ValueError(f"Unsupported field type: {field_type}")


def _prompt_optional_json_object(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    label: str,
) -> dict[str, Any]:
    while True:
        raw = _readline(
            input_stream,
            output_stream,
            f"{label} (blank for none): ",
        ).strip()
        if raw == "":
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            output_stream.write("Invalid JSON. Please provide a JSON object.\n")
            continue
        if not isinstance(payload, dict):
            output_stream.write("JSON must be an object.\n")
            continue
        return dict(payload)


def _prompt_yes_no(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    label: str,
    default: bool,
) -> bool:
    default_hint = "Y/n" if default else "y/N"
    while True:
        raw = _readline(input_stream, output_stream, f"{label} [{default_hint}]: ").strip().lower()
        if raw == "":
            return default
        if raw in _TRUE_VALUES:
            return True
        if raw in _FALSE_VALUES:
            return False
        output_stream.write("Please answer yes or no.\n")


def _state_defaults_as_attributes(fields: list[dict[str, Any]]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for field in fields:
        if "default" not in field:
            continue
        attrs[str(field["name"])] = field["default"]
    return attrs


def _readline(input_stream: TextIO, output_stream: TextIO, prompt: str) -> str:
    output_stream.write(prompt)
    output_stream.flush()
    raw = input_stream.readline()
    if raw == "":
        raise RuntimeError("Input stream ended before initialization completed.")
    return raw.rstrip("\n")
