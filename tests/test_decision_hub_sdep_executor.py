from __future__ import annotations

import unittest
from typing import Any

from examples.decision_hub_demo.execution_adapter import ExecutionRequest
from examples.decision_hub_demo.sdep_executor import (
    SDEPBackedExecutor,
    SDEP_DELEGATE_ACTION_TYPE,
    execution_intent_to_sdep_request,
    execution_request_to_intent,
    sdep_response_to_execution_outcome,
)


class _StaticTransport:
    def __init__(self, payload: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        self.payload = dict(payload or {})
        self.exc = exc
        self.requests: list[Any] = []

    def execute(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if self.exc is not None:
            raise self.exc
        return dict(self.payload)


class DecisionHubSDEPExecutorTests(unittest.TestCase):
    def test_execution_request_to_intent_mapping(self) -> None:
        request = _execution_request()

        intent = execution_request_to_intent(request)

        self.assertEqual(intent.id, request.execution_id)
        self.assertEqual(intent.operation["name"], SDEP_DELEGATE_ACTION_TYPE)
        self.assertEqual(intent.objective["id"], request.decision_id)
        self.assertEqual(intent.executor_type, "codex")
        self.assertEqual(intent.target["kind"], "work_item")
        self.assertEqual(intent.target["id"], request.acted_on)
        self.assertEqual(intent.target["title"], request.params["target_title"])
        self.assertEqual(intent.target["url"], request.params["target_url"])
        self.assertEqual(intent.parameters["scope"], "triage")
        self.assertEqual(intent.parameters["trace_ref"], request.params["trace_ref"])
        self.assertEqual(intent.input_payload["decision_id"], request.decision_id)
        self.assertEqual(intent.input_payload["trace_ref"], request.params["trace_ref"])
        self.assertEqual(intent.input_payload["acted_on"], request.acted_on)
        self.assertEqual(intent.input_payload["selected_action"], SDEP_DELEGATE_ACTION_TYPE)
        self.assertEqual(intent.input_payload["demo_action_type"], "delegate_to_executor")
        self.assertEqual(
            intent.success_criteria[0]["description"],
            request.params["success_criteria"],
        )
        self.assertIn(request.execution_id, intent.refs)
        self.assertIn(request.decision_id, intent.refs)
        self.assertIn(request.params["trace_ref"], intent.refs)
        self.assertIn(request.acted_on, intent.refs)

    def test_execution_intent_to_sdep_request_mapping(self) -> None:
        request = _execution_request()
        intent = execution_request_to_intent(request)

        sdep_request = execution_intent_to_sdep_request(intent)

        self.assertEqual(sdep_request.idempotency_key, request.execution_id)
        self.assertEqual(sdep_request.execution.action_type, SDEP_DELEGATE_ACTION_TYPE)
        self.assertNotEqual(sdep_request.execution.action_type, "delegate_to_executor")
        self.assertEqual(sdep_request.execution.target["id"], request.acted_on)
        self.assertEqual(sdep_request.execution.parameters["scope"], "triage")
        self.assertEqual(
            sdep_request.execution.success_criteria[0]["description"],
            request.params["success_criteria"],
        )
        self.assertEqual(sdep_request.traceability["execution_id"], request.execution_id)
        self.assertEqual(sdep_request.traceability["spice_decision_id"], request.decision_id)
        self.assertEqual(sdep_request.traceability["trace_ref"], request.params["trace_ref"])
        self.assertEqual(sdep_request.traceability["acted_on"], request.acted_on)
        self.assertEqual(sdep_request.execution.metadata["adapter"], "decision_hub_demo.sdep_executor")
        self.assertEqual(sdep_request.execution.metadata["demo_action_type"], "delegate_to_executor")

    def test_success_sdep_response_to_success_execution_outcome(self) -> None:
        request = _execution_request()
        response = _sdep_response(
            request,
            output={
                "decision_id": request.decision_id,
                "selected_action": SDEP_DELEGATE_ACTION_TYPE,
                "acted_on": request.acted_on,
                "status": "success",
                "elapsed_minutes": 7,
                "risk_change": "reduced",
                "followup_needed": True,
                "summary": "Codex triaged the PR.",
                "execution_ref": "hermes.exec.001",
            },
        )

        outcome = sdep_response_to_execution_outcome(request, response)

        self.assertEqual(outcome.status, "success")
        self.assertEqual(outcome.elapsed_minutes, 7)
        self.assertEqual(outcome.risk_change, "reduced")
        self.assertTrue(outcome.followup_needed)
        self.assertEqual(outcome.summary, "Codex triaged the PR.")
        self.assertEqual(outcome.execution_ref, "hermes.exec.001")
        self.assertIsNone(outcome.blocking_issue)
        self.assertEqual(outcome.metadata["decision_id"], request.decision_id)
        self.assertEqual(outcome.metadata["trace_ref"], request.params["trace_ref"])
        self.assertEqual(outcome.metadata["acted_on"], request.acted_on)
        self.assertEqual(outcome.metadata["sdep_response_status"], "success")
        self.assertEqual(outcome.metadata["sdep_outcome_status"], "success")

    def test_failed_sdep_outcome_to_failed_execution_outcome(self) -> None:
        request = _execution_request()
        response = _sdep_response(
            request,
            outcome_status="failed",
            output={
                "status": "failed",
                "elapsed_minutes": 3,
                "risk_change": "increased",
                "followup_needed": True,
                "summary": "Codex could not triage the PR.",
                "execution_ref": "hermes.exec.failed",
                "blocking_issue": "test_failure",
            },
        )

        outcome = sdep_response_to_execution_outcome(request, response)

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.elapsed_minutes, 3)
        self.assertEqual(outcome.risk_change, "increased")
        self.assertTrue(outcome.followup_needed)
        self.assertEqual(outcome.blocking_issue, "test_failure")

    def test_partial_sdep_outcome_to_partial_execution_outcome(self) -> None:
        request = _execution_request()
        response = _sdep_response(
            request,
            outcome_status="partial",
            output={
                "status": "partial",
                "elapsed_minutes": 5,
                "risk_change": "reduced",
                "followup_needed": True,
                "summary": "Codex completed triage but left review work.",
                "execution_ref": "hermes.exec.partial",
            },
        )

        outcome = sdep_response_to_execution_outcome(request, response)

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.elapsed_minutes, 5)
        self.assertEqual(outcome.risk_change, "reduced")
        self.assertTrue(outcome.followup_needed)
        self.assertIsNone(outcome.blocking_issue)

    def test_protocol_error_response_to_failed_execution_outcome(self) -> None:
        request = _execution_request()
        response = _sdep_response(
            request,
            response_status="error",
            outcome_status="failed",
            output={
                "status": "failed",
                "summary": "Hermes timed out before producing an outcome.",
            },
            error={
                "code": "hermes.timeout",
                "message": "Hermes timed out after 30 seconds.",
                "retryable": True,
                "details": {"timeout_seconds": 30},
            },
        )

        outcome = sdep_response_to_execution_outcome(request, response)

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.blocking_issue, "hermes.timeout")
        self.assertTrue(outcome.followup_needed)
        self.assertEqual(outcome.metadata["sdep_response_status"], "error")
        self.assertEqual(outcome.metadata["sdep_error"]["details"]["timeout_seconds"], 30)

    def test_executor_sends_canonical_sdep_request(self) -> None:
        request = _execution_request()
        transport = _StaticTransport(_sdep_response(request))
        executor = SDEPBackedExecutor(transport)

        outcome = executor.execute(request)

        self.assertEqual(outcome.status, "success")
        self.assertEqual(len(transport.requests), 1)
        sent = transport.requests[0]
        self.assertEqual(sent.idempotency_key, request.execution_id)
        self.assertEqual(sent.execution.action_type, SDEP_DELEGATE_ACTION_TYPE)
        self.assertEqual(sent.execution.target["id"], request.acted_on)
        self.assertEqual(sent.traceability["spice_decision_id"], request.decision_id)
        self.assertEqual(sent.traceability["trace_ref"], request.params["trace_ref"])

    def test_executor_catches_transport_error(self) -> None:
        request = _execution_request()
        executor = SDEPBackedExecutor(_StaticTransport(exc=RuntimeError("transport down")))

        outcome = executor.execute(request)

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.blocking_issue, "sdep_executor_error")
        self.assertEqual(outcome.metadata["error_type"], "RuntimeError")
        self.assertEqual(outcome.metadata["execution_id"], request.execution_id)
        self.assertEqual(outcome.metadata["decision_id"], request.decision_id)
        self.assertEqual(outcome.metadata["trace_ref"], request.params["trace_ref"])


