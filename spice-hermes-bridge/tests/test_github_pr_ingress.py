from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from spice_hermes_bridge.adapters.github_pr import poll_github_repo
from spice_hermes_bridge.cli import main
from spice_hermes_bridge.storage.delivery import load_delivery_state


def _pull(
    *,
    number: int | None = 123,
    title: str = "Fix decision guidance validation",
    requested_reviewers: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/Dyalwayshappy/Spice/pull/{number}",
        "created_at": "2026-04-17T00:10:00Z",
        "requested_reviewers": requested_reviewers or [],
        "requested_teams": [],
    }
    if number is None:
        payload.pop("number")
    return payload


class GitHubPrIngressTest(unittest.TestCase):
    def test_new_pr_opened_builds_valid_work_item_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            result = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull()],
                delivery_state_path=Path(tempdir) / "delivery_state.json",
                observations_log_path=Path(tempdir) / "observations.jsonl",
                polled_at="2026-04-17T00:20:00+00:00",
            )

            self.assertEqual(result.status, "ok")
            self.assertEqual(len(result.observations_built), 1)
            observation = result.observations_built[0]
            self.assertEqual(observation.observation_type, "work_item_opened")
            self.assertEqual(observation.source, "github")
            self.assertEqual(observation.confidence, 1.0)
            self.assertEqual(
                observation.attributes["event_key"],
                "github:Dyalwayshappy/Spice:pull_request:123:opened",
            )
            self.assertEqual(observation.attributes["item_id"], "123")
            self.assertEqual(observation.attributes["action"], "opened")
            self.assertEqual(observation.observed_at, "2026-04-17T00:10:00+00:00")
            self.assertEqual(
                observation.provenance["time_anchor_source"],
                "github_event_time",
            )

    def test_review_requested_builds_second_work_item_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            result = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull(requested_reviewers=[{"login": "reviewer"}])],
                delivery_state_path=Path(tempdir) / "delivery_state.json",
                observations_log_path=Path(tempdir) / "observations.jsonl",
                polled_at="2026-04-17T00:20:00+00:00",
            )

            keys = {item.attributes["event_key"] for item in result.observations_built}
            self.assertEqual(
                keys,
                {
                    "github:Dyalwayshappy/Spice:pull_request:123:opened",
                    "github:Dyalwayshappy/Spice:pull_request:123:review_requested",
                },
            )
            review = [
                item
                for item in result.observations_built
                if item.attributes["action"] == "review_requested"
            ][0]
            self.assertTrue(review.attributes["requires_attention"])
            self.assertEqual(review.observed_at, "2026-04-17T00:20:00+00:00")
            self.assertEqual(review.provenance["requested_reviewer_count"], 1)
            self.assertEqual(review.provenance["time_anchor_source"], "poll_time")

    def test_duplicate_poll_does_not_rewrite_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            delivery_state = Path(tempdir) / "delivery_state.json"
            audit_log = Path(tempdir) / "observations.jsonl"
            first = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull()],
                delivery_state_path=delivery_state,
                observations_log_path=audit_log,
                polled_at="2026-04-17T00:20:00+00:00",
            )
            second = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull()],
                delivery_state_path=delivery_state,
                observations_log_path=audit_log,
                polled_at="2026-04-17T00:25:00+00:00",
            )

            self.assertEqual(len(first.observations_built), 1)
            self.assertEqual(len(second.observations_built), 0)
            self.assertEqual(
                second.deduped_event_keys,
                ("github:Dyalwayshappy/Spice:pull_request:123:opened",),
            )
            self.assertEqual(len(audit_log.read_text().splitlines()), 1)

    def test_validation_failure_does_not_mark_processed(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            delivery_state = Path(tempdir) / "delivery_state.json"
            result = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull(title="")],
                delivery_state_path=delivery_state,
                observations_log_path=Path(tempdir) / "observations.jsonl",
                polled_at="2026-04-17T00:20:00+00:00",
            )

            self.assertEqual(result.status, "error")
            self.assertEqual(result.observations_built, ())
            self.assertTrue(
                any(issue.field == "attributes.title" for issue in result.issues)
            )
            self.assertFalse(delivery_state.exists())

    def test_delivery_state_and_audit_log_are_written_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            delivery_state = Path(tempdir) / "delivery_state.json"
            audit_log = Path(tempdir) / "observations.jsonl"
            result = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull()],
                delivery_state_path=delivery_state,
                observations_log_path=audit_log,
                polled_at="2026-04-17T00:20:00+00:00",
            )

            state = load_delivery_state(path=delivery_state)
            event_key = "github:Dyalwayshappy/Spice:pull_request:123:opened"
            self.assertIn(event_key, state["processed_event_keys"])
            self.assertEqual(
                state["processed_event_keys"][event_key]["observation_id"],
                result.observations_built[0].observation_id,
            )
            audit_payload = json.loads(audit_log.read_text().splitlines()[0])
            self.assertEqual(audit_payload["attributes"]["event_key"], event_key)

    def test_existing_audit_without_delivery_state_is_repaired_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            delivery_state = Path(tempdir) / "delivery_state.json"
            audit_log = Path(tempdir) / "observations.jsonl"
            first = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull()],
                delivery_state_path=delivery_state,
                observations_log_path=audit_log,
                polled_at="2026-04-17T00:20:00+00:00",
            )
            delivery_state.unlink()

            second = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull()],
                delivery_state_path=delivery_state,
                observations_log_path=audit_log,
                polled_at="2026-04-17T00:25:00+00:00",
            )

            event_key = "github:Dyalwayshappy/Spice:pull_request:123:opened"
            state = load_delivery_state(path=delivery_state)
            self.assertEqual(second.observations_built, ())
            self.assertEqual(second.deduped_event_keys, (event_key,))
            self.assertEqual(len(audit_log.read_text().splitlines()), 1)
            self.assertEqual(
                state["processed_event_keys"][event_key]["observation_id"],
                first.observations_built[0].observation_id,
            )
            self.assertIn(
                f"repaired_delivery_state_from_audit={event_key}",
                second.warnings,
            )

    def test_partial_status_keeps_successful_observation_and_unprocessed_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            delivery_state = Path(tempdir) / "delivery_state.json"
            audit_log = Path(tempdir) / "observations.jsonl"
            result = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull(number=123), _pull(number=456, title="")],
                delivery_state_path=delivery_state,
                observations_log_path=audit_log,
                polled_at="2026-04-17T00:20:00+00:00",
            )

            self.assertEqual(result.status, "partial")
            self.assertEqual(len(result.observations_built), 1)
            self.assertTrue(
                any(issue.field == "attributes.title" for issue in result.issues)
            )
            state = load_delivery_state(path=delivery_state)
            self.assertIn(
                "github:Dyalwayshappy/Spice:pull_request:123:opened",
                state["processed_event_keys"],
            )
            self.assertNotIn(
                "github:Dyalwayshappy/Spice:pull_request:456:opened",
                state["processed_event_keys"],
            )

    def test_missing_pr_number_is_not_marked_processed(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            result = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull(number=None)],
                delivery_state_path=Path(tempdir) / "delivery_state.json",
                observations_log_path=Path(tempdir) / "observations.jsonl",
                polled_at="2026-04-17T00:20:00+00:00",
            )

            self.assertEqual(result.status, "error")
            self.assertTrue(
                any(issue.field == "attributes.item_id" for issue in result.issues)
            )

    def test_cli_json_contract_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "poll-github",
                        "--repo",
                        "not-a-valid-owner-name",
                        "--delivery-state",
                        str(Path(tempdir) / "delivery_state.json"),
                        "--observations-log",
                        str(Path(tempdir) / "observations.jsonl"),
                        "--json",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertIn("result_type", payload)
            self.assertIn("status", payload)
            self.assertIn("repo", payload)
            self.assertIn("observations_built", payload)
            self.assertIn("deduped_event_keys", payload)
            self.assertIn("warnings", payload)
            self.assertIn("issues", payload)
            self.assertIn(payload["status"], {"ok", "partial", "error"})
            self.assertIsInstance(exit_code, int)

    def test_adapter_does_not_emit_importance_state_or_conflict_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            result = poll_github_repo(
                "Dyalwayshappy/Spice",
                fetcher=lambda repo: [_pull()],
                delivery_state_path=Path(tempdir) / "delivery_state.json",
                observations_log_path=Path(tempdir) / "observations.jsonl",
                polled_at="2026-04-17T00:20:00+00:00",
            )

            observation = result.observations_built[0]
            serialized = json.dumps(observation.to_dict())
            self.assertNotIn("world_state", serialized)
            self.assertNotIn("active_decision_context", serialized)
            self.assertNotIn("conflict", serialized)
            self.assertNotIn("recommendation", serialized)


if __name__ == "__main__":
    unittest.main()
