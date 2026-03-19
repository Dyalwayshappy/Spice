from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from spice.entry.cli import main as spice_cli_main
from spice.entry.spec import load_domain_spec


REPO_ROOT = Path(__file__).resolve().parents[1]
QUICKSTART_SPEC = REPO_ROOT / "spice" / "entry" / "assets" / "quickstart.domain_spec.json"


class InitDomainCLITests(unittest.TestCase):
    def test_spice_cli_entrypoint_function_runs_init_from_spec(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "init_cli_entry"
            stdout_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer):
                exit_code = spice_cli_main(
                    [
                        "init",
                        "domain",
                        "my_domain",
                        "--from-spec",
                        str(QUICKSTART_SPEC),
                        "--output",
                        str(output_dir),
                        "--no-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "domain_spec.json").exists())

    def test_interactive_happy_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "interactive_domain"
            user_input = "\n".join(
                [
                    "",   # domain id default
                    "",   # observation types default
                    "",   # action types default
                    "",   # outcome types default
                    "",   # executor type default
                    "",   # operation for action default
                    "",   # state entity id default
                    "status",
                    "",   # field type default string
                    "open",
                    "",   # finish fields
                    "",   # default action
                    "",   # demo observation type
                    "",   # demo source
                    "",   # additional demo attrs
                    "",   # confirm yes
                ]
            ) + "\n"
            completed = self._run_init(
                "my_domain",
                "--output",
                str(output_dir),
                "--no-run",
                input_text=user_input,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("State fields builder", completed.stdout)
            self.assertIn("Domain init complete.", completed.stdout)
            self.assertTrue((output_dir / "domain_spec.json").exists())
            self.assertTrue((output_dir / "run_demo.py").exists())

            generated_spec = load_domain_spec(output_dir / "domain_spec.json")
            self.assertEqual(generated_spec.domain.id, "my_domain")
            self.assertEqual(generated_spec.decision.default_action, "my_domain.monitor")

    def test_interactive_reprompt_on_invalid_executor_type(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "interactive_reprompt"
            user_input = "\n".join(
                [
                    "",          # domain id default
                    "",          # observation types default
                    "",          # action types default
                    "",          # outcome types default
                    "invalid",   # invalid executor type
                    "mock",      # corrected executor type
                    "",          # operation default
                    "",          # state entity default
                    "",          # no fields -> default inserted
                    "",          # default action
                    "",          # demo observation type
                    "",          # demo source
                    "",          # additional demo attrs
                    "",          # confirm yes
                ]
            ) + "\n"
            completed = self._run_init(
                "my_domain",
                "--output",
                str(output_dir),
                "--no-run",
                input_text=user_input,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Invalid value. Choose one of", completed.stdout)

    def test_from_spec_non_interactive(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "from_spec_domain"
            completed = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
                "--no-run",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(
                (output_dir / "artifacts" / "init_summary.json").read_text(encoding="utf-8")
            )
            self.assertFalse(bool(summary["interactive"]))
            self.assertEqual(summary["from_spec_path"], str(QUICKSTART_SPEC))

    def test_force_behavior(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "force_domain"
            first = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
                "--no-run",
            )
            self.assertEqual(first.returncode, 0, first.stderr)

            second = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
                "--no-run",
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("already exists", second.stderr)

            third = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
                "--no-run",
                "--force",
            )
            self.assertEqual(third.returncode, 0, third.stderr)

    def test_no_run_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "no_run_domain"
            completed = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
                "--no-run",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Run generated demo ... SKIPPED", completed.stdout)
            self.assertTrue((output_dir / "artifacts" / "run_demo.stdout.log").exists())
            self.assertTrue((output_dir / "artifacts" / "run_demo.stderr.log").exists())
            summary = json.loads(
                (output_dir / "artifacts" / "init_summary.json").read_text(encoding="utf-8")
            )
            self.assertFalse(bool(summary["demo_ran"]))

    def test_generated_project_runs_successfully_and_reports_mapping(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "run_domain"
            completed = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("domain_action_id=", completed.stdout)
            self.assertIn("planned_execution_operation=", completed.stdout)
            self.assertIn("executed_operation=", completed.stdout)

            summary = json.loads(
                (output_dir / "artifacts" / "init_summary.json").read_text(encoding="utf-8")
            )
            self.assertTrue(bool(summary["demo_ran"]))
            self.assertEqual(summary["demo_exit_code"], 0)
            last_cycle = summary.get("last_cycle") or {}
            self.assertEqual(last_cycle.get("decision_action"), "quickstart.service_ops.monitor")
            self.assertEqual(last_cycle.get("planned_operation"), "service.monitor")
            self.assertEqual(last_cycle.get("execution_operation"), "service.monitor")

    def test_deterministic_scaffold_for_same_spec(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_a = Path(tmp_dir) / "domain_a"
            output_b = Path(tmp_dir) / "domain_b"

            run_a = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_a),
                "--no-run",
            )
            run_b = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_b),
                "--no-run",
            )
            self.assertEqual(run_a.returncode, 0, run_a.stderr)
            self.assertEqual(run_b.returncode, 0, run_b.stderr)

            files_a = self._scaffold_contents(output_a)
            files_b = self._scaffold_contents(output_b)
            self.assertEqual(files_a, files_b)

    def test_with_llm_scaffold_includes_domain_llm_wiring(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "with_llm_domain"
            completed = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
                "--no-run",
                "--with-llm",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            domain_pack = (output_dir / "quickstart_service_ops_domain" / "domain_pack.py").read_text(
                encoding="utf-8"
            )
            self.assertIn("build_domain_llm_decision_policy", domain_pack)
            self.assertIn("DOMAIN_MODEL_ENV", domain_pack)
            readme = (output_dir / "README.md").read_text(encoding="utf-8")
            self.assertIn("Optional LLM Activation", readme)

    def test_without_with_llm_scaffold_remains_deterministic_template(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "without_llm_domain"
            completed = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
                "--no-run",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            domain_pack = (output_dir / "quickstart_service_ops_domain" / "domain_pack.py").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("build_domain_llm_decision_policy", domain_pack)
            self.assertIn("Generated deterministic DomainPack skeleton", domain_pack)

    def test_with_llm_generated_project_uses_model_override_for_decision(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "with_llm_run_domain"
            init_completed = self._run_init(
                "my_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
                "--no-run",
                "--with-llm",
            )
            self.assertEqual(init_completed.returncode, 0, init_completed.stderr)

            model_script = root / "domain_llm_model.py"
            model_script.write_text(self._domain_llm_model_script(), encoding="utf-8")
            model_cmd = f"{sys.executable} {model_script}"
            env = os.environ.copy()
            env["SPICE_DOMAIN_MODEL"] = model_cmd

            run_completed = subprocess.run(
                [sys.executable, "run_demo.py"],
                cwd=output_dir,
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )
            self.assertEqual(run_completed.returncode, 0, run_completed.stderr)
            self.assertIn('"decision_action": "quickstart.service_ops.notify"', run_completed.stdout)

    @staticmethod
    def _run_init(
        name: str,
        *args: str,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "spice.entry", "init", "domain", name, *args],
            cwd=REPO_ROOT,
            text=True,
            input=input_text,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def _scaffold_contents(root: Path) -> dict[str, str]:
        payload: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "artifacts" in path.parts:
                continue
            rel = str(path.relative_to(root))
            payload[rel] = path.read_text(encoding="utf-8")
        return payload

    @staticmethod
    def _domain_llm_model_script() -> str:
        return (
            "import json\n"
            "import sys\n"
            "prompt = sys.stdin.read()\n"
            "if 'Decision proposals' in prompt:\n"
            "    payload = [\n"
            "        {\n"
            "            'decision_type': 'quickstart.service_ops.llm',\n"
            "            'status': 'proposed',\n"
            "            'selected_action': 'quickstart.service_ops.notify',\n"
            "            'attributes': {'confidence': 0.7, 'urgency': 'high'},\n"
            "        }\n"
            "    ]\n"
            "elif 'simulation advice' in prompt:\n"
            "    payload = {\n"
            "        'score': 0.9,\n"
            "        'suggestion_text': 'LLM says notify ops now',\n"
            "        'confidence': 0.85,\n"
            "        'urgency': 'high',\n"
            "        'simulation_rationale': 'high_error_rate_signal',\n"
            "    }\n"
            "else:\n"
            "    payload = {'score': 0.0}\n"
            "print(json.dumps(payload))\n"
        )


if __name__ == "__main__":
    unittest.main()
