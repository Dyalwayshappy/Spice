from __future__ import annotations

import unittest

from spice.llm.util import (
    extract_first_json_array,
    extract_first_json_object,
    strip_markdown_fences,
)


class JsonExtractTests(unittest.TestCase):
    def test_strip_markdown_fences(self) -> None:
        payload = "```json\n{\"a\": 1}\n```"
        stripped = strip_markdown_fences(payload)
        self.assertEqual(stripped, '{"a": 1}')

    def test_extract_first_json_object_from_fenced_text(self) -> None:
        raw = "```json\n{\"key\": \"value\", \"nested\": {\"x\": 1}}\n```"
        candidate = extract_first_json_object(raw)
        self.assertEqual(candidate, '{"key": "value", "nested": {"x": 1}}')

    def test_extract_first_json_object_with_leading_text(self) -> None:
        raw = "Model note:\nUse this payload\n\n{\"domain\": {\"id\": \"x\"}}\ntrailing"
        candidate = extract_first_json_object(raw)
        self.assertEqual(candidate, '{"domain": {"id": "x"}}')

    def test_extract_first_json_array(self) -> None:
        raw = "Result:\n[1, 2, {\"ok\": true}]"
        candidate = extract_first_json_array(raw)
        self.assertEqual(candidate, '[1, 2, {"ok": true}]')

    def test_no_json_returns_none(self) -> None:
        raw = "No JSON here."
        self.assertIsNone(extract_first_json_object(raw))
        self.assertIsNone(extract_first_json_array(raw))


if __name__ == "__main__":
    unittest.main()