def _execution_request(action_type: str = "delegate_to_executor") -> ExecutionRequest:
    return ExecutionRequest(
        execution_id="exec.2026-04-17T06:00:00Z.delegate.ab12",
        decision_id="decision.2026-04-17T06:00:00Z.workitem.github_pr_123.ab12",
        action_type=action_type,
        acted_on="workitem.github_pr.123",
        params={
            "scope": "triage",
            "time_budget_minutes": 10,
            "target_title": "Fix decision guidance validation",
            "target_url": "https://github.com/Dyalwayshappy/Spice/pull/123",
            "success_criteria": "Return status, blocker, risk_change, followup_needed",
            "recommendation": "Delegate PR triage to Codex.",
            "human_summary": "Let Codex triage the PR before the meeting.",
            "reason_summary": ["executor available", "time pressure favors delegation"],
            "trace_ref": "trace.decision.ab12",
        },
        executor="codex",
        created_at="2026-04-17T06:00:00Z",
    )


def _sdep_response(
    request: ExecutionRequest,
    *,
    response_status: str = "success",
    outcome_status: str = "success",
    output: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "protocol": "sdep",
        "sdep_version": "0.1",
        "message_type": "execute.response",
        "message_id": "sdep-msg-test",
        "request_id": "sdep-req-test",
        "timestamp": "2026-04-17T06:00:01+00:00",
        "responder": {
            "id": "agent.hermes",
            "name": "Hermes SDEP Executor",
            "version": "0.1",
            "vendor": "Spice",
            "implementation": "hermes-codex",
            "role": "executor",
        },
        "status": response_status,
        "outcome": {
            "execution_id": "hermes.exec.001",
            "status": outcome_status,
            "outcome_type": "observation",
            "output": output
            or {
                "decision_id": request.decision_id,
                "selected_action": SDEP_DELEGATE_ACTION_TYPE,
                "acted_on": request.acted_on,
                "status": "success",
                "elapsed_minutes": 6,
                "risk_change": "reduced",
                "followup_needed": True,
                "summary": "Codex triaged the PR.",
                "execution_ref": "hermes.exec.001",
            },
            "artifacts": [],
            "metrics": {"elapsed_minutes": 6},
            "metadata": {"executor": "codex"},
        },
        "error": error,
        "traceability": {
            "execution_id": request.execution_id,
            "spice_decision_id": request.decision_id,
            "trace_ref": request.params["trace_ref"],
            "acted_on": request.acted_on,
        },
        "metadata": {"wrapper": "hermes_sdep_agent"},
    }


if __name__ == "__main__":
    unittest.main()
