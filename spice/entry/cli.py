from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
