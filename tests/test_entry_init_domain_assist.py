from __future__ import annotations

import contextlib
import io
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from spice.entry.cli import main as spice_cli_main


REPO_ROOT = Path(__file__).resolve().parents[1]
QUICKSTART_SPEC = REPO_ROOT / "spice" / "entry" / "assets" / "quickstart.domain_spec.json"


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextlib.contextmanager
def _run_relay_server(response_fn):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            self.server.last_body = body
            self.server.last_headers = dict(self.headers)
            self.server.request_path = self.path
            status, payload_bytes = response_fn(body, self.server)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload_bytes)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = _ThreadedHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


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

    def test_assist_relay_missing_base_url(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "relay_missing_base_url"
            brief_file = root / "brief.txt"
            brief_file.write_text("Need base url.", encoding="utf-8")

            completed = self._run_init_assist(
                "assist_domain",
                "--assist-provider",
                "openapi_compatible",
                "--assist-api-key",
                "relay-secret",
                "--assist-brief-file",
                str(brief_file),
                "--output",
                str(output_dir),
                "--no-run",
                input_text="accept\n",
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("--assist-base-url", completed.stderr)
            self.assertIn("openapi_compatible", completed.stderr)

    def test_assist_relay_model_conflict(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "relay_invalid_combo"
            brief_file = root / "brief.txt"
            brief_file.write_text("Reject invalid relay combination.", encoding="utf-8")

            completed = self._run_init_assist(
                "assist_domain",
                "--assist-provider",
                "subprocess",
                "--assist-base-url",
                "https://relay.invalid",
                "--assist-api-key",
                "relay-secret",
                "--assist-model",
                "echo relay",
                "--assist-brief-file",
                str(brief_file),
                "--output",
                str(output_dir),
                "--no-run",
                input_text="accept\n",
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("subprocess assist provider does not accept", completed.stderr)
            self.assertNotIn("relay-secret", completed.stderr)

    def test_assist_relay_redacts_api_key(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "relay_redaction"
            brief_file = root / "brief.txt"
            brief_file.write_text("Relay redaction.", encoding="utf-8")

            def response_fn(payload: bytes, server: _ThreadedHTTPServer) -> tuple[int, bytes]:
                request_obj = json.loads(payload.decode("utf-8"))
                server.request_json = request_obj
                response_payload = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "draft_spec": self._load_quickstart_spec(),
                                        "assumptions": ["relay redaction"],
                                        "warnings": [],
                                        "missing_info": [],
                                        "confidence": {"overall": 0.91},
                                    }
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"input_chars": 1, "output_chars": 12},
                    "api_key": "relay-secret",
                }
                return 200, json.dumps(response_payload, ensure_ascii=True).encode("utf-8")

            with _run_relay_server(response_fn) as server:
                base_url = (
                    f"http://{server.server_address[0]}:{server.server_address[1]}"
                )
                completed = self._run_init_assist(
                    "assist_domain",
                    "--assist-provider",
                    "openapi_compatible",
                    "--assist-base-url",
                    base_url,
                    "--assist-api-key",
                    "relay-secret",
                    "--assist-model",
                    "relay-model",
                    "--assist-brief-file",
                    str(brief_file),
                    "--output",
                    str(output_dir),
                    "--no-run",
                    input_text="accept\n",
                )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn("relay-secret", completed.stdout)
            self.assertNotIn("relay-secret", completed.stderr)
            assist_dir = output_dir / "artifacts" / "assist"
            self._assert_secret_not_in_artifacts(assist_dir, "relay-secret")

    def test_assist_relay_normalizes_near_miss_domain_spec_shapes(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "relay_normalized"
            brief_file = root / "brief.txt"
            brief_file.write_text("Monitor alerts and decide actions.", encoding="utf-8")

            def response_fn(payload: bytes, server: _ThreadedHTTPServer) -> tuple[int, bytes]:
                server.request_json = json.loads(payload.decode("utf-8"))
                response_payload = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "draft_spec": {
                                            "schema_version": "spice.domainspec.v1",
                                            "domain": {"id": "relay_demo"},
                                            "vocabulary": {
                                                "observation_types": [
                                                    "alert_received",
                                                    "context_enriched",
                                                ],
                                                "action_types": [
                                                    "acknowledge_alert",
                                                    "notify_oncall",
                                                ],
                                                "outcome_types": [
                                                    "alert_acknowledged",
                                                    "oncall_notified",
                                                ],
                                            },
                                            "state": {
                                                "entity_id": "alert_id",
                                                "fields": {
                                                    "alert_id": {"type": "string", "required": True},
                                                    "created_at": {"type": "timestamp"},
                                                    "severity": {"type": "string"},
                                                },
                                            },
                                            "actions": [
                                                {
                                                    "type": "acknowledge_alert",
                                                    "executor": "system",
                                                    "expected_outcome_type": "alert_acknowledged",
                                                },
                                                {
                                                    "type": "notify_oncall",
                                                    "executor": "system",
                                                    "expected_outcome_type": "oncall_notified",
                                                },
                                            ],
                                            "decision": {"default_action": "acknowledge_alert"},
                                            "demo": {
                                                "observations": [
                                                    {
                                                        "type": "alert_received",
                                                        "alert_id": "A-1001",
                                                        "severity": "critical",
                                                    },
                                                    {
                                                        "type": "context_enriched",
                                                        "alert_id": "A-1001",
                                                        "created_at": "2025-01-01T00:00:00Z",
                                                    },
                                                ]
                                            },
                                        },
                                        "assumptions": ["normalized relay response"],
                                        "warnings": [],
                                        "missing_info": [],
                                        "confidence": {"overall": 0.83},
                                    }
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ]
                }
                return 200, json.dumps(response_payload, ensure_ascii=True).encode("utf-8")

            with _run_relay_server(response_fn) as server:
                base_url = f"http://{server.server_address[0]}:{server.server_address[1]}"
                completed = self._run_init_assist(
                    "assist_domain",
                    "--assist-provider",
                    "openapi_compatible",
                    "--assist-base-url",
                    base_url,
                    "--assist-api-key",
                    "relay-secret",
                    "--assist-model",
                    "gpt-5.4",
                    "--assist-brief-file",
                    str(brief_file),
                    "--output",
                    str(output_dir),
                    "--no-run",
                    input_text="accept\n",
                )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            generated = json.loads((output_dir / "domain_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(generated["schema_version"], "spice.domain_spec.v1")
            self.assertIsInstance(generated["state"]["fields"], list)
            self.assertEqual(generated["state"]["fields"][1]["type"], "string")
            self.assertEqual(generated["actions"][0]["executor"]["type"], "mock")
            self.assertEqual(generated["demo"]["observations"][0]["source"], "relay_demo.demo")
            self.assertIn("attributes", generated["demo"]["observations"][0])

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

    def _assert_secret_not_in_artifacts(self, assist_dir: Path, secret: str) -> None:
        for path in assist_dir.rglob("*"):
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            self.assertNotIn(secret, content, f"secret leaked in {path}")

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
