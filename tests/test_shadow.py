from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spice.core import SpiceRuntime
from spice.decision import CandidateDecision, PolicyIdentity
from spice.protocols import Decision, Observation, Outcome
from spice.shadow import compare, compare_from_jsonl


class BaselinePolicy:
    identity = PolicyIdentity.create(
        policy_name="tests.baseline_policy",
        policy_version="0.2",
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
            decision_type="tests.baseline_decision",
            selected_action=selected.action,
            attributes={"selected_candidate_id": selected.id},
        )


class CandidatePolicy:
    identity = PolicyIdentity.create(
        policy_name="tests.candidate_policy",
        policy_version="0.2",
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
            decision_type="tests.candidate_decision",
            selected_action=selected.action,
            attributes={"selected_candidate_id": selected.id},
        )


class ShadowTests(unittest.TestCase):
    @staticmethod
    def _baseline_runtime_factory() -> SpiceRuntime:
        return SpiceRuntime(decision_policy=BaselinePolicy())

    @staticmethod
    def _candidate_runtime_factory() -> SpiceRuntime:
        return SpiceRuntime(decision_policy=CandidatePolicy())

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

    def test_compare_offline_shadow(self) -> None:
        report = compare(
            self._stream(),
            self._baseline_runtime_factory,
            self._candidate_runtime_factory,
            baseline_policy_hash=BaselinePolicy.identity.resolved_hash(),
            candidate_policy_hash=CandidatePolicy.identity.resolved_hash(),
            check_determinism=True,
        )

        self.assertEqual(report.total_cycles, 2)
        self.assertAlmostEqual(report.divergence_rate, 1.0)
        self.assertAlmostEqual(report.avg_score_delta or 0.0, 0.2)
        self.assertEqual(report.veto_divergence_count, 0)
        self.assertIsNone(report.baseline_cycles_to_stable)
        self.assertIsNone(report.candidate_cycles_to_stable)
        self.assertTrue(report.baseline_deterministic)
        self.assertTrue(report.candidate_deterministic)

        first = report.cycles[0]
        self.assertEqual(first.cycle_index, 1)
        self.assertEqual(first.baseline_action, "action.safe")
        self.assertEqual(first.candidate_action, "action.fast")
        self.assertTrue(first.action_diverged)
        self.assertEqual(first.baseline_score, 0.7)
        self.assertEqual(first.candidate_score, 0.9)
        self.assertAlmostEqual(first.score_delta or 0.0, 0.2)
        self.assertFalse(first.baseline_veto)
        self.assertFalse(first.candidate_veto)
        self.assertFalse(first.veto_diverged)
        self.assertEqual(first.baseline_candidates_mode, "policy")
        self.assertEqual(first.candidate_candidates_mode, "policy")
        self.assertEqual(first.baseline_policy_name, "tests.baseline_policy")
        self.assertEqual(first.candidate_policy_name, "tests.candidate_policy")

    def test_compare_from_jsonl(self) -> None:
        rows = [
            {
                "record_type": "observation",
                "id": "obs-001",
                "observation_type": "software.build_failure",
                "source": "ci",
                "attributes": {"build": "1"},
            },
            {
                "record_type": "outcome",
                "id": "out-001",
                "outcome_type": "software.placeholder",
                "status": "applied",
                "decision_id": "decision.synthetic",
                "changes": {},
                "attributes": {"status": "ok"},
            },
            {
                "record_type": "observation",
                "id": "obs-002",
                "observation_type": "software.build_failure",
                "source": "ci",
                "attributes": {"build": "2"},
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "shadow_stream.jsonl"
            with path.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row))
                    f.write("\n")

            report = compare_from_jsonl(
                path,
                self._baseline_runtime_factory,
                self._candidate_runtime_factory,
                baseline_policy_hash=BaselinePolicy.identity.resolved_hash(),
                candidate_policy_hash=CandidatePolicy.identity.resolved_hash(),
                check_determinism=True,
            )

        self.assertEqual(report.total_cycles, 2)
        self.assertAlmostEqual(report.divergence_rate, 1.0)

    def test_policy_hash_mismatch_fails_fast(self) -> None:
        with self.assertRaises(ValueError):
            compare(
                self._stream(),
                self._baseline_runtime_factory,
                self._candidate_runtime_factory,
                baseline_policy_hash="mismatch",
                candidate_policy_hash=CandidatePolicy.identity.resolved_hash(),
                check_determinism=False,
            )


if __name__ == "__main__":
    unittest.main()
