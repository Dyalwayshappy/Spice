from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from spice.entry.cli import main as spice_cli_main


REPO_ROOT = Path(__file__).resolve().parents[1]


class QuickstartCLITests(unittest.TestCase):
    def test_spice_cli_entrypoint_function_runs_quickstart(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "quickstart_cli_entry"
            stdout_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer):
                exit_code = spice_cli_main(
                    ["quickstart", "--output", str(output_dir), "--no-run"]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "domain_spec.json").exists())

    def test_quickstart_no_run_generates_scaffold_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "quickstart_out"
            completed = self._run_quickstart(
                "--output",
                str(output_dir),
                "--no-run",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Run generated demo ... SKIPPED", completed.stdout)
            self.assertTrue((output_dir / "domain_spec.json").exists())
            self.assertTrue((output_dir / "run_demo.py").exists())
            self.assertTrue((output_dir / "artifacts" / "quickstart_summary.json").exists())

            summary = json.loads(
                (output_dir / "artifacts" / "quickstart_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(summary["schema_version"], "spice.quickstart.report.v1")
            self.assertFalse(bool(summary["demo_ran"]))
            self.assertIn("quickstart.service_ops", summary["domain_id"])

    def test_quickstart_run_reports_action_and_operation_mapping(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "quickstart_run"
            completed = self._run_quickstart("--output", str(output_dir))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("domain_action_id=", completed.stdout)
            self.assertIn("planned_execution_operation=", completed.stdout)
            self.assertIn("executed_operation=", completed.stdout)

            stdout_log = output_dir / "artifacts" / "run_demo.stdout.log"
            stderr_log = output_dir / "artifacts" / "run_demo.stderr.log"
            summary_path = output_dir / "artifacts" / "quickstart_summary.json"
            self.assertTrue(stdout_log.exists())
            self.assertTrue(stderr_log.exists())
            self.assertTrue(summary_path.exists())

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertTrue(bool(summary["demo_ran"]))
            self.assertEqual(summary["demo_exit_code"], 0)
            last_cycle = summary.get("last_cycle") or {}
            self.assertEqual(last_cycle.get("decision_action"), "quickstart.service_ops.monitor")
            self.assertEqual(last_cycle.get("planned_operation"), "service.monitor")
            self.assertEqual(last_cycle.get("execution_operation"), "service.monitor")

    def test_quickstart_requires_force_for_existing_output(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "quickstart_force"

            first = self._run_quickstart("--output", str(output_dir), "--no-run")
            self.assertEqual(first.returncode, 0, first.stderr)

            second = self._run_quickstart("--output", str(output_dir), "--no-run")
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("already exists", second.stderr)

            third = self._run_quickstart("--output", str(output_dir), "--no-run", "--force")
            self.assertEqual(third.returncode, 0, third.stderr)

    @staticmethod
    def _run_quickstart(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "spice.entry", "quickstart", *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
