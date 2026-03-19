from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spice.entry import (
    SCHEMA_VERSION_V1,
    DomainSpec,
    DomainSpecValidationError,
    derive_domain_pack_class_name,
    derive_package_name,
    render_scaffold_files,
    write_scaffold,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_spec_payload() -> dict:
    return {
        "schema_version": SCHEMA_VERSION_V1,
        "domain": {
            "id": "incident_ops",
        },
        "vocabulary": {
            "observation_types": [
                "incident_ops.alert_opened",
                "incident_ops.metric_snapshot",
            ],
            "action_types": [
                "incident_ops.monitor",
                "incident_ops.escalate",
            ],
            "outcome_types": [
                "incident_ops.transition",
            ],
        },
        "state": {
            "entity_id": "incident_ops.current",
            "fields": [
                {"name": "status", "type": "string", "default": "open"},
                {"name": "severity", "type": "string", "default": "high"},
                {"name": "error_rate", "type": "number", "default": 0.0},
            ],
        },
        "actions": [
            {
                "id": "incident_ops.monitor",
                "description": "Observe and wait for updated signals.",
                "executor": {
                    "type": "mock",
                    "operation": "incident.monitor",
                    "parameters": {"severity": "high"},
                },
                "expected_outcome_type": "incident_ops.transition",
            },
            {
                "id": "incident_ops.escalate",
                "description": "Escalate to on-call human.",
                "executor": {
                    "type": "cli",
                    "operation": "incident.escalate",
                    "parameters": {"channel": "pager"},
                },
                "expected_outcome_type": "incident_ops.transition",
            },
        ],
        "decision": {
            "default_action": "incident_ops.monitor",
        },
        "demo": {
            "observations": [
                {
                    "type": "incident_ops.alert_opened",
                    "source": "incident_ops.demo",
                    "attributes": {
                        "status": "open",
                        "severity": "critical",
                        "error_rate": 0.12,
                    },
                }
            ],
        },
    }


class DomainSpecValidationTests(unittest.TestCase):
    def test_valid_spec_round_trip(self) -> None:
        spec = DomainSpec.from_dict(_valid_spec_payload())
        payload = spec.to_dict()

        self.assertEqual(payload["domain"]["id"], "incident_ops")
        self.assertEqual(payload["decision"]["default_action"], "incident_ops.monitor")
        self.assertEqual(
            payload["vocabulary"]["observation_types"][0],
            "incident_ops.alert_opened",
        )

    def test_action_types_must_match_actions(self) -> None:
        payload = _valid_spec_payload()
        payload["actions"] = [
            {
                "id": "incident_ops.monitor",
                "description": "Observe and wait for updated signals.",
                "executor": {
                    "type": "mock",
                    "operation": "incident.monitor",
                },
                "expected_outcome_type": "incident_ops.transition",
            }
        ]

        with self.assertRaises(DomainSpecValidationError):
            DomainSpec.from_dict(payload)

    def test_default_action_must_exist_in_vocabulary(self) -> None:
        payload = _valid_spec_payload()
        payload["decision"]["default_action"] = "incident_ops.invalid_action"

        with self.assertRaises(DomainSpecValidationError):
            DomainSpec.from_dict(payload)

    def test_invalid_executor_type_is_rejected(self) -> None:
        payload = _valid_spec_payload()
        payload["actions"][0]["executor"]["type"] = "unknown"

        with self.assertRaises(DomainSpecValidationError):
            DomainSpec.from_dict(payload)

    def test_missing_executor_operation_is_rejected(self) -> None:
        payload = _valid_spec_payload()
        payload["actions"][0]["executor"]["operation"] = ""

        with self.assertRaises(DomainSpecValidationError):
            DomainSpec.from_dict(payload)

    def test_non_object_executor_parameters_is_rejected(self) -> None:
        payload = _valid_spec_payload()
        payload["actions"][0]["executor"]["parameters"] = ["invalid"]

        with self.assertRaises(DomainSpecValidationError):
            DomainSpec.from_dict(payload)

    def test_expected_outcome_type_must_exist_in_vocabulary(self) -> None:
        payload = _valid_spec_payload()
        payload["actions"][0]["expected_outcome_type"] = "incident_ops.unknown"

        with self.assertRaises(DomainSpecValidationError):
            DomainSpec.from_dict(payload)

    def test_demo_observation_type_must_exist_in_vocabulary(self) -> None:
        payload = _valid_spec_payload()
        payload["demo"]["observations"][0]["type"] = "incident_ops.unknown"

        with self.assertRaises(DomainSpecValidationError):
            DomainSpec.from_dict(payload)

    def test_derived_names_from_domain_id(self) -> None:
        self.assertEqual(derive_package_name("incident.ops"), "incident_ops_domain")
        self.assertEqual(derive_domain_pack_class_name("incident.ops"), "IncidentOpsDomainPack")


class DomainScaffoldRendererTests(unittest.TestCase):
    def test_renderer_is_deterministic(self) -> None:
        spec = DomainSpec.from_dict(_valid_spec_payload())
        first = render_scaffold_files(spec)
        second = render_scaffold_files(spec)
        self.assertEqual(first, second)

    def test_scaffold_contains_derived_package_path(self) -> None:
        spec = DomainSpec.from_dict(_valid_spec_payload())
        files = render_scaffold_files(spec)

        self.assertIn("incident_ops_domain/domain_pack.py", files)
        self.assertIn("incident_ops_domain/reducers.py", files)
        self.assertIn("incident_ops_domain/vocabulary.py", files)

    def test_generated_scaffold_runs_demo(self) -> None:
        spec = DomainSpec.from_dict(_valid_spec_payload())

        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            project_dir = Path(tmp_dir) / "incident_ops_scaffold"
            write_scaffold(spec, project_dir)

            completed = subprocess.run(
                [sys.executable, "run_demo.py"],
                cwd=project_dir,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("SPICE demo cycle completed", completed.stdout)
            self.assertIn("domain=incident_ops", completed.stdout)
            self.assertIn("cycles=1", completed.stdout)
            self.assertIn('"decision_action": "incident_ops.monitor"', completed.stdout)
            self.assertIn('"planned_operation": "incident.monitor"', completed.stdout)
            self.assertIn('"execution_operation": "incident.monitor"', completed.stdout)


if __name__ == "__main__":
    unittest.main()
