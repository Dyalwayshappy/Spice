from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from spice.decision import (
    DecisionGuidanceSupport,
    describe_decision_guidance_support,
    explain_decision_guidance,
)
from spice.entry.cli import main as spice_cli_main


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DECISION_MD = REPO_ROOT / "examples" / "decision.md"
EXAMPLE_SUPPORT_JSON = REPO_ROOT / "examples" / "decision_support.json"


class DecisionGuidanceExplainTests(unittest.TestCase):
    def test_explain_report_exposes_runtime_boundary_and_support_contract(self) -> None:
        support = _example_support()

        report = explain_decision_guidance(EXAMPLE_DECISION_MD, support=support)

        self.assertEqual(
            report["artifact"]["artifact_id"],
            "decision.personal_work_coordination.flight_pr_conflict",
        )
        self.assertEqual(report["validation"]["status"], "partially_supported")
        self.assertIn("Primary Objective", report["sections"]["runtime_active"])
        self.assertIn("Decision Principles", report["sections"]["runtime_inactive"])
        self.assertIn("Version / Metadata", report["sections"]["parse_only"])
        self.assertIn("Risk Budget", report["sections"]["not_parsed_for_runtime_v1"])

        contract = report["support_contract"]
        self.assertTrue(contract["declared"])
        self.assertIn("flight_readiness", contract["score_dimensions"])
        self.assertIn(
            "no_action_that_endangers_departure",
            contract["constraint_ids"],
        )
        self.assertIn(
            "delegate_blocking_pr_under_time_pressure",
            contract["tradeoff_rule_ids"],
        )

        unsupported = report["unsupported"]
        self.assertEqual(unsupported["score_dimensions"], [])
        self.assertEqual(unsupported["constraint_ids"], [])
        self.assertIn(
            "flight_preservation_over_pr_progress",
            unsupported["tradeoff_rules"],
        )

        rules = {
            rule["id"]: rule for rule in report["active_guidance"]["tradeoff_rules"]
        }
        self.assertEqual(
            rules["delegate_blocking_pr_under_time_pressure"]["runtime_support"],
            "policy_or_candidate_result",
        )
        self.assertEqual(
            rules["flight_preservation_over_pr_progress"]["runtime_support"],
            "unsupported",
        )
        self.assertIn("when", report["executable_tradeoff_subset"])

    def test_support_contract_can_be_described_directly(self) -> None:
        contract = describe_decision_guidance_support(_example_support())

        self.assertTrue(contract["declared"])
        self.assertIn("pr_risk_reduction", contract["score_dimensions"])
        self.assertIn("no_silent_blocker_ignore", contract["constraint_ids"])

    def test_cli_decision_explain_json_reports_unsupported_semantics(self) -> None:
        stdout_buffer = io.StringIO()
        with redirect_stdout(stdout_buffer):
            exit_code = spice_cli_main(
                [
                    "decision",
                    "explain",
                    str(EXAMPLE_DECISION_MD),
                    "--support-json",
                    str(EXAMPLE_SUPPORT_JSON),
                    "--json",
                ]
            )

        self.assertEqual(exit_code, 0)
        report = json.loads(stdout_buffer.getvalue())
        self.assertEqual(report["validation"]["status"], "partially_supported")
        self.assertIn(
            "flight_preservation_over_pr_progress",
            report["unsupported"]["tradeoff_rules"],
        )
        self.assertEqual(
            report["selection_effect"]["primary_objective"],
            "Primary Objective influences max/min comparison only in v1.",
        )

    def test_quickstart_example_script_runs_validate_explain(self) -> None:
        completed = subprocess.run(
            [sys.executable, "examples/decision_quickstart.py"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("decision.md explain", completed.stdout)
        self.assertIn("validation_status: partially_supported", completed.stdout)
        self.assertIn("runtime-active sections:", completed.stdout)
        self.assertIn("unsupported runtime semantics:", completed.stdout)


def _example_support() -> DecisionGuidanceSupport:
    payload = json.loads(EXAMPLE_SUPPORT_JSON.read_text(encoding="utf-8"))
    return DecisionGuidanceSupport.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
