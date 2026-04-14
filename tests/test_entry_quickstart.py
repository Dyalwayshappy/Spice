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
                    ["quickstart", "--core-only", "--output", str(output_dir), "--no-run"]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "domain_spec.json").exists())

    def test_quickstart_no_run_generates_scaffold_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "quickstart_out"
            completed = self._run_quickstart(
                "--core-only",
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
            completed = self._run_quickstart("--core-only", "--output", str(output_dir))

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

            first = self._run_quickstart(
                "--core-only",
                "--output",
                str(output_dir),
                "--no-run",
            )
            self.assertEqual(first.returncode, 0, first.stderr)

            second = self._run_quickstart(
                "--core-only",
                "--output",
                str(output_dir),
                "--no-run",
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("already exists", second.stderr)

            third = self._run_quickstart(
                "--core-only",
                "--output",
                str(output_dir),
                "--no-run",
                "--force",
            )
            self.assertEqual(third.returncode, 0, third.stderr)

    def test_default_quickstart_generates_decision_profile_and_llm_runtime(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            core_dir = root / "quickstart"
            llm_dir = root / "quickstart_llm"
            profile_path = root / ".spice" / "decision" / "decision.md"
            support_path = root / ".spice" / "decision" / "support" / "default_support.json"

            completed = self._run_quickstart(
                "--output",
                str(core_dir),
                "--llm-output",
                str(llm_dir),
                "--decision-profile",
                str(profile_path),
                "--support-output",
                str(support_path),
                "--no-run",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Quickstart complete.", completed.stdout)
            self.assertIn("Use OpenRouter with the example runtime", completed.stdout)
            self.assertIn("Real projects define their own DomainSpec", completed.stdout)
            self.assertTrue((core_dir / "domain_spec.json").exists())
            self.assertTrue((llm_dir / "run_demo.py").exists())
            self.assertTrue(profile_path.exists())
            self.assertTrue(support_path.exists())

            summary_path = core_dir / "artifacts" / "integrated_quickstart_summary.json"
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(
                summary["schema_version"],
                "spice.quickstart.integrated_report.v1",
            )
            self.assertEqual(summary["decision_profile"]["profile_path"], str(profile_path))
            self.assertEqual(summary["llm_runtime"]["output_dir"], str(llm_dir))

    def test_default_quickstart_requires_force_before_partial_write(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            core_dir = root / "quickstart"
            llm_dir = root / "quickstart_llm"
            profile_path = root / ".spice" / "decision" / "decision.md"
            support_path = root / ".spice" / "decision" / "support" / "default_support.json"
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.write_text("# existing\n", encoding="utf-8")

            completed = self._run_quickstart(
                "--output",
                str(core_dir),
                "--llm-output",
                str(llm_dir),
                "--decision-profile",
                str(profile_path),
                "--support-output",
                str(support_path),
                "--no-run",
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Use --force", completed.stderr)
            self.assertFalse(core_dir.exists())
            self.assertFalse(llm_dir.exists())

    def test_spice_console_script_is_declared(self) -> None:
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[project.scripts]", pyproject)
        self.assertIn('spice = "spice.entry.cli:main"', pyproject)

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
