from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from spice.protocols.observation import Observation
from spice.protocols.world_state import WorldState

from examples.decision_hub_demo.confirmation import (
    ConfirmationResolution,
    ControlLoopResult,
    DecisionControlLoop,
)
from examples.decision_hub_demo.execution_adapter import ExecutionFeedbackAdapter, Executor
from examples.decision_hub_demo.llm_simulation import build_simulation_runner_from_env
from examples.decision_hub_demo.policy import DecisionHubRecommendationRunner
from examples.decision_hub_demo.reducer import ingest_observation
from examples.decision_hub_demo.state import DOMAIN_KEY, new_world_state

from spice_hermes_bridge.observations import (
    StructuredObservation,
    build_event_key,
    build_observation,
    validate_observation,
)


@dataclass(slots=True)
class SpiceDemoRunResult:
    """Result payload for the local bridge -> Spice -> executor glue flow."""

    observations: list[dict[str, Any]]
    recommendation: dict[str, Any]
    control: dict[str, Any]
    confirmation_text: str | None
    resolution: dict[str, Any] | None
    resolution_text: str | None
    updated_work_item: dict[str, Any]
    recent_outcome: dict[str, Any] | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "recommendation": self.recommendation,
            "control": self.control,
            "confirmation_text": self.confirmation_text,
            "resolution": self.resolution,
            "resolution_text": self.resolution_text,
            "updated_work_item": self.updated_work_item,
            "recent_outcome": self.recent_outcome,
        }


class SpiceDemoSession:
    """Thin adapter around examples.decision_hub_demo.

    Bridge observations are converted into Spice Observation records and then
    applied through the demo reducer. The session does not bypass WorldState,
    candidate generation, confirmation, execution, or outcome reduction.
    """

    def __init__(
        self,
        *,
        state: WorldState | None = None,
        executor: Executor | None = None,
        runner: DecisionHubRecommendationRunner | None = None,
    ) -> None:
        self.state = state or new_world_state()
        self.runner = runner or DecisionHubRecommendationRunner(
            simulation_runner=build_simulation_runner_from_env()
        )
        self.control_loop = DecisionControlLoop(
            execution_adapter=ExecutionFeedbackAdapter(executor=executor),
        )

    def ingest_into_spice(self, observation: StructuredObservation) -> Observation:
        spice_observation = bridge_observation_to_spice(observation)
        ingest_observation(self.state, spice_observation)
        return spice_observation

    def ingest_many(self, observations: list[StructuredObservation]) -> list[Observation]:
        return [self.ingest_into_spice(observation) for observation in observations]

    def recommend(self, *, now: datetime | None = None) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if now is not None:
            context["now"] = now
        return self.runner.recommend(self.state, context)

    def handle_recommendation(
        self,
        recommendation: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> ControlLoopResult:
        return self.control_loop.handle_recommendation(self.state, recommendation, now=now)

    def resolve_confirmation(
        self,
        confirmation_id: str,
        *,
        choice: str,
        now: datetime | None = None,
    ) -> ConfirmationResolution:
        if choice not in {"confirm", "reject", "details"}:
            raise ValueError("choice must be one of: confirm, reject, details")
        return self.control_loop.resolve_confirmation(
            self.state,
            confirmation_id,
            choice=choice,  # type: ignore[arg-type]
            now=now,
        )

    def latest_work_item(self, recommendation: dict[str, Any]) -> dict[str, Any]:
        acted_on = recommendation.get("acted_on")
        if not acted_on:
            return {}
        demo = self.state.domain_state.get(DOMAIN_KEY, {})
        return dict(demo.get("work_items", {}).get(acted_on, {}))

    def latest_outcome(self) -> dict[str, Any] | None:
        demo = self.state.domain_state.get(DOMAIN_KEY, {})
        outcomes = demo.get("recent_outcomes", [])
        if not outcomes:
            return None
        return dict(outcomes[-1])


def bridge_observation_to_spice(observation: StructuredObservation) -> Observation:
    """Convert a validated bridge observation into the Spice protocol record."""

    issues = validate_observation(observation)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        messages = "; ".join(f"{issue.field}: {issue.message}" for issue in errors)
        raise ValueError(f"invalid bridge observation: {messages}")

    observed_at = _parse_observed_at(observation.observed_at)
    return Observation(
        id=str(observation.observation_id),
        timestamp=observed_at,
        observation_type=observation.observation_type,
        source=observation.source,
        attributes=dict(observation.attributes),
        metadata={
            **dict(observation.provenance),
            "confidence": observation.confidence,
            "bridge_observed_at": observation.observed_at,
            "bridge_observation_id": observation.observation_id,
        },
    )


def sample_bridge_observations(*, now: datetime | None = None) -> list[StructuredObservation]:
    """Build the smallest local scenario for WhatsApp + GitHub + Codex capability."""

    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    commitment_start = anchor + timedelta(minutes=42)
    commitment_end = anchor + timedelta(minutes=102)
    prep_start = anchor + timedelta(minutes=12)

    return [
        build_observation(
            observation_type="executor_capability_observed",
            source="hermes",
            observed_at=anchor.isoformat(),
            confidence=1.0,
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
            provenance={
                "adapter": "hermes_capability.v1",
                "reported_by": "hermes",
                "notes": "Codex available via Hermes terminal/codex skill.",
            },
        ),
        build_observation(
            observation_type="commitment_declared",
            source="whatsapp",
            observed_at=anchor.isoformat(),
            confidence=0.95,
            attributes={
                "commitment_id": "commitment.demo.fixed_departure",
                "summary": "Leave for fixed commitment",
                "start_time": commitment_start.isoformat(),
                "end_time": commitment_end.isoformat(),
                "duration_minutes": 60,
                "prep_start_time": prep_start.isoformat(),
                "priority_hint": "high",
                "flexibility_hint": "fixed",
                "constraint_hints": ["do_not_be_late"],
            },
            provenance={
                "adapter": "whatsapp_schedule.v1",
                "extractor_mode": "deterministic",
            },
        ),
        build_observation(
            observation_type="work_item_opened",
            source="github",
            observed_at=anchor.isoformat(),
            confidence=1.0,
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
                "event_key": build_event_key(
                    source="github",
                    namespace="Dyalwayshappy/Spice",
                    item_type="pull_request",
                    item_id="123",
                    action="opened",
                ),
            },
            provenance={
                "adapter": "github_pr.v1",
                "api_source": "quickstart_sample",
                "time_anchor_source": "poll_time",
            },
        ),
    ]


