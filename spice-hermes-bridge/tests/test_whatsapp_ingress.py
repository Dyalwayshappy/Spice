from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from spice_hermes_bridge.adapters.whatsapp import (
    WhatsAppInboundMessage,
    observe_whatsapp_message,
)
from spice_hermes_bridge.cli import main
from spice_hermes_bridge.extraction.proposals import CommitmentProposal


class WhatsAppIngressTest(unittest.TestCase):
    def test_declared_commitment_builds_valid_observation(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="我明天下午3点有投资人会议，预计需要2小时",
                chat_id="whatsapp.self",
                sender_id="user.self",
                message_id="wa.demo.1",
                received_at="2026-04-16T02:00:00+00:00",
            )
        )

        self.assertEqual(result.status, "observation_built")
        self.assertEqual(result.result_type, "observation")
        self.assertTrue(result.valid)
        self.assertIsNotNone(result.observation)
        assert result.observation is not None
        self.assertEqual(result.observation.observation_type, "commitment_declared")
        self.assertEqual(
            result.observation.attributes["start_time"],
            "2026-04-17T15:00:00+08:00",
        )
        self.assertEqual(result.observation.attributes["duration_minutes"], 120)
        self.assertEqual(
            result.observation.attributes["end_time"],
            "2026-04-17T17:00:00+08:00",
        )
        self.assertEqual(
            result.observation.provenance["adapter"],
            "whatsapp_perception.v2",
        )
        self.assertEqual(result.observation.provenance["extractor_mode"], "deterministic")
        self.assertFalse(result.observation.provenance["fallback"])
        self.assertEqual(result.observation.provenance["time_anchor_source"], "received_at")

    def test_short_valid_commitment_can_default_duration_with_warning(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="明天下午3点开会",
                received_at="2026-04-16T02:00:00+00:00",
            )
        )

        self.assertEqual(result.status, "observation_built")
        assert result.observation is not None
        self.assertEqual(result.observation.attributes["duration_minutes"], 60)
        self.assertEqual(result.observation.provenance["duration_source"], "default_safe")
        self.assertIn(
            "duration_defaulted_to_60_minutes_for_bounded_commitment",
            result.warnings,
        )
        self.assertNotIn("priority_hint", result.observation.attributes)

    def test_ambiguous_commitment_goes_to_pending_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            pending_path = Path(tempdir) / "pending_confirmations.json"
            result = observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="明天下午有个会",
                    received_at="2026-04-16T02:00:00+00:00",
                ),
                pending_store_path=pending_path,
            )

            self.assertEqual(result.result_type, "pending_confirmation")
            self.assertIsNone(result.observation)
            self.assertIsNotNone(result.pending_confirmation)
            assert result.pending_confirmation is not None
            self.assertIn("start_time", result.pending_confirmation.missing_fields)
            self.assertTrue(pending_path.exists())
            stored = json.loads(pending_path.read_text())
            self.assertEqual(stored[0]["pending_id"], result.pending_confirmation.pending_id)
            self.assertEqual(stored[0]["status"], "pending")
            self.assertEqual(stored[0]["followups"], [])
            self.assertIsNone(stored[0]["resolved_at"])

    def test_non_commitment_message_is_ignored(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(text="你好 Hermes，测试一下")
        )

        self.assertEqual(result.status, "ignored")
        self.assertEqual(result.result_type, "ignored")
        self.assertEqual(result.reason, "no_supported_commitment_pattern")
        self.assertIsNone(result.observation)

    def test_near_miss_false_positive_is_ignored(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(text="明天下午会议这个词怎么翻译")
        )
        second = observe_whatsapp_message(
            WhatsAppInboundMessage(text="我们明天下午再讨论会议这个词的翻译")
        )

        self.assertEqual(result.result_type, "ignored")
        self.assertIsNone(result.observation)
        self.assertEqual(second.result_type, "ignored")
        self.assertIsNone(second.observation)

    def test_short_valid_chinese_and_numeric_times(self) -> None:
        first = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="明天下午三点开会",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            persist_pending=False,
        )
        second = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="后天 15:30 面试",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            persist_pending=False,
        )

        self.assertEqual(first.result_type, "observation")
        assert first.observation is not None
        self.assertEqual(
            first.observation.attributes["start_time"],
            "2026-04-17T15:00:00+08:00",
        )
        self.assertEqual(second.result_type, "observation")
        assert second.observation is not None
        self.assertEqual(
            second.observation.attributes["start_time"],
            "2026-04-18T15:30:00+08:00",
        )

    def test_risky_default_duration_goes_to_pending(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="明天下午3点出发",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            persist_pending=False,
        )

        self.assertEqual(result.result_type, "pending_confirmation")
        assert result.pending_confirmation is not None
        self.assertIn("duration_minutes", result.pending_confirmation.missing_fields)

    def test_relative_time_anchor_uses_message_timestamp_timezone(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="明天下午3点开会",
                received_at="2026-04-16T23:30:00-04:00",
            ),
            default_timezone="America/New_York",
            persist_pending=False,
        )

        self.assertEqual(result.result_type, "observation")
        assert result.observation is not None
        self.assertEqual(
            result.observation.attributes["start_time"],
            "2026-04-17T15:00:00-04:00",
        )

    def test_naive_received_at_is_not_used_as_relative_time_anchor(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="明天下午3点开会",
                received_at="2026-04-16T02:00:00",
            ),
            persist_pending=False,
        )

        self.assertEqual(result.result_type, "observation")
        self.assertIn("naive_received_at_ignored_used_system_now", result.warnings)
        assert result.observation is not None
        self.assertEqual(result.observation.provenance["time_anchor_source"], "system_now")

    def test_time_boundary_cases_are_explicit(self) -> None:
        crossing_midnight = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="今晚11点开会，两个小时",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            persist_pending=False,
        )
        flight_without_duration = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="明天凌晨1点的航班",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            persist_pending=False,
        )
        prep = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="后天9点会议，提前30分钟准备",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            persist_pending=False,
        )

        self.assertEqual(crossing_midnight.result_type, "observation")
        assert crossing_midnight.observation is not None
        self.assertEqual(
            crossing_midnight.observation.attributes["end_time"],
            "2026-04-17T01:00:00+08:00",
        )
        self.assertEqual(flight_without_duration.result_type, "pending_confirmation")
        assert flight_without_duration.pending_confirmation is not None
        self.assertIn(
            "duration_minutes",
            flight_without_duration.pending_confirmation.missing_fields,
        )
        self.assertEqual(prep.result_type, "observation")
        assert prep.observation is not None
        self.assertEqual(prep.observation.attributes["duration_minutes"], 60)
        self.assertEqual(
            prep.observation.attributes["prep_start_time"],
            "2026-04-18T08:30:00+08:00",
        )
        self.assertIn(
            "duration_defaulted_to_60_minutes_for_bounded_commitment",
            prep.warnings,
        )

    def test_command_and_hermes_response_are_ignored(self) -> None:
        command = observe_whatsapp_message(WhatsAppInboundMessage(text="/sethome"))
        hermes = observe_whatsapp_message(
            WhatsAppInboundMessage(text="⚕ *Hermes Agent*\n已连接")
        )

        self.assertEqual(command.reason, "command_message")
        self.assertEqual(hermes.reason, "hermes_response")

    def test_cli_whatsapp_observe_from_json_payload(self) -> None:
        payload_path = Path(__file__).parents[1] / "examples" / "whatsapp_message.json"
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = main(["whatsapp-observe", "--input-json", str(payload_path), "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["result_type"], "observation")
        self.assertEqual(payload["status"], "observation_built")
        self.assertTrue(payload["valid"])
        self.assertIn("warnings", payload)
        self.assertIn("pending_confirmation", payload)
        self.assertEqual(
            payload["observation"]["observation_type"],
            "commitment_declared",
        )

    def test_llm_assisted_mode_outputs_observation_through_bridge_builder(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="我明天下午3点有投资人会议，预计需要2小时",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            extractor="llm_assisted",
            llm_provider=_StaticProvider(
                {
                    "summary": "投资人会议",
                    "start_time": "2026-04-17T15:00:00+08:00",
                    "end_time": "2026-04-17T17:00:00+08:00",
                    "constraint_hints": ["do_not_be_late"],
                    "meta": {
                        "confidence": 0.88,
                        "uncertain_fields": [],
                        "assumptions": [],
                        "needs_confirmation": False,
                    },
                }
            ),
            persist_pending=False,
        )

        self.assertEqual(result.result_type, "observation")
        assert result.observation is not None
        self.assertRegex(result.observation.observation_id or "", r"^obs_[0-9a-f]{32}$")
        self.assertEqual(result.observation.provenance["extractor"], "llm_assisted")
        self.assertEqual(result.observation.provenance["extractor_mode"], "llm_assisted")
        self.assertFalse(result.observation.provenance["fallback"])
        self.assertEqual(result.observation.attributes["duration_minutes"], 120)

    def test_llm_assisted_mode_outputs_pending_when_uncertain(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="明天下午有个会",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            extractor="llm_assisted",
            llm_provider=_StaticProvider(
                {
                    "summary": "会议",
                    "start_time": None,
                    "end_time": None,
                    "meta": {
                        "confidence": 0.41,
                        "uncertain_fields": ["start_time"],
                        "assumptions": ["afternoon_not_precise"],
                        "needs_confirmation": True,
                    },
                }
            ),
            persist_pending=False,
        )

        self.assertEqual(result.result_type, "pending_confirmation")
        self.assertIsNone(result.observation)
        assert result.pending_confirmation is not None
        self.assertIn("start_time", result.pending_confirmation.missing_fields)

    def test_llm_assisted_time_must_be_supported_by_original_text(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="明天下午有个会",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            extractor="llm_assisted",
            llm_provider=_StaticProvider(
                {
                    "summary": "会议",
                    "start_time": "2026-04-17T15:00:00+08:00",
                    "end_time": "2026-04-17T16:00:00+08:00",
                    "meta": {
                        "confidence": 0.9,
                        "uncertain_fields": [],
                        "assumptions": [],
                        "needs_confirmation": False,
                    },
                }
            ),
            persist_pending=False,
        )

        self.assertEqual(result.result_type, "pending_confirmation")
        self.assertEqual(result.reason, "proposal_start_time_not_supported_by_text")
        self.assertIsNone(result.observation)
        assert result.pending_confirmation is not None
        self.assertIn("start_time", result.pending_confirmation.missing_fields)

    def test_llm_failure_falls_back_to_deterministic(self) -> None:
        result = observe_whatsapp_message(
            WhatsAppInboundMessage(
                text="明天下午3点开会",
                received_at="2026-04-16T02:00:00+00:00",
            ),
            extractor="llm_assisted",
            llm_provider=_FailingProvider(),
            persist_pending=False,
        )

        self.assertEqual(result.result_type, "observation")
        self.assertTrue(any("llm_assisted_failed" in warning for warning in result.warnings))
        assert result.observation is not None
        self.assertEqual(result.observation.provenance["extractor"], "deterministic")
        self.assertEqual(result.observation.provenance["extractor_mode"], "llm_assisted")
        self.assertTrue(result.observation.provenance["fallback"])
        self.assertIn("llm_assisted_failed", result.observation.provenance["fallback_reason"])

    def test_pending_followup_resolves_to_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            pending_path = Path(tempdir) / "pending_confirmations.json"
            pending = observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="明天下午有个会",
                    chat_id="whatsapp.self",
                    sender_id="user.self",
                    received_at="2026-04-16T02:00:00+00:00",
                ),
                pending_store_path=pending_path,
            )

            self.assertEqual(pending.result_type, "pending_confirmation")
            resolved = observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="下午3点，1小时",
                    chat_id="whatsapp.self",
                    sender_id="user.self",
                    message_id="wa.followup.1",
                    received_at="2026-04-16T02:03:00+00:00",
                ),
                pending_store_path=pending_path,
                resolve_pending=True,
            )

            self.assertEqual(resolved.result_type, "observation")
            assert resolved.observation is not None
            self.assertEqual(
                resolved.observation.attributes["start_time"],
                "2026-04-17T15:00:00+08:00",
            )
            self.assertEqual(resolved.observation.attributes["duration_minutes"], 60)
            self.assertEqual(
                resolved.observation.provenance["pending_id"],
                pending.pending_confirmation.pending_id,  # type: ignore[union-attr]
            )
            stored = json.loads(pending_path.read_text())
            self.assertEqual(stored[0]["status"], "resolved")
            self.assertIsNotNone(stored[0]["resolved_at"])
            self.assertEqual(len(stored[0]["followups"]), 1)

    def test_pending_followup_stays_pending_when_still_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            pending_path = Path(tempdir) / "pending_confirmations.json"
            observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="明天下午有个会",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:00:00+00:00",
                ),
                pending_store_path=pending_path,
            )

            result = observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="应该还是下午",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:03:00+00:00",
                ),
                pending_store_path=pending_path,
                resolve_pending=True,
            )

            self.assertEqual(result.result_type, "pending_confirmation")
            assert result.pending_confirmation is not None
            self.assertEqual(result.pending_confirmation.status, "pending")
            self.assertIn("start_time", result.pending_confirmation.missing_fields)
            stored = json.loads(pending_path.read_text())
            self.assertEqual(stored[0]["status"], "pending")
            self.assertEqual(len(stored[0]["followups"]), 1)

    def test_resolved_pending_does_not_emit_observation_again_for_same_followup(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            pending_path = Path(tempdir) / "pending_confirmations.json"
            observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="明天下午有个会",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:00:00+00:00",
                ),
                pending_store_path=pending_path,
            )
            first = observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="下午3点，1小时",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:03:00+00:00",
                ),
                pending_store_path=pending_path,
                resolve_pending=True,
            )
            second = observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="下午3点，1小时",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:04:00+00:00",
                ),
                pending_store_path=pending_path,
                resolve_pending=True,
            )

            self.assertEqual(first.result_type, "observation")
            self.assertEqual(second.result_type, "ignored")
            self.assertEqual(second.reason, "pending_already_resolved_for_followup")

    def test_resolve_pending_without_active_pending_uses_normal_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            pending_path = Path(tempdir) / "pending_confirmations.json"
            result = observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="明天下午3点开会",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:00:00+00:00",
                ),
                pending_store_path=pending_path,
                resolve_pending=True,
            )

            self.assertEqual(result.result_type, "observation")
            assert result.observation is not None
            self.assertNotIn("pending_id", result.observation.provenance)

    def test_llm_assisted_pending_resolution_uses_same_bridge_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            pending_path = Path(tempdir) / "pending_confirmations.json"
            observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="明天下午有个会",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:00:00+00:00",
                ),
                pending_store_path=pending_path,
            )

            result = observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="下午3点，1小时",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:03:00+00:00",
                ),
                extractor="llm_assisted",
                llm_provider=_StaticProvider(
                    {
                        "summary": "会议",
                        "start_time": "2026-04-17T15:00:00+08:00",
                        "end_time": "2026-04-17T16:00:00+08:00",
                        "meta": {
                            "confidence": 0.9,
                            "uncertain_fields": [],
                            "assumptions": [],
                            "needs_confirmation": False,
                        },
                    }
                ),
                pending_store_path=pending_path,
                resolve_pending=True,
            )

            self.assertEqual(result.result_type, "observation")
            assert result.observation is not None
            self.assertEqual(result.observation.provenance["extractor"], "llm_assisted")
            self.assertTrue(result.observation.provenance["pending_resolution"])

    def test_llm_failure_fallback_still_resolves_pending_when_deterministic_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            pending_path = Path(tempdir) / "pending_confirmations.json"
            observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="明天下午有个会",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:00:00+00:00",
                ),
                pending_store_path=pending_path,
            )

            result = observe_whatsapp_message(
                WhatsAppInboundMessage(
                    text="下午3点，1小时",
                    chat_id="whatsapp.self",
                    received_at="2026-04-16T02:03:00+00:00",
                ),
                extractor="llm_assisted",
                llm_provider=_FailingProvider(),
                pending_store_path=pending_path,
                resolve_pending=True,
            )

            self.assertEqual(result.result_type, "observation")
            assert result.observation is not None
            self.assertEqual(result.observation.provenance["extractor"], "deterministic")
            self.assertTrue(result.observation.provenance["fallback"])

    def test_cli_resolve_pending_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            pending_path = Path(tempdir) / "pending_confirmations.json"
            first_stdout = io.StringIO()
            with redirect_stdout(first_stdout):
                first_exit = main(
                    [
                        "whatsapp-observe",
                        "--text",
                        "明天下午有个会",
                        "--chat-id",
                        "whatsapp.self",
                        "--received-at",
                        "2026-04-16T02:00:00+00:00",
                        "--pending-store",
                        str(pending_path),
                        "--json",
                    ]
                )
            second_stdout = io.StringIO()
            with redirect_stdout(second_stdout):
                second_exit = main(
                    [
                        "whatsapp-observe",
                        "--text",
                        "下午3点，1小时",
                        "--chat-id",
                        "whatsapp.self",
                        "--received-at",
                        "2026-04-16T02:03:00+00:00",
                        "--pending-store",
                        str(pending_path),
                        "--resolve-pending",
                        "--json",
                    ]
                )

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            first_payload = json.loads(first_stdout.getvalue())
            second_payload = json.loads(second_stdout.getvalue())
            self.assertEqual(first_payload["result_type"], "pending_confirmation")
            self.assertEqual(second_payload["result_type"], "observation")
            self.assertIn("warnings", second_payload)
            self.assertIn("issues", second_payload)

class _StaticProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def propose_commitment(
        self,
        *,
        text: str,
        reference_time: datetime | None,
        default_timezone: str,
    ) -> CommitmentProposal | None:
        return CommitmentProposal.from_payload(self.payload, extractor="llm_assisted")


class _FailingProvider:
    def propose_commitment(
        self,
        *,
        text: str,
        reference_time: datetime | None,
        default_timezone: str,
    ) -> CommitmentProposal | None:
        raise RuntimeError("simulated provider failure")


if __name__ == "__main__":
    unittest.main()
