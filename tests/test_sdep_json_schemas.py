from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from spice.protocols.sdep import (
    SDEP_AGENT_DESCRIBE_REQUEST,
    SDEP_AGENT_DESCRIBE_RESPONSE,
    SDEP_EXECUTE_REQUEST,
    SDEP_EXECUTE_RESPONSE,
    SDEP_PROTOCOL,
    SDEP_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "sdep" / "v0.1"


class SDEPJsonSchemaTests(unittest.TestCase):
    def test_schema_files_exist_and_parse(self) -> None:
        expected = {
            "common.schema.json",
            "execute.request.schema.json",
            "execute.response.schema.json",
            "agent.describe.request.schema.json",
            "agent.describe.response.schema.json",
        }

        found = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}

        self.assertEqual(found, expected)
        for name in expected:
            with self.subTest(schema=name):
                payload = _load_schema(name)
                self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertTrue(str(payload["$id"]).startswith("https://spice.dev/schemas/sdep/v0.1/"))

    def test_message_schema_constants_match_protocol_constants(self) -> None:
        cases = [
            ("execute.request.schema.json", SDEP_EXECUTE_REQUEST),
            ("execute.response.schema.json", SDEP_EXECUTE_RESPONSE),
            ("agent.describe.request.schema.json", SDEP_AGENT_DESCRIBE_REQUEST),
            ("agent.describe.response.schema.json", SDEP_AGENT_DESCRIBE_RESPONSE),
        ]

        for name, message_type in cases:
            with self.subTest(schema=name):
                schema = _load_schema(name)
                self.assertEqual(schema["properties"]["message_type"]["const"], message_type)
                self.assertIn("protocol", schema["required"])
                self.assertIn("sdep_version", schema["required"])
                self.assertIn("message_type", schema["required"])
                self.assertIn("message_id", schema["required"])
                self.assertIn("request_id", schema["required"])
                self.assertIn("timestamp", schema["required"])

    def test_common_schema_protocol_version_and_status_semantics(self) -> None:
        common = _load_schema("common.schema.json")
        defs = common["$defs"]

        self.assertEqual(defs["protocol"]["const"], SDEP_PROTOCOL)
        self.assertEqual(defs["sdep_version"]["const"], SDEP_VERSION)
        self.assertEqual(defs["response_status"]["enum"], ["success", "error"])
        self.assertEqual(
            defs["outcome_status"]["enum"],
            ["success", "failed", "partial", "abandoned", "unknown"],
        )

    def test_execute_request_schema_keeps_domain_payloads_open(self) -> None:
        schema = _load_schema("execute.request.schema.json")
        execution = schema["properties"]["execution"]
        properties = execution["properties"]

        self.assertEqual(properties["parameters"]["$ref"], "common.schema.json#/$defs/metadata")
        self.assertEqual(properties["input"]["$ref"], "common.schema.json#/$defs/metadata")
        self.assertEqual(properties["metadata"]["$ref"], "common.schema.json#/$defs/metadata")
        self.assertIn("success_criteria", execution["required"])
        self.assertIn("failure_policy", execution["required"])

    def test_execute_response_schema_separates_response_and_outcome_status(self) -> None:
        schema = _load_schema("execute.response.schema.json")
        outcome = schema["properties"]["outcome"]

        self.assertEqual(schema["properties"]["status"]["$ref"], "common.schema.json#/$defs/response_status")
        self.assertEqual(
            outcome["properties"]["status"]["$ref"],
            "common.schema.json#/$defs/outcome_status",
        )
        self.assertIn("error", schema["properties"])

    def test_schema_refs_resolve_to_local_files_and_defs(self) -> None:
        schemas = {path.name: _load_schema(path.name) for path in SCHEMA_DIR.glob("*.schema.json")}

        for name, schema in schemas.items():
            with self.subTest(schema=name):
                for ref in _iter_refs(schema):
                    file_name, pointer = ref.split("#", maxsplit=1)
                    target_schema_name = file_name or name
                    self.assertIn(target_schema_name, schemas)
                    _resolve_json_pointer(schemas[target_schema_name], pointer)


def _load_schema(name: str) -> dict[str, Any]:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"{name} must be a JSON object")
    return payload


def _iter_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            refs.append(ref)
        for item in value.values():
            refs.extend(_iter_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_iter_refs(item))
    return refs


def _resolve_json_pointer(schema: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise AssertionError(f"only local JSON pointers are supported in test, got {pointer!r}")
    current: Any = schema
    for raw_part in pointer.strip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise AssertionError(f"unresolved JSON pointer {pointer!r}")
        current = current[part]
    return current


if __name__ == "__main__":
    unittest.main()
