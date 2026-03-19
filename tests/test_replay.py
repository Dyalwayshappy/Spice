from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spice.core import SpiceRuntime
from spice.decision import CandidateDecision, PolicyIdentity, SafetyConstraint
from spice.protocols import Decision, Observation, Outcome
from spice.replay import ReplayRunner, load_replay_stream


class DeterministicPolicy:
    identity = PolicyIdentity.create(
        policy_name="tests.deterministic_policy",
        policy_version="0.2",
        implementation_fingerprint="deterministic-v1",
    )

    def propose(self, state, context):
        count = int(state.resources.get("observation_count", 0))
        return [
            CandidateDecision(
                id=f"cand-{count}-safe",
                action="action.safe",
                params={"mode": "safe"},
                score_total=0.8,
                score_breakdown={"stability": 0.8, "cost": 0.6},
                risk=0.1,
                confidence=0.9,
            ),
            CandidateDecision(
                id=f"cand-{count}-fast",
                action="action.fast",
                params={"mode": "fast"},
                score_total=0.6,
                score_breakdown={"latency": 0.9, "stability": 0.4},
                risk=0.7,
                confidence=0.8,
            ),
        ]

    def select(self, candidates, objective, constraints):
        if constraints:
            self._assert_constraints(constraints)

        eligible = [candidate for candidate in candidates if candidate.risk <= objective.risk_budget]
        selected = max(eligible or candidates, key=lambda candidate: candidate.score_total)

        return Decision(
            id=f"decision.{selected.id}",
            decision_type="tests.policy_decision",
            selected_action=selected.action,
            attributes={
                "selected_candidate_id": selected.id,
            },
        )

    @staticmethod
    def _assert_constraints(constraints):
        for constraint in constraints:
            if not isinstance(constraint, SafetyConstraint):
                raise AssertionError(f"Expected SafetyConstraint, got {type(constraint)!r}")


class ReplayTests(unittest.TestCase):
    def _runtime_factory(self) -> SpiceRuntime:
        return SpiceRuntime(decision_policy=DeterministicPolicy())

    def test_replay_deterministic_for_pinned_policy(self) -> None:
        stream = [
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

        runner = ReplayRunner(
            self._runtime_factory,
            stability_predicate=lambda state: int(state.resources.get("observation_count", 0)) >= 2,
        )
        report = runner.replay(
            stream,
            pinned_policy_hash=DeterministicPolicy.identity.resolved_hash(),
            check_determinism=True,
        )

        self.assertTrue(report.deterministic)
        self.assertEqual(report.total_cycles, 2)
        self.assertEqual(report.cycles_to_stable, 2)
        self.assertEqual(report.policy_name, "tests.deterministic_policy")
        self.assertEqual(report.policy_version, "0.2")
        self.assertEqual(report.policy_hash, DeterministicPolicy.identity.resolved_hash())

        cycle = report.cycles[0]
        self.assertEqual(cycle.cycle_index, 1)
        self.assertEqual(cycle.selected_action, "action.safe")
        self.assertEqual(cycle.selected_candidate_score, 0.8)
        self.assertFalse(cycle.veto)
        self.assertEqual(cycle.candidates_mode, "policy")

    def test_replay_rejects_policy_hash_mismatch(self) -> None:
        runner = ReplayRunner(self._runtime_factory)
        stream = [
            Observation(
                id="obs-001",
                observation_type="software.build_failure",
                source="ci",
                attributes={"build": "1"},
            )
        ]

        with self.assertRaises(ValueError):
            runner.replay(
                stream,
                pinned_policy_hash="mismatch",
                check_determinism=False,
            )

    def test_load_replay_stream_from_jsonl(self) -> None:
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
                "decision_id": "decision.001",
                "changes": {},
                "attributes": {"status": "ok"},
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "replay.jsonl"
            with path.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row))
                    f.write("\n")

            records = load_replay_stream(path)

        self.assertEqual(len(records), 2)
        self.assertIsInstance(records[0], Observation)
        self.assertIsInstance(records[1], Outcome)


if __name__ == "__main__":
    unittest.main()
