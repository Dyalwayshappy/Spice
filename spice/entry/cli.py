from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spice.decision import (
    DEFAULT_LOCAL_DECISION_PROFILE,
    DecisionGuidanceSupport,
    explain_decision_guidance,
    format_decision_guidance_explanation,
    init_decision_profile,
)
from spice.entry.assist import (
    ASSIST_MAX_TRIES_DEFAULT,
    capture_brief,
    resolve_assist_model,
    run_assist_session,
    write_assist_artifacts,
)
from spice.entry.init_domain import run_init_domain, run_init_domain_from_spec
from spice.entry.quickstart import QUICKSTART_DEFAULT_OUTPUT, run_quickstart


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice",
        description="Spice entry tooling.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    quickstart = subparsers.add_parser(
        "quickstart",
        help="Run the deterministic Spice first-success quickstart flow.",
    )
    quickstart.add_argument(
        "--output",
        type=Path,
        default=QUICKSTART_DEFAULT_OUTPUT,
        help="Output directory for generated quickstart scaffold (default: .spice/quickstart).",
    )
    quickstart.add_argument(
        "--force",
        action="store_true",
        help="Replace existing quickstart output directory.",
    )
    quickstart.add_argument(
        "--no-run",
        action="store_true",
        help="Generate scaffold and artifacts but skip executing run_demo.py.",
    )
    quickstart.set_defaults(handler=_handle_quickstart)

    decision_parser = subparsers.add_parser(
        "decision",
        help="Inspect decision.md guidance.",
    )
    decision_subparsers = decision_parser.add_subparsers(
        dest="decision_command",
        required=True,
    )
    decision_init = decision_subparsers.add_parser(
        "init",
        help="Copy the bundled default decision profile into this project.",
    )
    decision_init.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_LOCAL_DECISION_PROFILE,
        help="Local decision profile path (default: .spice/decision/decision.md).",
    )
    decision_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing local decision profile and copied support reference.",
    )
    decision_init.add_argument(
        "--no-support",
        action="store_true",
        help="Do not copy the reference support JSON used for explain/demo/debug flows.",
    )
    decision_init.set_defaults(handler=_handle_decision_init)

    decision_explain = decision_subparsers.add_parser(
        "explain",
        help="Validate and explain a decision.md file.",
    )
    decision_explain.add_argument(
        "path",
        type=Path,
        help="Path to decision.md.",
    )
    decision_explain.add_argument(
        "--support-json",
        type=Path,
        default=None,
        help=(
            "Optional JSON file declaring score_dimensions, constraint_ids, "
            "and tradeoff_rule_ids supported by the active policy/domain adapter."
        ),
    )
    decision_explain.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of the concise text report.",
    )
    decision_explain.set_defaults(handler=_handle_decision_explain)

    init_parser = subparsers.add_parser(
        "init",
        help="Initialize new artifacts from DomainSpec templates.",
    )
    init_subparsers = init_parser.add_subparsers(dest="init_command", required=True)
    init_domain = init_subparsers.add_parser(
        "domain",
        help="Interactively create a runnable Spice domain scaffold.",
    )
    init_domain.add_argument("name", help="Domain project folder name.")
    init_domain.add_argument(
        "--from-spec",
        type=Path,
        default=None,
        help="Use an existing DomainSpec JSON file instead of interactive prompts.",
    )
    init_domain.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: ./<name>).",
    )
    init_domain.add_argument(
        "--force",
        action="store_true",
        help="Replace existing output directory.",
    )
    init_domain.add_argument(
        "--no-run",
        action="store_true",
        help="Generate scaffold and artifacts but skip executing run_demo.py.",
    )
    init_domain.add_argument(
        "--with-llm",
        action="store_true",
        help=(
            "Generate scaffold with optional domain-level LLM decision/simulation wiring. "
            "This is template-level activation only (DomainSpec schema is unchanged)."
        ),
    )
    init_domain.add_argument(
        "--assist",
        action="store_true",
        help="Draft DomainSpec from a natural-language brief via LLM-assisted flow.",
    )
    init_domain.add_argument(
        "--assist-brief-file",
        type=Path,
        default=None,
        help="Read assist brief text from file.",
    )
    init_domain.add_argument(
        "--assist-stdin",
        action="store_true",
        help="Read assist brief from stdin (terminate with END line).",
    )
    init_domain.add_argument(
        "--assist-model",
        type=str,
        default=None,
        help=(
            "Model override for assist drafting. "
            "Use 'deterministic' to force deterministic provider; "
            "otherwise value is treated as a subprocess command "
            "(example: \"ollama run qwen2.5\")."
        ),
    )
    init_domain.add_argument(
        "--assist-max-tries",
        type=int,
        default=ASSIST_MAX_TRIES_DEFAULT,
        help=f"Max draft retries for invalid assist output (default: {ASSIST_MAX_TRIES_DEFAULT}).",
    )
    init_domain.set_defaults(handler=_handle_init_domain)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return int(handler(args))


