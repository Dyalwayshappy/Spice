from __future__ import annotations

import unittest

from spice_hermes_bridge.integrations.hermes_relay import (
    HermesInboundRelay,
    extract_message_list,
    normalize_hermes_whatsapp_message,
)


class HermesRelayTest(unittest.TestCase):
    def test_extract_message_list_accepts_bridge_array(self) -> None:
        self.assertEqual(extract_message_list([{"body": "hello"}]), [{"body": "hello"}])
        self.assertEqual(extract_message_list({"messages": [{"body": "hello"}]}), [{"body": "hello"}])
        self.assertEqual(extract_message_list({"unexpected": []}), [])

    def test_normalize_hermes_whatsapp_message_shape(self) -> None:
        normalized = normalize_hermes_whatsapp_message(
            {
                "chatId": "12345@s.whatsapp.net",
                "senderId": "me@s.whatsapp.net",
                "body": "明天下午3点有个会",
                "timestamp": 1776271363,
                "messageId": "msg-1",
            }
        )

        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized.chat_id, "12345@s.whatsapp.net")
        self.assertEqual(normalized.sender, "me@s.whatsapp.net")
        self.assertEqual(normalized.text, "明天下午3点有个会")
        self.assertEqual(normalized.message_id, "msg-1")
        self.assertIn("+00:00", normalized.timestamp)
        payload = normalized.to_webhook_payload()
        self.assertEqual(payload["chat_id"], "12345@s.whatsapp.net")
        self.assertEqual(payload["sender"], "me@s.whatsapp.net")
        self.assertEqual(payload["received_at"], normalized.timestamp)

    def test_normalize_skips_empty_text_or_missing_chat(self) -> None:
        self.assertIsNone(normalize_hermes_whatsapp_message({"chatId": "chat", "body": ""}))
        self.assertIsNone(normalize_hermes_whatsapp_message({"body": "hello"}))

    def test_poll_once_forwards_messages_to_webhook(self) -> None:
        posts: list[tuple[str, dict]] = []

        def fake_get(url: str, timeout: int):
            self.assertEqual(url, "http://127.0.0.1:3000/messages")
            return [
                {
                    "chatId": "chat-1",
                    "senderId": "sender-1",
                    "body": "今天下午3点有个会",
                    "timestamp": "2026-04-17T14:00:00+08:00",
                    "messageId": "msg-1",
                }
            ]

        def fake_post(url: str, payload: dict, timeout: int):
            posts.append((url, payload))
            return {"status": 200, "body": {"ok": True}}

        relay = HermesInboundRelay(
            webhook_url="https://public.example/whatsapp/webhook",
            http_get_json=fake_get,
            http_post_json=fake_post,
        )

        result = relay.poll_once()

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.forwarded, 1)
        self.assertEqual(posts[0][0], "https://public.example/whatsapp/webhook")
        self.assertEqual(posts[0][1]["chat_id"], "chat-1")
        self.assertEqual(posts[0][1]["text"], "今天下午3点有个会")

    def test_poll_once_dedups_repeated_message_ids_in_process(self) -> None:
        posts: list[dict] = []
        message = {
            "chatId": "chat-1",
            "senderId": "sender-1",
            "body": "今天下午3点有个会",
            "timestamp": "2026-04-17T14:00:00+08:00",
            "messageId": "msg-1",
        }

        def fake_get(url: str, timeout: int):
            return [message]

        def fake_post(url: str, payload: dict, timeout: int):
            posts.append(payload)
            return {"status": 200}

        relay = HermesInboundRelay(
            webhook_url="https://public.example/whatsapp/webhook",
            http_get_json=fake_get,
            http_post_json=fake_post,
        )

        first = relay.poll_once()
        second = relay.poll_once()

        self.assertEqual(first.forwarded, 1)
        self.assertEqual(second.forwarded, 0)
        self.assertEqual(second.skipped, 1)
        self.assertEqual(len(posts), 1)


if __name__ == "__main__":
    unittest.main()
