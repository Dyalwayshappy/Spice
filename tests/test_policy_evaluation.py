from __future__ import annotations

import unittest
from typing import Any
from uuid import uuid4

from spice.core import SpiceRuntime
from spice.decision import CandidateDecision, PolicyIdentity
from spice.evaluation import PolicyEvaluationRunner
from spice.memory import MemoryProvider
from spice.protocols import Decision, Observation, Outcome


class _InMemoryProvider(MemoryProvider):
    def __init__(self) -> None:
        self.storage: dict[str, list[dict[str, Any]]] = {}

    def write(
        self,
        records: list[dict[str, Any]],
        *,
        namespace: str,
        refs: list[str] | None = None,
    ) -> list[str]:
        stored = self.storage.setdefault(namespace, [])
        ids: list[str] = []
        for record in records:
            payload = dict(record)
            payload.setdefault("id", f"mem-{uuid4().hex}")
            stored.append(payload)
            ids.append(str(payload["id"]))
        return ids

    def query(
        self,
        *,
        namespace: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        order_by: str | None = None,
    ) -> list[dict[str, Any]]:
        records = list(self.storage.get(namespace, []))
        if filters:
            filtered: list[dict[str, Any]] = []
            for record in records:
                include = True
                for key, expected in filters.items():
                    if record.get(key) != expected:
                        include = False
                        break
                if include:
                    filtered.append(record)
            records = filtered

        if limit < 0:
            return records
        return records[:limit]


class _BaselinePolicy:
    identity = PolicyIdentity.create(
        policy_name="tests.eval.baseline",
        policy_version="0.1",
        implementation_fingerprint="baseline-v1",
    )

    def propose(self, state, context):
        count = int(state.resources.get("observation_count", 0))
        return [
            CandidateDecision(
                id=f"base-{count}-safe",
                action="action.safe",
                score_total=0.7,
                score_breakdown={"stability": 0.7},
                risk=0.1,
                confidence=0.9,
            )
        ]

    def select(self, candidates, objective, constraints):
        selected = candidates[0]
        return Decision(
            id=f"decision.{selected.id}",
            decision_type="tests.eval.baseline",
            selected_action=selected.action,
            attributes={"selected_candidate_id": selected.id},
        )


class _CandidatePolicy:
    identity = PolicyIdentity.create(
        policy_name="tests.eval.candidate",
        policy_version="0.1",
        implementation_fingerprint="candidate-v1",
    )

    def propose(self, state, context):
        count = int(state.resources.get("observation_count", 0))
        return [
            CandidateDecision(
                id=f"cand-{count}-fast",
                action="action.fast",
                score_total=0.9,
                score_breakdown={"latency": 0.9},
                risk=0.2,
                confidence=0.85,
            )
        ]

    def select(self, candidates, objective, constraints):
        selected = candidates[0]
        return Decision(
            id=f"decision.{selected.id}",
            decision_type="tests.eval.candidate",
            selected_action=selected.action,
            attributes={"selected_candidate_id": selected.id},
        )


class _RiskyCandidatePolicy:
    identity = PolicyIdentity.create(
        policy_name="tests.eval.candidate.risky",
        policy_version="0.1",
        implementation_fingerprint="candidate-risky-v1",
    )

    def propose(self, state, context):
        count = int(state.resources.get("observation_count", 0))
        return [
            CandidateDecision(
                id=f"cand-{count}-risky",
                action="action.risky",
                score_total=0.95,
                score_breakdown={"speed": 0.95},
                risk=1.5,
                confidence=0.8,
            )
        ]

    def select(self, candidates, objective, constraints):
        selected = candidates[0]
        return Decision(
            id=f"decision.{selected.id}",
            decision_type="tests.eval.candidate.risky",
            selected_action=selected.action,
            attributes={"selected_candidate_id": selected.id},
        )