def _handle_quickstart(args: argparse.Namespace) -> int:
    output_dir: Path = args.output
    force = bool(args.force)
    no_run = bool(args.no_run)
    try:
        print("[1/6] Load built-in DomainSpec ... OK")
        print("[2/6] Validate DomainSpec ... OK (schema_version=spice.domain_spec.v1)")
        print("[3/6] Render deterministic scaffold ... OK")
        report = run_quickstart(
            output_dir=output_dir,
            force=force,
            no_run=no_run,
        )
        print(
            "[4/6] Write scaffold ... OK "
            f"({len(report.scaffold_files)} files -> {report.output_dir})"
        )
        if report.demo_ran:
            print(
                "[5/6] Run generated demo ... OK "
                f"(command={' '.join(report.demo_command)})"
            )
            if report.last_cycle is not None:
                action_id = str(report.last_cycle.get("decision_action", ""))
                planned_operation = str(report.last_cycle.get("planned_operation", ""))
                executed_operation = str(report.last_cycle.get("execution_operation", ""))
                print(f"domain_action_id={action_id}")
                print(f"planned_execution_operation={planned_operation}")
                print(f"executed_operation={executed_operation}")
        else:
            print("[5/6] Run generated demo ... SKIPPED (--no-run)")
        print(
            "[6/6] Write artifacts ... OK "
            f"({report.stdout_log_path.parent / 'quickstart_summary.json'})"
        )
        print()
        print("Quickstart complete.")
        print(f"Inspect generated scaffold: {report.output_dir}")
        print(f"Reference DomainSpec: {report.domain_spec_path}")
        print("Next step: spice init domain <name>")
        return 0
    except Exception as exc:
        print(f"quickstart failed: {exc}", file=sys.stderr)
        return 1


def _handle_decision_explain(args: argparse.Namespace) -> int:
    try:
        support_source = str(args.support_json) if args.support_json is not None else ""
        support = (
            _load_decision_guidance_support(args.support_json)
            if args.support_json is not None
            else None
        )
        report = explain_decision_guidance(args.path, support=support)
        if support_source:
            report["support_contract"]["source"] = support_source
            report["support_contract"]["role"] = (
                "explain/debug input; runtime authority should come from the active policy/domain adapter"
            )
        if bool(args.json):
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_decision_guidance_explanation(report))
            if support_source:
                print()
                print(
                    "Support note: --support-json is for explain/debug. "
                    "Runtime capability should come from the active policy/domain adapter."
                )
        return 0
    except Exception as exc:
        print(f"decision explain failed: {exc}", file=sys.stderr)
        return 1


def _handle_decision_init(args: argparse.Namespace) -> int:
    try:
        report = init_decision_profile(
            output=args.output,
            force=bool(args.force),
            include_support=not bool(args.no_support),
        )
        print("Decision profile initialized.")
        print(f"profile_path={report.profile_path}")
        if report.support_path is not None:
            print(f"support_reference_path={report.support_path}")
            print(
                "support_reference_role=explain/debug only; runtime support comes from the active policy/domain adapter"
            )
        print()
        print("Next steps:")
        if report.support_path is not None:
            print(
                "  python -m spice.entry decision explain "
                f"{report.profile_path} --support-json {report.support_path}"
            )
        else:
            print(f"  python -m spice.entry decision explain {report.profile_path}")
        print("  Use guided_policy_from_profile(base_policy, profile_path) in Python runtime code.")
        return 0
    except Exception as exc:
        print(f"decision init failed: {exc}", file=sys.stderr)
        return 1


def _load_decision_guidance_support(path: Path) -> DecisionGuidanceSupport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("support JSON must be an object.")
    return DecisionGuidanceSupport.from_dict(payload)


