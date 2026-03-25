from __future__ import annotations

import contextlib
import json
import socketserver
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from spice.llm.core import (
    LLMAuthError,
    LLMClient,
    LLMModelConfig,
    LLMModelConfigOverride,
    LLMRateLimitError,
    LLMRequest,
    LLMResponseError,
    LLMRouteNotFoundError,
    LLMRouter,
    LLMTaskHook,
    LLMTransportError,
    ProviderRegistry,
)
from spice.llm.providers import (
    DeterministicLLMProvider,
    OpenAPICompatibleLLMProvider,
    SubprocessLLMProvider,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextlib.contextmanager
def _run_openapi_server(handler):
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            self.server.last_request_body = payload
            self.server.request_headers = dict(self.headers)
            self.server.request_path = self.path
            status, response_bytes = handler(payload, self.server)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response_bytes)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = _ThreadedHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class LLMCoreProviderTests(unittest.TestCase):
    def test_provider_registry_register_and_resolve(self) -> None:
        registry = ProviderRegistry.empty().register(DeterministicLLMProvider())
        provider = registry.resolve("deterministic")
        self.assertEqual(provider.provider_id, "deterministic")

    def test_provider_registry_missing_provider_raises(self) -> None:
        registry = ProviderRegistry.empty()
        with self.assertRaises(KeyError):
            registry.resolve("missing")

    def test_router_resolution_precedence(self) -> None:
        global_cfg = LLMModelConfig(provider_id="deterministic", model_id="global")
        hook_cfg = LLMModelConfig(provider_id="deterministic", model_id="hook")
        domain_cfg = LLMModelConfig(provider_id="deterministic", model_id="domain")
        router = LLMRouter(
            global_default=global_cfg,
            hook_defaults={LLMTaskHook.ASSIST_DRAFT: hook_cfg},
            domain_routes={(LLMTaskHook.ASSIST_DRAFT, "incident"): domain_cfg},
        )

        resolved_domain = router.resolve(LLMTaskHook.ASSIST_DRAFT, domain="incident")
        resolved_hook = router.resolve(LLMTaskHook.ASSIST_DRAFT, domain="other")
        resolved_global = router.resolve(LLMTaskHook.DECISION_PROPOSE, domain="other")

        self.assertEqual(resolved_domain.model_id, "domain")
        self.assertEqual(resolved_hook.model_id, "hook")
        self.assertEqual(resolved_global.model_id, "global")

    def test_router_override_applies(self) -> None:
        router = LLMRouter(
            hook_defaults={
                LLMTaskHook.ASSIST_DRAFT: LLMModelConfig(
                    provider_id="deterministic",
                    model_id="default",
                    temperature=0.0,
                    max_tokens=100,
                    timeout_sec=5.0,
                    response_format_hint="json_object",
                )
            }
        )
        override = LLMModelConfigOverride(
            provider_id="subprocess",
            model_id="python3 fake.py",
            timeout_sec=9.0,
        )
        resolved = router.resolve(
            LLMTaskHook.ASSIST_DRAFT,
            model_override=override,
        )
        self.assertEqual(resolved.provider_id, "subprocess")
        self.assertEqual(resolved.model_id, "python3 fake.py")
        self.assertEqual(resolved.timeout_sec, 9.0)
        self.assertEqual(resolved.response_format_hint, "json_object")

    def test_router_without_match_raises(self) -> None:
        router = LLMRouter()
        with self.assertRaises(LLMRouteNotFoundError):
            router.resolve(LLMTaskHook.ASSIST_DRAFT)

    def test_llm_client_dispatches_to_resolved_provider(self) -> None:
        provider = DeterministicLLMProvider(
            responses={LLMTaskHook.ASSIST_DRAFT: '{"ok": true}'}
        )
        registry = ProviderRegistry.empty().register(provider)
        router = LLMRouter(
            hook_defaults={
                LLMTaskHook.ASSIST_DRAFT: LLMModelConfig(
                    provider_id="deterministic",
                    model_id="deterministic.v1",
                )
            }
        )
        client = LLMClient(registry=registry, router=router)
        request = LLMRequest(
            task_hook=LLMTaskHook.ASSIST_DRAFT,
            input_text="prompt",
        )
        response = client.generate(request)
        self.assertEqual(response.provider_id, "deterministic")
        self.assertEqual(json.loads(response.output_text), {"ok": True})

    def test_deterministic_provider_returns_assist_contract(self) -> None:
        provider = DeterministicLLMProvider()
        request = LLMRequest(
            task_hook=LLMTaskHook.ASSIST_DRAFT,
            domain="my_domain",
            input_text="prompt",
        )
        response = provider.generate(
            request,
            LLMModelConfig(provider_id="deterministic", model_id="deterministic.v1"),
        )
        payload = json.loads(response.output_text)
        self.assertIn("draft_spec", payload)
        self.assertIn("confidence", payload)
        self.assertEqual(response.provider_id, "deterministic")

    def test_subprocess_provider_invocation_success(self) -> None:
        provider = SubprocessLLMProvider()
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            script_path = Path(tmp_dir) / "echo_model.py"
            script_path.write_text(
                "import json, sys\n"
                "prompt = sys.stdin.read()\n"
                "print(json.dumps({'prompt': prompt.strip()}))\n",
                encoding="utf-8",
            )
            response = provider.generate(
                LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="hello-world"),
                LLMModelConfig(
                    provider_id="subprocess",
                    model_id=f"{sys.executable} {script_path}",
                ),
            )
            payload = json.loads(response.output_text)
            self.assertEqual(payload["prompt"], "hello-world")

    def test_subprocess_provider_rate_limit_error_normalization(self) -> None:
        provider = SubprocessLLMProvider()
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            script_path = Path(tmp_dir) / "rate_limit.py"
            script_path.write_text(
                "import sys\n"
                "sys.stderr.write('rate limit exceeded')\n"
                "raise SystemExit(1)\n",
                encoding="utf-8",
            )
            with self.assertRaises(LLMRateLimitError):
                provider.generate(
                    LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="x"),
                    LLMModelConfig(
                        provider_id="subprocess",
                        model_id=f"{sys.executable} {script_path}",
                    ),
                )

    def test_subprocess_provider_auth_error_normalization(self) -> None:
        provider = SubprocessLLMProvider()
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            script_path = Path(tmp_dir) / "auth_error.py"
            script_path.write_text(
                "import sys\n"
                "sys.stderr.write('unauthorized api key')\n"
                "raise SystemExit(1)\n",
                encoding="utf-8",
            )
            with self.assertRaises(LLMAuthError):
                provider.generate(
                    LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="x"),
                    LLMModelConfig(
                        provider_id="subprocess",
                        model_id=f"{sys.executable} {script_path}",
                    ),
                )

    def test_subprocess_provider_empty_stdout_raises_response_error(self) -> None:
        provider = SubprocessLLMProvider()
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp_dir:
            script_path = Path(tmp_dir) / "empty_output.py"
            script_path.write_text("pass\n", encoding="utf-8")
            with self.assertRaises(LLMResponseError):
                provider.generate(
                    LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="x"),
                    LLMModelConfig(
                        provider_id="subprocess",
                        model_id=f"{sys.executable} {script_path}",
                    ),
                )

    def test_openapi_provider_success_response(self) -> None:
        provider = OpenAPICompatibleLLMProvider()

        def handler(payload: bytes, server: _ThreadedHTTPServer) -> tuple[int, bytes]:
            server.request_json = json.loads(payload.decode("utf-8"))
            response_payload = {
                "choices": [
                    {
                        "message": {"content": "relay text"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"input_chars": 11, "output_chars": 9},
                "api_key": "super-secret",
            }
            return 200, json.dumps(response_payload, ensure_ascii=True).encode("utf-8")

        with _run_openapi_server(handler) as server:
            base_url = f"http://{server.server_address[0]}:{server.server_address[1]}"
            model = LLMModelConfig(
                provider_id="openapi_compatible",
                model_id="relay-model",
                base_url=base_url,
                api_key="super-secret",
            )
            response = provider.generate(
                LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="prompt"),
                model,
            )

            self.assertEqual(response.output_text, "relay text")
            self.assertEqual(
                server.request_headers.get("Authorization"), "Bearer super-secret"
            )
            self.assertEqual(server.request_path, "/chat/completions")
            self.assertEqual(server.request_json["model"], "relay-model")
            self.assertEqual(
                response.raw_payload["endpoint"], base_url.rstrip("/") + "/chat/completions"
            )
            self.assertNotIn("super-secret", json.dumps(response.raw_payload["response"]))

    def test_openapi_provider_validation_errors(self) -> None:
        provider = OpenAPICompatibleLLMProvider()
        request = LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="prompt")

        with self.assertRaises(LLMTransportError):
            provider.generate(
                request,
                LLMModelConfig(
                    provider_id="openapi_compatible",
                    model_id="relay-model",
                    base_url="   ",
                    api_key="super-secret",
                ),
            )

        with self.assertRaises(LLMAuthError):
            provider.generate(
                request,
                LLMModelConfig(
                    provider_id="openapi_compatible",
                    model_id="relay-model",
                    base_url="http://example.com",
                    api_key=None,
                ),
            )


if __name__ == "__main__":
    unittest.main()
