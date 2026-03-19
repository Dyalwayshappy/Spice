from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spice.entry.cli import main as spice_cli_main


REPO_ROOT = Path(__file__).resolve().parents[1]
QUICKSTART_SPEC = REPO_ROOT / "spice" / "entry" / "assets" / "quickstart.domain_spec.json"


class InitDomainAssistTests(unittest.TestCase):
    def test_assist_rejects_from_spec_combination(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            output_dir = Path(tmp_dir) / "assist_from_spec_forbidden"
            completed = self._run_init_assist(
                "assist_domain",
                "--from-spec",
                str(QUICKSTART_SPEC),
                "--output",
                str(output_dir),
                "--no-run",
                input_text="accept\n",
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("--assist cannot be combined with --from-spec", completed.stderr)

    def test_assist_happy_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "assist_happy"
            brief_file = root / "brief.txt"
            brief_file.write_text("Monitor alerts and decide actions.", encoding="utf-8")
            model_script = root / "model_valid.py"
            model_script.write_text(self._valid_model_script(), encoding="utf-8")
            model_cmd = f"{sys.executable} {model_script}"

            completed = self._run_init_assist(
                "assist_domain",
                "--assist-brief-file",
                str(brief_file),
                "--assist-model",
                model_cmd,
                "--output",
                str(output_dir),
                "--no-run",
                input_text="accept\n",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            assist_dir = output_dir / "artifacts" / "assist"
            self.assertTrue((output_dir / "domain_spec.json").exists())
            self.assertTrue((assist_dir / "brief.txt").exists())
            self.assertTrue((assist_dir / "llm_draft.raw.json").exists())
            self.assertTrue((assist_dir / "llm_draft.parsed.json").exists())
            self.assertTrue((assist_dir / "draft_domain_spec.json").exists())
            self.assertTrue((assist_dir / "accepted_domain_spec.json").exists())
            self.assertTrue((assist_dir / "assist_summary.json").exists())
            self.assertFalse((assist_dir / "validation_errors.log").exists())

            summary = json.loads((assist_dir / "assist_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["attempt_count"], 1)
            self.assertEqual(summary["review_decision"], "accepted")

    def test_assist_non_json_output_recovery(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "assist_wrapper"
            brief_file = root / "brief.txt"
            brief_file.write_text("Monitor alerts.", encoding="utf-8")
            model_script = root / "model_wrapped.py"
            model_script.write_text(self._wrapped_model_script(), encoding="utf-8")
            model_cmd = f"{sys.executable} {model_script}"

            completed = self._run_init_assist(
                "assist_domain",
                "--assist-brief-file",
                str(brief_file),
                "--assist-model",
                model_cmd,
                "--output",
                str(output_dir),
                "--no-run",
                input_text="accept\n",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(
                (output_dir / "artifacts" / "assist" / "assist_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(summary["attempt_count"], 1)
            self.assertEqual(summary["model_backend"], "subprocess")

    def test_assist_invalid_spec_retry_recovery(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "assist_retry"
            brief_file = root / "brief.txt"
            brief_file.write_text("Retry until valid spec.", encoding="utf-8")
            model_script = root / "model_retry.py"
            model_script.write_text(self._invalid_then_valid_model_script(), encoding="utf-8")
            model_cmd = f"{sys.executable} {model_script}"

            completed = self._run_init_assist(
                "assist_domain",
                "--assist-brief-file",
                str(brief_file),
                "--assist-model",
                model_cmd,
                "--assist-max-tries",
                "2",
                "--output",
                str(output_dir),
                "--no-run",
                input_text="accept\n",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            assist_dir = output_dir / "artifacts" / "assist"
            summary = json.loads((assist_dir / "assist_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["attempt_count"], 2)
            self.assertTrue((assist_dir / "validation_errors.log").exists())
            validation_log = (assist_dir / "validation_errors.log").read_text(encoding="utf-8")
            self.assertIn("domain spec validation error", validation_log)

    def test_assist_cancel_flow(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "assist_cancel"
            brief_file = root / "brief.txt"
            brief_file.write_text("Cancel this run.", encoding="utf-8")
            model_script = root / "model_valid.py"
            model_script.write_text(self._valid_model_script(), encoding="utf-8")
            model_cmd = f"{sys.executable} {model_script}"

            completed = self._run_init_assist(
                "assist_domain",
                "--assist-brief-file",
                str(brief_file),
                "--assist-model",
                model_cmd,
                "--output",
                str(output_dir),
                "--no-run",
                input_text="cancel\n",
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("cancelled", completed.stderr.lower())
            self.assertFalse((output_dir / "domain_spec.json").exists())

    def test_assist_edit_flow_inline_fallback(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "assist_edit"
            brief_file = root / "brief.txt"
            brief_file.write_text("Edit this draft before accepting.", encoding="utf-8")
            model_script = root / "model_valid.py"
            model_script.write_text(self._valid_model_script(), encoding="utf-8")
            model_cmd = f"{sys.executable} {model_script}"

            edited_spec = self._load_quickstart_spec()
            edited_spec["domain"]["id"] = "edited_domain"
            input_text = "edit\n" + json.dumps(edited_spec, indent=2) + "\nEND\naccept\n"
            completed = self._run_init_assist(
                "assist_domain",
                "--assist-brief-file",
                str(brief_file),
                "--assist-model",
                model_cmd,
                "--output",
                str(output_dir),
                "--no-run",
                input_text=input_text,
                env_overrides={"EDITOR": ""},
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Inline edit mode", completed.stdout)
            generated = json.loads((output_dir / "domain_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(generated["domain"]["id"], "edited_domain")

    def test_assist_deterministic_scaffold_from_accepted_spec(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            brief_file = root / "brief.txt"
            brief_file.write_text("Use accepted spec deterministically.", encoding="utf-8")
            model_script = root / "model_valid.py"
            model_script.write_text(self._valid_model_script(), encoding="utf-8")
            model_cmd = f"{sys.executable} {model_script}"
            output_a = root / "assist_a"
            output_b = root / "assist_b"

            run_a = self._run_init_assist(
                "assist_domain",
                "--assist-brief-file",
                str(brief_file),
                "--assist-model",
                model_cmd,
                "--output",
                str(output_a),
                "--no-run",
                input_text="accept\n",
            )
            run_b = self._run_init_assist(
                "assist_domain",
                "--assist-brief-file",
                str(brief_file),
                "--assist-model",
                model_cmd,
                "--output",
                str(output_b),
                "--no-run",
                input_text="accept\n",
            )

            self.assertEqual(run_a.returncode, 0, run_a.stderr)
            self.assertEqual(run_b.returncode, 0, run_b.stderr)
            self.assertEqual(self._scaffold_contents(output_a), self._scaffold_contents(output_b))

    def test_spice_cli_entrypoint_function_runs_assist(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "assist_cli_entry"
            brief_file = root / "brief.txt"
            brief_file.write_text("CLI function assist run.", encoding="utf-8")
            model_script = root / "model_valid.py"
            model_script.write_text(self._valid_model_script(), encoding="utf-8")
            model_cmd = f"{sys.executable} {model_script}"

            stdin = io.StringIO("accept\n")
            stdout = io.StringIO()
            stderr = io.StringIO()
            old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
            try:
                sys.stdin = stdin
                sys.stdout = stdout
                sys.stderr = stderr
                exit_code = spice_cli_main(
                    [
                        "init",
                        "domain",
                        "assist_domain",
                        "--assist",
                        "--assist-brief-file",
                        str(brief_file),
                        "--assist-model",
                        model_cmd,
                        "--output",
                        str(output_dir),
                        "--no-run",
                    ]
                )
            finally:
                sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "domain_spec.json").exists())

    @staticmethod
    def _run_init_assist(
        name: str,
        *args: str,
        input_text: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, "-m", "spice.entry", "init", "domain", name, "--assist", *args],
            cwd=REPO_ROOT,
            text=True,
            input=input_text,
            capture_output=True,
            check=False,
            env=env,
        )

    @staticmethod
    def _scaffold_contents(root: Path) -> dict[str, str]:
        payload: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "artifacts" in path.parts:
                continue
            payload[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
        return payload

    @staticmethod
    def _load_quickstart_spec() -> dict:
        return json.loads(QUICKSTART_SPEC.read_text(encoding="utf-8"))

    @classmethod
    def _valid_model_script(cls) -> str:
        spec_json = json.dumps(cls._load_quickstart_spec(), ensure_ascii=True)
        return (
            "import json\n"
            f"spec = json.loads({spec_json!r})\n"
            "payload = {\n"
            "  'draft_spec': spec,\n"
            "  'assumptions': ['valid model assumption'],\n"
            "  'warnings': [],\n"
            "  'missing_info': [],\n"
            "  'confidence': {'overall': 0.88},\n"
            "}\n"
            "print(json.dumps(payload))\n"
        )

    @classmethod
    def _wrapped_model_script(cls) -> str:
        spec_json = json.dumps(cls._load_quickstart_spec(), ensure_ascii=True)
        return (
            "import json\n"
            f"spec = json.loads({spec_json!r})\n"
            "payload = {\n"
            "  'draft_spec': spec,\n"
            "  'assumptions': ['wrapped output'],\n"
            "  'warnings': [],\n"
            "  'missing_info': [],\n"
            "  'confidence': {'overall': 0.67},\n"
            "}\n"
            "print('wrapper text before payload')\n"
            "print('```json')\n"
            "print(json.dumps(payload))\n"
            "print('```')\n"
        )

    @classmethod
    def _invalid_then_valid_model_script(cls) -> str:
        spec_json = json.dumps(cls._load_quickstart_spec(), ensure_ascii=True)
        return (
            "import json\n"
            "import sys\n"
            "prompt = sys.stdin.read()\n"
            "attempt = 1\n"
            "for line in prompt.splitlines():\n"
            "    if line.startswith('Attempt:'):\n"
            "        try:\n"
            "            attempt = int(line.split(':', 1)[1].strip())\n"
            "        except ValueError:\n"
            "            attempt = 1\n"
            "spec = json.loads("
            f"{spec_json!r}"
            ")\n"
            "if attempt == 1:\n"
            "    spec['schema_version'] = 'invalid.schema.version'\n"
            "payload = {\n"
            "  'draft_spec': spec,\n"
            "  'assumptions': ['retry script'],\n"
            "  'warnings': [],\n"
            "  'missing_info': [],\n"
            "  'confidence': {'overall': 0.72},\n"
            "}\n"
            "print(json.dumps(payload))\n"
        )


if __name__ == "__main__":
    unittest.main()
