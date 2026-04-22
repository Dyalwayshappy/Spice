from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spice.protocols.observation import Observation

from examples.decision_hub_demo.confirmation import (
    DecisionControlLoop,
    format_confirmation_for_whatsapp,
)
from examples.decision_hub_demo.llm_simulation import build_simulation_runner_from_env
from examples.decision_hub_demo.policy import DecisionHubRecommendationRunner
from examples.decision_hub_demo.reducer import ingest_observation
from examples.decision_hub_demo.state import DOMAIN_KEY, new_world_state

DEMO_DIR = Path(__file__).resolve().parent
DEFAULT_COMPARE_OUTPUT_DIR = DEMO_DIR / "compare_artifacts"


def build_demo_state(now: datetime):
    state = new_world_state()
    ingest_observation(
        state,
        Observation(
            id="obs.demo.capability.codex",
            timestamp=now,
            observation_type="executor_capability_observed",
            source="hermes",
            metadata={
                "adapter": "hermes_capability.v1",
                "reported_by": "hermes",
                "notes": "Codex available via Hermes terminal/codex skill.",
            },
            attributes={
                "capability_id": "cap.external_executor.codex",
                "action_type": "delegate_to_executor",
                "executor": "codex",
                "supported_scopes": ["triage", "review_summary"],
                "requires_confirmation": True,
                "reversible": True,
                "default_time_budget_minutes": 10,
                "availability": "available",
            },
        ),
    )
    ingest_observation(
        state,
        Observation(
            id="obs.demo.commitment",
            timestamp=now,
            observation_type="commitment_declared",
            source="whatsapp",
            attributes={
                "commitment_id": "commitment.demo.flight",
                "summary": "Leave for fixed commitment",
                "start_time": (now + timedelta(minutes=42)).isoformat(),
                "end_time": (now + timedelta(minutes=102)).isoformat(),
                "duration_minutes": 60,
                "prep_start_time": (now + timedelta(minutes=12)).isoformat(),
                "priority_hint": "high",
                "flexibility_hint": "fixed",
                "constraint_hints": ["do_not_be_late"],
            },
        ),
    )
    ingest_observation(
        state,
        Observation(
            id="obs.demo.github.pr",
            timestamp=now,
            observation_type="work_item_opened",
            source="github",
            attributes={
                "kind": "pull_request",
                "repo": "Dyalwayshappy/Spice",
                "item_id": "123",
                "title": "Fix decision guidance validation",
                "url": "https://github.com/Dyalwayshappy/Spice/pull/123",
                "action": "opened",
                "urgency_hint": "medium",
                "estimated_minutes_hint": 30,
                "requires_attention": True,
                "event_key": "github:Dyalwayshappy/Spice:pull_request:123:opened",
            },
        ),
    )
    return state


def run_path(choice: str, *, now: datetime) -> dict[str, object]:
    state = build_demo_state(now)
    result = DecisionHubRecommendationRunner(
        simulation_runner=build_simulation_runner_from_env()
    ).recommend(state, {"now": now})
    loop = DecisionControlLoop()
    control = loop.handle_recommendation(state, result, now=now)
    resolution = None
    confirmation_text = None
    if control.confirmation_request:
        confirmation_text = format_confirmation_for_whatsapp(control.confirmation_request)
        resolution = loop.resolve_confirmation(
            state,
            str(control.confirmation_request["confirmation_id"]),
            choice=choice,  # type: ignore[arg-type]
            now=now + timedelta(minutes=6),
        )
    demo_state = state.domain_state[DOMAIN_KEY]
    acted_on = result["acted_on"]
    return {
        "decision_id": result["decision_id"],
        "selected_action": result["selected_action"],
        "requires_confirmation": result["requires_confirmation"],
        "acted_on": result["acted_on"],
        "human_summary": result["human_summary"],
        "reason_summary": result["reason_summary"],
        "tradeoff_rules_applied": result["tradeoff_rules_applied"],
        "veto_reasons": result["veto_reasons"],
        "score_breakdown": result["score_breakdown"],
        "trace_ref": result["trace_ref"],
        "compare_payload": result["compare_payload"],
        "control": control.to_payload(),
        "confirmation_text": confirmation_text,
        "resolution": resolution.to_payload() if resolution else None,
        "updated_work_item": demo_state["work_items"].get(acted_on, {}),
        "recent_outcome": demo_state["recent_outcomes"][-1] if demo_state["recent_outcomes"] else None,
        "confirmation_store": loop.confirmation_store.to_payload(),
    }


def build_compare_artifact(*, now: datetime) -> dict[str, object]:
    state = build_demo_state(now)
    result = DecisionHubRecommendationRunner(
        simulation_runner=build_simulation_runner_from_env()
    ).recommend(state, {"now": now})
    return result["compare_payload"]


def _write_compare_artifact(output_dir: Path, *, now: datetime) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "meeting_vs_pr_conflict.json"
    target.write_text(
        json.dumps(build_compare_artifact(now=now), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run decision_hub_demo scenarios.")
    parser.add_argument(
        "--write-compare-artifact",
        action="store_true",
        help="Write a compare artifact generated from the demo decision path.",
    )
    parser.add_argument(
        "--compare-output-dir",
        type=Path,
        default=DEFAULT_COMPARE_OUTPUT_DIR,
        help="Directory for generated compare artifacts (default: examples/decision_hub_demo/compare_artifacts).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if bool(args.write_compare_artifact):
        artifact_path = _write_compare_artifact(args.compare_output_dir, now=now)
        print(f"compare_artifact={artifact_path}")
        return

    print(
        json.dumps(
            {
                "scenario_a_confirm": run_path("confirm", now=now),
                "scenario_b_reject": run_path("reject", now=now),
                "scenario_c_details": run_path("details", now=now),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