class PolicyEvaluationTests(unittest.TestCase):
    @staticmethod
    def _stream() -> list[Observation | Outcome]:
        return [
            Observation(
                id="obs-001",
                observation_type="software.build_failure",
                source="ci",
                attributes={"build": "1"},
            ),
            Outcome(
                id="out-001",
                outcome_type="software.placeholder",
                status="applied",
                decision_id="decision.synthetic",
                changes={},
                attributes={"status": "ok"},
            ),
            Observation(
                id="obs-002",
                observation_type="software.build_failure",
                source="ci",
                attributes={"build": "2"},
            ),
        ]

    @staticmethod
    def _baseline_runtime_factory() -> SpiceRuntime:
        return SpiceRuntime(decision_policy=_BaselinePolicy())

    @staticmethod
    def _candidate_runtime_factory() -> SpiceRuntime:
        return SpiceRuntime(decision_policy=_CandidatePolicy())

    @staticmethod
    def _risky_candidate_runtime_factory() -> SpiceRuntime:
        return SpiceRuntime(decision_policy=_RiskyCandidatePolicy())

    def test_policy_evaluation_metrics_and_gates(self) -> None:
        runner = PolicyEvaluationRunner(
            baseline_runtime_factory=self._baseline_runtime_factory,
            candidate_runtime_factory=self._candidate_runtime_factory,
        )
        report = runner.evaluate(
            self._stream(),
            domain="software",
            baseline_expected_policy_hash=_BaselinePolicy.identity.resolved_hash(),
            candidate_expected_policy_hash=_CandidatePolicy.identity.resolved_hash(),
            check_determinism=True,
        )

        self.assertEqual(report.domain, "software")
        self.assertEqual(report.metrics.total_cycles, 2)
        self.assertEqual(report.metrics.valid_cycles, 2)
        self.assertAlmostEqual(report.metrics.action_divergence_rate, 1.0)
        self.assertAlmostEqual(report.metrics.avg_selected_candidate_score_delta or 0.0, 0.2)
        self.assertAlmostEqual(report.metrics.baseline_risk_budget_violation_rate or 0.0, 0.0)
        self.assertAlmostEqual(report.metrics.candidate_risk_budget_violation_rate or 0.0, 0.0)
        self.assertTrue(report.gates.determinism_pass)
        self.assertTrue(report.gates.policy_hash_match_pass)
        self.assertTrue(report.gates.candidate_risk_budget_pass)
        self.assertTrue(report.gates.overall_pass)

    def test_policy_hash_mismatch_fails_hash_gate(self) -> None:
        runner = PolicyEvaluationRunner(
            baseline_runtime_factory=self._baseline_runtime_factory,
            candidate_runtime_factory=self._candidate_runtime_factory,
        )
        report = runner.evaluate(
            self._stream(),
            domain="software",
            baseline_expected_policy_hash="mismatch",
            candidate_expected_policy_hash=_CandidatePolicy.identity.resolved_hash(),
            check_determinism=False,
        )

        self.assertFalse(report.baseline.policy_hash_match)
        self.assertFalse(report.gates.policy_hash_match_pass)
        self.assertFalse(report.gates.overall_pass)
        self.assertIn("policy_hash_mismatch", report.gates.messages)

    def test_candidate_risk_budget_gate_fails_for_risky_policy(self) -> None:
        runner = PolicyEvaluationRunner(
            baseline_runtime_factory=self._baseline_runtime_factory,
            candidate_runtime_factory=self._risky_candidate_runtime_factory,
        )
        report = runner.evaluate(
            self._stream(),
            domain="software",
            baseline_expected_policy_hash=_BaselinePolicy.identity.resolved_hash(),
            candidate_expected_policy_hash=_RiskyCandidatePolicy.identity.resolved_hash(),
            check_determinism=True,
        )

        self.assertAlmostEqual(report.metrics.candidate_risk_budget_violation_rate or 0.0, 1.0)
        self.assertFalse(report.gates.candidate_risk_budget_pass)
        self.assertFalse(report.gates.overall_pass)
        self.assertIn("candidate_risk_budget_violation_rate_exceeded", report.gates.messages)

    def test_policy_evaluation_from_episode_dataset(self) -> None:
        provider = _InMemoryProvider()
        runtime = SpiceRuntime(
            memory_provider=provider,
            decision_policy=_BaselinePolicy(),
        )
        runtime.run_cycle(
            observation_type="software.build_failure",
            source="ci",
            attributes={"build": "1"},
        )
        runtime.run_cycle(
            observation_type="software.build_failure",
            source="ci",
            attributes={"build": "2"},
        )

        runner = PolicyEvaluationRunner(
            baseline_runtime_factory=self._baseline_runtime_factory,
            candidate_runtime_factory=self._candidate_runtime_factory,
        )
        report = runner.evaluate_from_provider(
            provider,
            domain="software",
            baseline_expected_policy_hash=_BaselinePolicy.identity.resolved_hash(),
            candidate_expected_policy_hash=_CandidatePolicy.identity.resolved_hash(),
            check_determinism=True,
        )

        self.assertEqual(report.metrics.total_cycles, 2)
        self.assertEqual(report.metrics.valid_cycles, 2)
        self.assertTrue(report.gates.overall_pass)


if __name__ == "__main__":
    unittest.main()