def _handle_init_domain(args: argparse.Namespace) -> int:
    output_dir: Path = args.output if args.output is not None else Path(args.name)
    force = bool(args.force)
    no_run = bool(args.no_run)
    from_spec = args.from_spec
    assist = bool(args.assist)
    assist_brief_file = args.assist_brief_file
    assist_stdin = bool(args.assist_stdin)
    assist_model = args.assist_model
    assist_max_tries = max(1, int(args.assist_max_tries))
    with_llm = bool(args.with_llm)

    if assist and from_spec is not None:
        print("init domain failed: --assist cannot be combined with --from-spec.", file=sys.stderr)
        return 1
    if assist_brief_file is not None and assist_stdin:
        print(
            "init domain failed: use either --assist-brief-file or --assist-stdin, not both.",
            file=sys.stderr,
        )
        return 1

    try:
        if assist:
            print("[1/7] Capture domain brief ...")
            brief = capture_brief(
                brief_file=assist_brief_file,
                use_stdin=assist_stdin,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
            )
            if not brief.strip():
                raise RuntimeError("Assist brief is empty.")

            model, model_backend = resolve_assist_model(model=assist_model)
            print(f"[2/7] Draft DomainSpec via assist model ... ({model_backend})")
            session = run_assist_session(
                domain_name=str(args.name),
                brief=brief,
                draft_service=model,
                model_backend=model_backend,
                max_tries=assist_max_tries,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
            )
            print("[3/7] Validate accepted DomainSpec ... OK (schema_version=spice.domain_spec.v1)")
            print("[4/7] Render deterministic scaffold ... OK")
            report = run_init_domain_from_spec(
                spec=session.accepted_spec,
                output_dir=output_dir,
                force=force,
                no_run=no_run,
                with_llm=with_llm,
                interactive=False,
                from_spec_path=None,
            )
            assist_summary_path = write_assist_artifacts(
                artifacts_root=report.stdout_log_path.parent,
                session=session,
            )
            print(
                "[5/7] Write scaffold ... OK "
                f"({len(report.scaffold_files)} files -> {report.output_dir})"
            )
            if report.demo_ran:
                print(
                    "[6/7] Run generated demo ... OK "
                    f"(command={' '.join(report.demo_command)})"
                )
                if report.last_cycle is not None:
                    action_id = str(report.last_cycle.get("decision_action", ""))
                    planned_operation = str(report.last_cycle.get("planned_operation", ""))
                    executed_operation = str(report.last_cycle.get("execution_operation", ""))
                    print(f"domain_action_id={action_id}")
                    print(f"planned_execution_operation={planned_operation}")
                    print(f"executed_operation={executed_operation}")
            else:
                print("[6/7] Run generated demo ... SKIPPED (--no-run)")
            print(
                "[7/7] Write artifacts ... OK "
                f"({assist_summary_path}, {report.stdout_log_path.parent / 'init_summary.json'})"
            )
            print()
            print("Domain init (--assist) complete.")
            print(f"Inspect generated scaffold: {report.output_dir}")
            print(f"Reference DomainSpec: {report.domain_spec_path}")
            return 0

        mode = "from-spec" if from_spec is not None else "interactive"
        print(f"[1/6] Build DomainSpec ({mode}) ...")
        report = run_init_domain(
            name=str(args.name),
            output_dir=output_dir,
            force=force,
            no_run=no_run,
            with_llm=with_llm,
            from_spec=from_spec,
            input_stream=sys.stdin,
            output_stream=sys.stdout,
        )
        print("[2/6] Validate DomainSpec ... OK (schema_version=spice.domain_spec.v1)")
        print("[3/6] Render deterministic scaffold ... OK")
        print(
            "[4/6] Write scaffold ... OK "
            f"({len(report.scaffold_files)} files -> {report.output_dir})"
        )
        if report.demo_ran:
            print(
                "[5/6] Run generated demo ... OK "
                f"(command={' '.join(report.demo_command)})"
            )
            if report.last_cycle is not None:
                action_id = str(report.last_cycle.get("decision_action", ""))
                planned_operation = str(report.last_cycle.get("planned_operation", ""))
                executed_operation = str(report.last_cycle.get("execution_operation", ""))
                print(f"domain_action_id={action_id}")
                print(f"planned_execution_operation={planned_operation}")
                print(f"executed_operation={executed_operation}")
        else:
            print("[5/6] Run generated demo ... SKIPPED (--no-run)")
        print(
            "[6/6] Write artifacts ... OK "
            f"({report.stdout_log_path.parent / 'init_summary.json'})"
        )
        print()
        print("Domain init complete.")
        print(f"Inspect generated scaffold: {report.output_dir}")
        print(f"Reference DomainSpec: {report.domain_spec_path}")
        print("Tip: run spice quickstart first if you want a prebuilt reference scaffold.")
        return 0
    except Exception as exc:
        print(f"init domain failed: {exc}", file=sys.stderr)
        return 1
