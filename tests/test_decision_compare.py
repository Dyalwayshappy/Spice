from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from examples.decision_hub_demo.run_demo import build_compare_artifact
from examples.decision_hub_demo.trace import TRACE_REGISTRY
from spice.decision.compare import render_compare_json, render_compare_text
from spice.decision.compare_payload import (
    build_compare_payload_from_trace,
    load_compare_payload,
    normalize_compare_payload,
)
from spice.entry.cli import main


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "examples" / "decision_hub_demo" / "compare_artifacts" / "meeting_vs_pr_conflict.json"
NOW = datetime(2026, 4, 17, 6, 0, 0, tzinfo=timezone.utc)


class DecisionCompareTests(unittest.TestCase):
    def test_compare_payload_from_decision_hub_demo_trace(self) -> None:
        compare_payload = build_compare_artifact(now=NOW)

        self.assertIn("decision_id", compare_payload)
        self.assertIn("trace_ref", compare_payload)
        self.assertIn("decision_relevant_state_summary", compare_payload)
        self.assertIn("candidate_decisions", compare_payload)
        self.assertIn("score_breakdown", compare_payload)
        self.assertIn("selected_recommendation", compare_payload)
        self.assertIn("why_not_the_others", compare_payload)
        self.assertTrue(compare_payload["candidate_decisions"])
        self.assertEqual(
            compare_payload["selected_recommendation"]["candidate_id"],
            "cand.delegate_to_executor",
        )

    def test_compare_reads_standard_payload_and_renders_text(self) -> None:
        payload = load_compare_payload(FIXTURE_PATH)

        output = render_compare_text(payload, show_execution=True)

        self.assertIn("DECISION COMPARISON", output)
        self.assertIn("decision_id:", output)
        self.assertIn("trace_ref:", output)
        self.assertIn("cand.delegate_to_executor", output)
        self.assertIn("WHY NOT OTHERS", output)
        self.assertIn("EXECUTION BOUNDARY", output)

    def test_compare_json_output_is_stable(self) -> None:
        payload = load_compare_payload(FIXTURE_PATH)

        rendered = json.loads(render_compare_json(payload))

        self.assertEqual(rendered["decision_id"], payload["decision_id"])
        self.assertEqual(rendered["trace_ref"], payload["trace_ref"])
        self.assertEqual(
            rendered["selected_recommendation"]["candidate_id"],
            payload["selected_recommendation"]["candidate_id"],
        )

    def test_veto_candidate_is_explained(self) -> None:
        payload = load_compare_payload(FIXTURE_PATH)

        output = render_compare_text(payload)

        self.assertIn("Vetoed by no_commitment_endangerment", output)
        self.assertIn("Vetoed by no_silent_blocker_ignore", output)
        self.assertIn("guided score: 0.43 (blocked by veto)", output)

    def test_tradeoff_rule_candidate_is_explained(self) -> None:
        payload = load_compare_payload(FIXTURE_PATH)

        output = render_compare_text(payload)

        self.assertIn(
            "The selected candidate was preferred by trade-off rule prefer_delegate_when_executor_available_and_time_pressure",
            output,
        )

    def test_missing_optional_fields_do_not_crash(self) -> None:
        payload = normalize_compare_payload(
            {
                "decision_id": "decision.demo",
                "trace_ref": "trace.demo",
                "decision_relevant_state_summary": {
                    "now": "2026-04-17T06:00:00+00:00",
                    "available_window_minutes": 15,
                    "active_commitments": [],
                    "open_work_items": [],
                    "active_conflicts": [],
                    "executor_available": False,
                },
                "candidate_decisions": [
                    {
                        "candidate_id": "cand.a",
                        "title": "Candidate A",
                        "action": "handle_now",
                        "intent": "Take the action now.",
                        "enabled_reason": "baseline",
                        "key_constraints": [],
                        "expected_effect": {},
                        "is_selected": True,
                    },
                    {
                        "candidate_id": "cand.b",
                        "title": "Candidate B",
                        "action": "ignore_temporarily",
                        "intent": "Do nothing for now.",
                        "enabled_reason": "baseline",
                        "key_constraints": [],
                        "expected_effect": {},
                        "is_selected": False,
                    },
                ],
                "score_breakdown": {
                    "candidates": {
                        "cand.a": {
                            "score_total": 0.9,
                            "dimensions": [],
                            "constraints": [],
                            "vetoes": [],
                            "tradeoff_rules": [],
                        },
                        "cand.b": {
                            "score_total": 0.2,
                            "dimensions": [],
                            "constraints": [],
                            "vetoes": [],
                            "tradeoff_rules": [],
                        },
                    }
                },
                "selected_recommendation": {
                    "candidate_id": "cand.a",
                    "action": "handle_now",
                    "title": "Candidate A",
                    "selection_reason": "selected from compare payload",
                    "decision_basis": [],
                },
                "why_not_the_others": [{"candidate_id": "cand.b", "title": "Candidate B", "reasons": []}],
                "expected_outcome_or_risk": {},
            }
        )

        output = render_compare_text(payload)

        self.assertIn("Candidate A", output)
        self.assertIn("Candidate B", output)
        self.assertIn("No explicit compare evidence was recorded", output)

    def test_compare_does_not_depend_on_live_runtime_registry(self) -> None:
        TRACE_REGISTRY.clear()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "decision",
                    "compare",
                    "--input",
                    str(FIXTURE_PATH),
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn("DECISION COMPARISON", stdout.getvalue())

    def test_show_execution_is_optional(self) -> None:
        payload = load_compare_payload(FIXTURE_PATH)

        without_execution = render_compare_text(payload, show_execution=False)
        with_execution = render_compare_text(payload, show_execution=True)

        self.assertNotIn("EXECUTION BOUNDARY", without_execution)
        self.assertIn("EXECUTION BOUNDARY", with_execution)

    def test_why_not_is_not_invented_by_renderer(self) -> None:
        payload = normalize_compare_payload(
            {
                "decision_id": "decision.demo",
                "trace_ref": "trace.demo",
                "decision_relevant_state_summary": {
                    "now": "2026-04-17T06:00:00+00:00",
                    "available_window_minutes": 15,
                    "active_commitments": [],
                    "open_work_items": [],
                    "active_conflicts": [],
                    "executor_available": False,
                },
                "candidate_decisions": [
                    {
                        "candidate_id": "cand.selected",
                        "title": "Selected Candidate",
                        "action": "handle_now",
                        "intent": "Act immediately.",
                        "enabled_reason": "baseline",
                        "key_constraints": [],
                        "expected_effect": {},
                        "is_selected": True,
                    },
                    {
                        "candidate_id": "cand.other",
                        "title": "Other Candidate",
                        "action": "ignore_temporarily",
                        "intent": "Wait.",
                        "enabled_reason": "baseline",
                        "key_constraints": [],
                        "expected_effect": {},
                        "is_selected": False,
                    },
                ],
                "score_breakdown": {
                    "candidates": {
                        "cand.selected": {
                            "score_total": 0.5,
                            "dimensions": [],
                            "constraints": [],
                            "vetoes": [],
                            "tradeoff_rules": [],
                        },
                        "cand.other": {
                            "score_total": 0.4,
                            "dimensions": [],
                            "constraints": [],
                            "vetoes": [],
                            "tradeoff_rules": [],
                        },
                    }
                },
                "selected_recommendation": {
                    "candidate_id": "cand.selected",
                    "action": "handle_now",
                    "title": "Selected Candidate",
                    "selection_reason": "selected from compare payload",
                    "decision_basis": [],
                },
                "why_not_the_others": [
                    {
                        "candidate_id": "cand.other",
                        "title": "Other Candidate",
                        "reasons": [],
                    }
                ],
                "expected_outcome_or_risk": {},
            }
        )

        output = render_compare_text(payload)

        self.assertIn("No explicit compare evidence was recorded for this candidate.", output)
        self.assertNotIn("Vetoed by", output)
        self.assertNotIn("trade-off rule", output)

    def test_decision_hub_demo_artifact_golden(self) -> None:
        payload = load_compare_payload(FIXTURE_PATH)

        self.assertEqual(payload["selected_recommendation"]["candidate_id"], "cand.delegate_to_executor")
        self.assertEqual(
            payload["execution_boundary"]["execution_path"],
            "SDEP -> Hermes/Codex",
        )
        self.assertTrue(
            any(
                item["candidate_id"] == "cand.quick_triage_then_defer"
                for item in payload["why_not_the_others"]
            )
        )

    def test_cli_json_output(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "decision",
                    "compare",
                    "--input",
                    str(FIXTURE_PATH),
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["decision_id"], load_compare_payload(FIXTURE_PATH)["decision_id"])


if __name__ == "__main__":
    unittest.main()