def run_sample_flow(
    *,
    choice: str = "confirm",
    executor: Executor | None = None,
    now: datetime | None = None,
) -> SpiceDemoRunResult:
    from spice_hermes_bridge.integrations.whatsapp_reply import (
        format_confirmation_resolution_for_whatsapp,
        format_control_result_for_whatsapp,
    )

    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    observations = sample_bridge_observations(now=anchor)
    session = SpiceDemoSession(executor=executor)
    session.ingest_many(observations)
    recommendation = session.recommend(now=anchor)
    control = session.handle_recommendation(recommendation, now=anchor)
    confirmation_text = format_control_result_for_whatsapp(control)
    resolution = None
    resolution_text = None

    control_payload = control.to_payload()
    request = control_payload.get("confirmation_request")
    if request:
        resolution = session.resolve_confirmation(
            str(request["confirmation_id"]),
            choice=choice,
            now=anchor + timedelta(minutes=6),
        )
        resolution_text = format_confirmation_resolution_for_whatsapp(resolution)

    return SpiceDemoRunResult(
        observations=[observation.to_dict() for observation in observations],
        recommendation=recommendation,
        control=control_payload,
        confirmation_text=confirmation_text,
        resolution=resolution.to_payload() if resolution else None,
        resolution_text=resolution_text,
        updated_work_item=session.latest_work_item(recommendation),
        recent_outcome=session.latest_outcome(),
    )


def _parse_observed_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include timezone")
    return parsed.astimezone(timezone.utc)
