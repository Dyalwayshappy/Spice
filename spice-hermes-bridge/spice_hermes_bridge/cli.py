from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spice_hermes_bridge.adapters.github_pr import poll_github_repo
from spice_hermes_bridge.adapters.whatsapp import (
    WhatsAppInboundMessage,
    observe_whatsapp_message,
)
from spice_hermes_bridge.observations import StructuredObservation, validate_observation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spice-hermes",
        description=(
            "Bridge external Hermes signals into structured Spice observations. "
            "Demo execution uses SDEP as the canonical Spice-Hermes boundary."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate-observation",
        help="Validate a structured observation JSON file.",
    )
    validate.add_argument("path", type=Path)
    validate.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable validation output.",
    )
    validate.set_defaults(handler=_handle_validate_observation)

    whatsapp = subparsers.add_parser(
        "whatsapp-observe",
        help="Convert one WhatsApp text message into a validated observation when supported.",
    )
    whatsapp.add_argument(
        "--text",
        help="WhatsApp message text. Use --input-json for a normalized payload file.",
    )
    whatsapp.add_argument(
        "--input-json",
        type=Path,
        help="Path to a JSON payload containing text/message/body plus optional metadata.",
    )
    whatsapp.add_argument("--chat-id")
    whatsapp.add_argument("--sender-id")
    whatsapp.add_argument("--message-id")
    whatsapp.add_argument(
        "--received-at",
        help="Optional ISO-8601 timestamp from the WhatsApp ingress source.",
    )
    whatsapp.add_argument(
        "--timezone",
        default="Asia/Shanghai",
        help="Timezone used to resolve relative dates such as 明天.",
    )
    whatsapp.add_argument(
        "--extractor",
        choices=("deterministic", "llm_assisted"),
        default="deterministic",
        help="Extractor mode. LLM mode emits proposals only and still goes through bridge gating.",
    )
    whatsapp.add_argument(
        "--pending-store",
        type=Path,
        default=Path(".spice-hermes/pending_confirmations.json"),
        help="Local pending confirmation store path.",
    )
    whatsapp.add_argument(
        "--resolve-pending",
        action="store_true",
        help="Resolve the most recent active pending confirmation in the same chat scope.",
    )
    whatsapp.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable ingress output.",
    )
    whatsapp.set_defaults(handler=_handle_whatsapp_observe)

    poll_github = subparsers.add_parser(
        "poll-github",
        help="Poll one GitHub repo and build deduplicated work_item_opened observations.",
    )
    poll_github.add_argument(
        "--repo",
        required=True,
        help="GitHub repository in owner/name format.",
    )
    poll_github.add_argument(
        "--delivery-state",
        type=Path,
        default=Path(".spice-hermes/delivery_state.json"),
        help="Local delivery state path for event_key deduplication.",
    )
    poll_github.add_argument(
        "--observations-log",
        type=Path,
        default=Path(".spice-hermes/observations.jsonl"),
        help="Local JSONL audit log for built observations.",
    )
    poll_github.add_argument(
        "--github-token",
        help="Optional GitHub token. If omitted, GITHUB_TOKEN is used when present.",
    )
    poll_github.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable polling output.",
    )
    poll_github.set_defaults(handler=_handle_poll_github)

    run_demo = subparsers.add_parser(
        "run-demo-flow",
        help="Run the local Spice demo flow through the canonical SDEP-backed execution spine.",
    )
    run_demo.add_argument(
        "--choice",
        choices=("confirm", "reject", "details"),
        default="confirm",
        help="Simulated confirmation response for confirmation-required recommendations.",
    )
    run_demo.add_argument(
        "--executor",
        choices=("sdep", "auto", "mock", "hermes"),
        default="sdep",
        help=(
            "Executor override. Default sdep is canonical; auto aliases sdep. "
            "mock/hermes are legacy debug overrides only."
        ),
    )
    run_demo.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable glue flow output.",
    )
    run_demo.set_defaults(handler=_handle_run_demo_flow)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def _handle_validate_observation(args: argparse.Namespace) -> int:
    observation = StructuredObservation.from_json(args.path.read_text())
    issues = validate_observation(observation)
    errors = [issue for issue in issues if issue.severity == "error"]

    payload = {
        "valid": not errors,
        "errors": len(errors),
        "warnings": len(issues) - len(errors),
        "issues": [issue.to_dict() for issue in issues],
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "valid" if payload["valid"] else "invalid"
        print(f"observation validation: {status}")
        for issue in issues:
            print(f"{issue.severity}: {issue.field}: {issue.message}")

    return 0 if not errors else 1


def _handle_whatsapp_observe(args: argparse.Namespace) -> int:
    if args.input_json:
        payload = json.loads(args.input_json.read_text())
        if not isinstance(payload, dict):
            raise ValueError("WhatsApp payload JSON must be an object")
        message = WhatsAppInboundMessage.from_payload(payload)
    else:
        if args.text is None:
            raise ValueError("whatsapp-observe requires --text or --input-json")
        message = WhatsAppInboundMessage(
            text=args.text,
            chat_id=args.chat_id,
            sender_id=args.sender_id,
            message_id=args.message_id,
            received_at=args.received_at,
        )

    result = observe_whatsapp_message(
        message,
        default_timezone=args.timezone,
        extractor=args.extractor,
        pending_store_path=args.pending_store,
        resolve_pending=args.resolve_pending,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"whatsapp ingress: {result.result_type}")
        if result.reason:
            print(f"reason: {result.reason}")
        if result.observation:
            print(f"observation_id: {result.observation.observation_id}")
            print(f"observation_type: {result.observation.observation_type}")
        if result.pending_confirmation:
            print(f"pending_id: {result.pending_confirmation.pending_id}")
            print(f"message: {result.pending_confirmation.message}")
        for warning in result.warnings:
            print(f"warning: {warning}")
        for issue in result.issues:
            print(f"{issue.severity}: {issue.field}: {issue.message}")

    return 0 if result.valid else 1


def _handle_poll_github(args: argparse.Namespace) -> int:
    result = poll_github_repo(
        args.repo,
        delivery_state_path=args.delivery_state,
        observations_log_path=args.observations_log,
        token=args.github_token,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"github poll: {result.status}")
        print(f"repo: {result.repo}")
        print(f"observations_built: {len(result.observations_built)}")
        print(f"deduped_event_keys: {len(result.deduped_event_keys)}")
        for observation in result.observations_built:
            print(f"observation_id: {observation.observation_id}")
            print(f"event_key: {observation.attributes.get('event_key')}")
        for event_key in result.deduped_event_keys:
            print(f"deduped: {event_key}")
        for warning in result.warnings:
            print(f"warning: {warning}")
        for issue in result.issues:
            print(f"{issue.severity}: {issue.field}: {issue.message}")

    return 0 if result.status in {"ok", "partial"} else 1


def _handle_run_demo_flow(args: argparse.Namespace) -> int:
    from spice_hermes_bridge.integrations.spice_demo import run_sample_flow

    executor = None
    if args.executor not in {"sdep", "auto"}:
        from spice_hermes_bridge.integrations.hermes_executor import create_executor

        executor = create_executor(args.executor)

    result = run_sample_flow(
        choice=args.choice,
        executor=executor,
    )
    payload = result.to_payload()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        recommendation = payload["recommendation"]
        print("spice demo glue flow")
        print(f"decision_id: {recommendation.get('decision_id')}")
        print(f"selected_action: {recommendation.get('selected_action')}")
        print(f"requires_confirmation: {recommendation.get('requires_confirmation')}")
        print()
        if payload.get("confirmation_text"):
            print(payload["confirmation_text"])
            print()
        if payload.get("resolution_text"):
            print(payload["resolution_text"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
