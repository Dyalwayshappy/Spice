from __future__ import annotations

import unittest

from spice.protocols.sdep import (
    SDEPDescribeRequest,
    SDEPDescribeResponse,
    SDEPExecuteRequest,
    SDEPExecuteResponse,
)


_MISSING = object()


class SDEPProtocolTests(unittest.TestCase):
    def test_execute_request_from_dict_enforces_canonical_envelope(self) -> None:
        cases = [
            ("protocol", "not-sdep", "protocol"),
            ("message_type", "execute.response", "message_type"),
            ("sdep_version", "0.9", "sdep_version"),
            ("message_id", "", "message_id"),
            ("message_id", _MISSING, "message_id"),
            ("sender.role", "", "sender.role"),
            ("sender.role", _MISSING, "sender.role"),
            ("sender.role", "executor", "sender.role"),
        ]
        for field_name, value, error_token in cases:
            with self.subTest(field=field_name, value=value):
                payload = self._base_request_payload()
                if "." in field_name:
                    parent_field, child_field = field_name.split(".", maxsplit=1)
                    parent = payload[parent_field]
                    if value is _MISSING:
                        parent.pop(child_field, None)
                    else:
                        parent[child_field] = value
                else:
                    if value is _MISSING:
                        payload.pop(field_name, None)
                    else:
                        payload[field_name] = value

                with self.assertRaisesRegex(ValueError, error_token):
                    SDEPExecuteRequest.from_dict(payload)

    def test_execute_response_from_dict_enforces_canonical_envelope(self) -> None:
        cases = [
            ("protocol", "not-sdep", "protocol"),
            ("message_type", "execute.request", "message_type"),
            ("sdep_version", "0.9", "sdep_version"),
            ("message_id", "", "message_id"),
            ("message_id", _MISSING, "message_id"),
            ("responder.role", "", "responder.role"),
            ("responder.role", _MISSING, "responder.role"),
            ("responder.role", "brain", "responder.role"),
            ("responder.implementation", "", "responder.implementation"),
            ("responder.implementation", _MISSING, "responder.implementation"),
            ("outcome.outcome_type", "custom_outcome", "outcome_type"),
        ]
        for field_name, value, error_token in cases:
            with self.subTest(field=field_name, value=value):
                payload = self._base_response_payload()
                if "." in field_name:
                    parent_field, child_field = field_name.split(".", maxsplit=1)
                    parent = payload[parent_field]
                    if value is _MISSING:
                        parent.pop(child_field, None)
                    else:
                        parent[child_field] = value
                else:
                    if value is _MISSING:
                        payload.pop(field_name, None)
                    else:
                        payload[field_name] = value

                with self.assertRaisesRegex(ValueError, error_token):
                    SDEPExecuteResponse.from_dict(payload)

    def test_execute_response_allows_namespaced_outcome_type(self) -> None:
        payload = self._base_response_payload()
        payload["outcome"]["outcome_type"] = "incident.custom_outcome"

        response = SDEPExecuteResponse.from_dict(payload)

        self.assertEqual(response.outcome.outcome_type, "incident.custom_outcome")

    def test_execute_request_from_dict_ignores_legacy_intent_field(self) -> None:
        payload = self._base_request_payload()
        payload["intent"] = {
            "id": "legacy-intent-1",
            "intent_type": "legacy.demo",
            "target": {"kind": "service", "id": "checkout-api"},
        }

        request = SDEPExecuteRequest.from_dict(payload)
        wire_payload = request.to_dict()

        self.assertIn("execution", wire_payload)
        self.assertNotIn("intent", wire_payload)

    def test_describe_request_from_dict_enforces_envelope_and_sender_role(self) -> None:
        cases = [
            ("protocol", "not-sdep", "protocol"),
            ("message_type", "execute.request", "message_type"),
            ("sdep_version", "0.9", "sdep_version"),
            ("message_id", "", "message_id"),
            ("message_id", _MISSING, "message_id"),
            ("sender.role", "", "sender.role"),
            ("sender.role", "executor", "sender.role"),
            ("query.include_capabilities", "yes", "include_capabilities"),
        ]
        for field_name, value, error_token in cases:
            with self.subTest(field=field_name, value=value):
                payload = self._base_describe_request_payload()
                _set_payload_field(payload, field_name, value)
                with self.assertRaisesRegex(ValueError, error_token):
                    SDEPDescribeRequest.from_dict(payload)

    def test_describe_response_from_dict_enforces_required_capability_fields(self) -> None:
        cases = [
            ("protocol", "not-sdep", "protocol"),
            ("message_type", "execute.response", "message_type"),
            ("sdep_version", "0.9", "sdep_version"),
            ("message_id", "", "message_id"),
            ("responder.role", "brain", "responder.role"),
            ("responder.implementation", "", "responder.implementation"),
            ("description.protocol_support", _MISSING, "protocol_support"),
            ("description.capabilities", _MISSING, "capabilities"),
            ("description.capabilities", {}, "capabilities"),
            ("description.protocol_support.versions", [], "versions"),
            ("description.capabilities.0.action_type", "", "action_type"),
            ("description.capabilities.0.target_kinds", [], "target_kinds"),
            ("description.capabilities.0.mode_support", [], "mode_support"),
            ("description.capabilities.0.side_effect_class", "dangerous", "side_effect_class"),
            ("description.capabilities.0.outcome_type", "custom_outcome", "outcome_type"),
            ("description.capabilities.0.semantic_inputs", {"id": "x"}, "semantic_inputs"),
            ("description.capabilities.0.semantic_inputs.0", "", "semantic_inputs"),
            ("description.capabilities.0.input_expectation", "", "input_expectation"),
            ("description.capabilities.0.parameter_expectation", "", "parameter_expectation"),
        ]
        for field_name, value, error_token in cases:
            with self.subTest(field=field_name, value=value):
                payload = self._base_describe_response_payload()
                _set_payload_field(payload, field_name, value)
                with self.assertRaisesRegex(ValueError, error_token):
                    SDEPDescribeResponse.from_dict(payload)

    def test_describe_response_round_trip(self) -> None:
        payload = self._base_describe_response_payload()
        response = SDEPDescribeResponse.from_dict(payload)
        wire_payload = response.to_dict()

        self.assertEqual(wire_payload["message_type"], "agent.describe.response")
        self.assertEqual(
            wire_payload["description"]["protocol_support"]["protocol"],
            "sdep",
        )
        self.assertEqual(
            wire_payload["description"]["capabilities"][0]["action_type"],
            "demo.echo",
        )
        self.assertEqual(
            wire_payload["description"]["capabilities"][0]["side_effect_class"],
            "read_only",
        )
        self.assertEqual(
            wire_payload["description"]["capabilities"][0]["outcome_type"],
            "observation",
        )

    @staticmethod
    def _base_request_payload() -> dict:
        return {
            "protocol": "sdep",
            "sdep_version": "0.1",
            "message_type": "execute.request",
            "message_id": "sdep-msg-test-request",
            "request_id": "sdep-req-test-request",
            "timestamp": "2026-03-12T12:00:00+00:00",
            "sender": {
                "id": "spice.runtime",
                "name": "Spice Runtime",
                "version": "0.1",
                "vendor": "Spice",
                "implementation": "spice-runtime",
                "role": "brain",
            },
            "execution": {
                "action_type": "demo.echo",
                "target": {"kind": "service", "id": "checkout-api"},
                "parameters": {},
                "input": {},
                "constraints": [],
                "success_criteria": [],
                "failure_policy": {},
                "mode": "sync",
                "dry_run": False,
                "metadata": {},
            },
            "metadata": {},
        }

    @staticmethod
    def _base_response_payload() -> dict:
        return {
            "protocol": "sdep",
            "sdep_version": "0.1",
            "message_type": "execute.response",
            "message_id": "sdep-msg-test-response",
            "request_id": "sdep-req-test-response",
            "timestamp": "2026-03-12T12:00:01+00:00",
            "responder": {
                "id": "agent.echo",
                "name": "Echo Agent",
                "version": "0.1",
                "vendor": "ExampleVendor",
                "implementation": "echo-agent",
                "role": "executor",
            },
            "status": "success",
            "outcome": {
                "execution_id": "exec-test-response",
                "status": "success",
                "output": {"ok": True},
                "artifacts": [],
                "metrics": {},
                "metadata": {},
            },
            "metadata": {},
        }

    @staticmethod
    def _base_describe_request_payload() -> dict:
        return {
            "protocol": "sdep",
            "sdep_version": "0.1",
            "message_type": "agent.describe.request",
            "message_id": "sdep-msg-test-describe-request",
            "request_id": "sdep-req-test-describe-request",
            "timestamp": "2026-03-12T12:00:00+00:00",
            "sender": {
                "id": "spice.runtime",
                "name": "Spice Runtime",
                "version": "0.1",
                "vendor": "Spice",
                "implementation": "spice-runtime",
                "role": "brain",
            },
            "query": {
                "include_capabilities": True,
                "action_types": [],
                "metadata": {},
            },
            "metadata": {},
        }

    @staticmethod
    def _base_describe_response_payload() -> dict:
        return {
            "protocol": "sdep",
            "sdep_version": "0.1",
            "message_type": "agent.describe.response",
            "message_id": "sdep-msg-test-describe-response",
            "request_id": "sdep-req-test-describe-response",
            "timestamp": "2026-03-12T12:00:01+00:00",
            "responder": {
                "id": "agent.echo",
                "name": "Echo Agent",
                "version": "0.1",
                "vendor": "ExampleVendor",
                "implementation": "echo-agent",
                "role": "executor",
            },
            "status": "success",
            "description": {
                "protocol_support": {
                    "protocol": "sdep",
                    "versions": ["0.1"],
                    "metadata": {},
                },
                "capabilities": [
                    {
                        "action_type": "demo.echo",
                        "target_kinds": ["service"],
                        "mode_support": ["sync"],
                        "dry_run_supported": True,
                        "side_effect_class": "read_only",
                        "outcome_type": "observation",
                        "semantic_inputs": ["target_ref"],
                        "input_expectation": "object payload",
                        "parameter_expectation": "object payload",
                        "metadata": {},
                    }
                ],
                "metadata": {},
            },
            "metadata": {},
        }


def _set_payload_field(payload: dict, field_name: str, value: object) -> None:
    if "." not in field_name:
        if value is _MISSING:
            payload.pop(field_name, None)
        else:
            payload[field_name] = value
        return

    parts = field_name.split(".")
    current: object = payload
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]

    leaf = parts[-1]
    if isinstance(current, list):
        idx = int(leaf)
        if value is _MISSING:
            current.pop(idx)
        else:
            current[idx] = value
    else:
        if value is _MISSING:
            current.pop(leaf, None)
        else:
            current[leaf] = value


if __name__ == "__main__":
    unittest.main()
