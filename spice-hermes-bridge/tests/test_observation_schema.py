from __future__ import annotations

import unittest
from pathlib import Path

from spice_hermes_bridge.observations import (
    StructuredObservation,
    build_event_key,
    build_observation,
    validate_observation,
)


class ObservationSchemaTest(unittest.TestCase):
    def test_builder_generates_bridge_owned_identity_and_utc_time(self) -> None:
        observation = build_observation(
            observation_type="commitment_declared",
            source="whatsapp",
            attributes={
                "summary": "投资人会议",
                "start_time": "2026-04-17T15:00:00+08:00",
                "duration_minutes": 90,
            },
            provenance={"adapter": "whatsapp_schedule.v1"},
        )

        self.assertRegex(
            observation.observation_id or "",
            r"^obs_[0-9a-f]{32}$",
        )
        self.assertTrue(observation.observed_at.endswith("+00:00"))
        self.assertEqual(validate_observation(observation), [])

    def test_missing_observation_id_is_invalid(self) -> None:
        observation = StructuredObservation(
            observation_type="commitment_declared",
            source="whatsapp",
            observed_at="2026-04-16T02:00:00+00:00",
            confidence=0.9,
            attributes={
                "summary": "投资人会议",
                "start_time": "2026-04-17T15:00:00+08:00",
                "duration_minutes": 90,
            },
            provenance={"adapter": "whatsapp_schedule.v1"},
        )

        issues = validate_observation(observation)

        self.assertTrue(any(issue.field == "observation_id" for issue in issues))

    def test_observed_at_requires_timezone(self) -> None:
        observation = build_observation(
            observation_type="commitment_declared",
            source="whatsapp",
            observed_at="2026-04-16T02:00:00",
            attributes={
                "summary": "投资人会议",
                "start_time": "2026-04-17T15:00:00+08:00",
                "duration_minutes": 90,
            },
            provenance={"adapter": "whatsapp_schedule.v1"},
        )

        issues = validate_observation(observation)

        self.assertTrue(any(issue.field == "observed_at" for issue in issues))

    def test_malformed_confidence_is_validation_error(self) -> None:
        observation = StructuredObservation.from_dict(
            {
                "observation_id": "obs_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "observation_type": "commitment_declared",
                "source": "whatsapp",
                "observed_at": "2026-04-16T02:00:00+00:00",
                "confidence": "high",
                "attributes": {
                    "summary": "投资人会议",
                    "start_time": "2026-04-17T15:00:00+08:00",
                    "duration_minutes": 90,
                },
                "provenance": {"adapter": "whatsapp_schedule.v1"},
            }
        )

        issues = validate_observation(observation)

        self.assertTrue(any(issue.field == "confidence" for issue in issues))

    def test_malformed_attributes_and_provenance_are_validation_errors(self) -> None:
        observation = StructuredObservation.from_dict(
            {
                "observation_id": "obs_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "observation_type": "commitment_declared",
                "source": "whatsapp",
                "observed_at": "2026-04-16T02:00:00+00:00",
                "attributes": "not-an-object",
                "provenance": "not-an-object",
            }
        )

        issues = validate_observation(observation)

        self.assertTrue(any(issue.field == "attributes" for issue in issues))
        self.assertTrue(any(issue.field == "provenance" for issue in issues))

    def test_commitment_declared_requires_time_window(self) -> None:
        observation = build_observation(
            observation_type="commitment_declared",
            source="whatsapp",
            confidence=0.9,
            attributes={
                "summary": "投资人会议",
                "start_time": "2026-04-17T15:00:00+08:00",
            },
            provenance={"adapter": "whatsapp_schedule.v1"},
        )

        issues = validate_observation(observation)

        self.assertTrue(any(issue.field == "attributes.end_time" for issue in issues))

    def test_work_item_opened_requires_event_key_for_dedup(self) -> None:
        observation = build_observation(
            observation_type="work_item_opened",
            source="github",
            attributes={
                "kind": "pull_request",
                "repo": "Dyalwayshappy/Spice",
                "item_id": "123",
                "title": "Fix validation",
                "action": "opened",
            },
            provenance={"adapter": "github_pr.v1"},
        )

        issues = validate_observation(observation)

        self.assertTrue(
            any(issue.field == "attributes.event_key" for issue in issues)
        )

    def test_execution_result_requires_decision_id_and_execution_ref(self) -> None:
        observation = build_observation(
            observation_type="execution_result_observed",
            source="hermes",
            attributes={
                "acted_on": "workitem.github_pr.123",
                "selected_action": "quick_triage_then_defer",
                "status": "success",
                "risk_change": "reduced",
            },
            provenance={"executor": "codex"},
        )

        issues = validate_observation(observation)

        self.assertTrue(
            any(issue.field == "attributes.decision_id" for issue in issues)
        )
        self.assertTrue(
            any(issue.field == "attributes.execution_ref" for issue in issues)
        )

    def test_valid_execution_result_accepts_decision_id_and_execution_ref(self) -> None:
        observation = build_observation(
            observation_type="execution_result_observed",
            source="hermes",
            attributes={
                "decision_id": "decision.demo",
                "execution_ref": "hermes.session.demo.execution.1",
                "acted_on": "workitem.github_pr.123",
                "selected_action": "quick_triage_then_defer",
                "status": "success",
                "risk_change": "reduced",
            },
            provenance={"executor": "codex"},
        )

        issues = validate_observation(observation)

        self.assertEqual(
            [issue for issue in issues if issue.severity == "error"],
            [],
        )

    def test_examples_validate(self) -> None:
        examples = Path(__file__).parents[1] / "examples"
        observation_examples = (
            "commitment_declared.json",
            "work_item_opened.json",
            "executor_capability_observed.json",
            "execution_result_observed.json",
        )

        for name in observation_examples:
            path = examples / name
            with self.subTest(path=path.name):
                observation = StructuredObservation.from_json(path.read_text())
                issues = validate_observation(observation)
                self.assertEqual(
                    [issue.to_dict() for issue in issues if issue.severity == "error"],
                    [],
                )

    def test_event_key_is_stable_and_action_specific(self) -> None:
        opened = build_event_key(
            source="github",
            namespace="Dyalwayshappy/Spice",
            item_type="pull_request",
            item_id=123,
            action="opened",
        )
        review_requested = build_event_key(
            source="github",
            namespace="Dyalwayshappy/Spice",
            item_type="pull_request",
            item_id=123,
            action="review_requested",
        )

        self.assertEqual(
            opened,
            "github:Dyalwayshappy/Spice:pull_request:123:opened",
        )
        self.assertEqual(
            opened,
            build_event_key(
                source="github",
                namespace="Dyalwayshappy/Spice",
                item_type="pull_request",
                item_id=123,
                action="opened",
            ),
        )
        self.assertNotEqual(opened, review_requested)

    def test_executor_capability_requires_runtime_contract_fields(self) -> None:
        observation = build_observation(
            observation_type="executor_capability_observed",
            source="hermes",
            attributes={
                "capability_id": "cap.external_executor.codex",
                "action_type": "delegate_to_executor",
                "executor": "codex",
                "supported_scopes": ["triage"],
                "availability": "available",
            },
            provenance={"adapter": "hermes_capability.v1"},
        )

        issues = validate_observation(observation)

        self.assertTrue(
            any(issue.field == "attributes.requires_confirmation" for issue in issues)
        )
        self.assertTrue(any(issue.field == "attributes.reversible" for issue in issues))
        self.assertTrue(
            any(issue.field == "attributes.default_time_budget_minutes" for issue in issues)
        )


if __name__ == "__main__":
    unittest.main()
