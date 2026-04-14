from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

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
    ProviderRegistry,
)
from spice.llm.providers import (
    DeterministicLLMProvider,
    OpenRouterLLMProvider,
    SubprocessLLMProvider,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


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

    def test_openrouter_provider_invocation_success(self) -> None:
        provider = OpenRouterLLMProvider()
        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "id": "chatcmpl-test",
                        "model": "anthropic/claude-3.5-sonnet",
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {"role": "assistant", "content": '{"ok": true}'},
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 7,
                            "completion_tokens": 3,
                            "total_tokens": 10,
                        },
                    }
                ).encode("utf-8")

        def fake_urlopen(request: object, timeout: float | None = None) -> FakeResponse:
            captured["url"] = getattr(request, "full_url")
            captured["timeout"] = timeout
            captured["headers"] = {
                key.lower(): value
                for key, value in getattr(request, "header_items")()
            }
            captured["payload"] = json.loads(getattr(request, "data").decode("utf-8"))
            return FakeResponse()

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "SPICE_OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
                "SPICE_OPENROUTER_SITE_URL": "https://github.com/Dyalwayshappy/Spice",
                "SPICE_OPENROUTER_APP_NAME": "Spice",
            },
        ), patch("spice.llm.providers.openrouter.urllib_request.urlopen", fake_urlopen):
            response = provider.generate(
                LLMRequest(
                    task_hook=LLMTaskHook.SIMULATION_ADVISE,
                    system_text="system prompt",
                    input_text="user prompt",
                ),
                LLMModelConfig(
                    provider_id="openrouter",
                    model_id="anthropic/claude-3.5-sonnet",
                    temperature=0.2,
                    max_tokens=128,
                    timeout_sec=9.0,
                    response_format_hint="json_object",
                ),
            )

        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(captured["timeout"], 9.0)
        headers = captured["headers"]
        self.assertIsInstance(headers, dict)
        self.assertEqual(headers.get("authorization"), "Bearer test-key")
        self.assertEqual(headers.get("http-referer"), "https://github.com/Dyalwayshappy/Spice")
        self.assertEqual(headers.get("x-openrouter-title"), "Spice")
        payload = captured["payload"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["model"], "anthropic/claude-3.5-sonnet")
        self.assertEqual(
            payload["messages"],
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
        )
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["max_tokens"], 128)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(response.provider_id, "openrouter")
        self.assertEqual(response.model_id, "anthropic/claude-3.5-sonnet")
        self.assertEqual(response.output_text, '{"ok": true}')
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.request_id, "chatcmpl-test")

    def test_openrouter_provider_requires_api_key(self) -> None:
        provider = OpenRouterLLMProvider()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMAuthError):
                provider.generate(
                    LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="x"),
                    LLMModelConfig(
                        provider_id="openrouter",
                        model_id="anthropic/claude-3.5-sonnet",
                    ),
                )

    def test_openrouter_provider_requires_model_id(self) -> None:
        provider = OpenRouterLLMProvider()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            with self.assertRaises(LLMResponseError):
                provider.generate(
                    LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="x"),
                    LLMModelConfig(provider_id="openrouter", model_id=""),
                )

    def test_openrouter_provider_rate_limit_error_normalization(self) -> None:
        provider = OpenRouterLLMProvider()

        def fake_urlopen(request: object, timeout: float | None = None) -> object:
            raise urllib.error.HTTPError(
                url="https://openrouter.ai/api/v1/chat/completions",
                code=429,
                msg="Too Many Requests",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"rate limited"}'),
            )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "spice.llm.providers.openrouter.urllib_request.urlopen",
            fake_urlopen,
        ):
            with self.assertRaises(LLMRateLimitError):
                provider.generate(
                    LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="x"),
                    LLMModelConfig(
                        provider_id="openrouter",
                        model_id="anthropic/claude-3.5-sonnet",
                    ),
                )

    def test_openrouter_provider_malformed_response_raises_response_error(self) -> None:
        provider = OpenRouterLLMProvider()

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"choices":[]}'

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "spice.llm.providers.openrouter.urllib_request.urlopen",
            lambda request, timeout=None: FakeResponse(),
        ):
            with self.assertRaises(LLMResponseError):
                provider.generate(
                    LLMRequest(task_hook=LLMTaskHook.ASSIST_DRAFT, input_text="x"),
                    LLMModelConfig(
                        provider_id="openrouter",
                        model_id="anthropic/claude-3.5-sonnet",
                    ),
                )


if __name__ == "__main__":
    unittest.main()
