from __future__ import annotations

import unittest

from spice.memory import EpisodePolicyIdentity, EpisodeRecord


class EpisodeMemorySchemaTests(unittest.TestCase):
    def test_episode_record_round_trip(self) -> None:
        episode = EpisodeRecord(
            episode_id="episode.decision.001",
            domain="software",
            cycle_index=1,
            policy=EpisodePolicyIdentity(
                policy_name="software.policy",
                policy_version="0.1",
                policy_hash="hash-001",
            ),
            refs={
                "observation_id": "obs-001",
                "decision_id": "dec-001",
                "decision_trace_id": "trace.dec-001",
                "execution_intent_id": "intent-001",
                "execution_result_id": "result-001",
                "outcome_id": "out-001",
                "reflection_id": "ref-001",
                "world_state_before_id": "ws-before-001",
                "world_state_after_id": "ws-after-001",
            },
            records={
                "observation": {"id": "obs-001"},
                "decision": {"id": "dec-001"},
                "decision_trace": {"id": "trace.dec-001"},
                "execution_intent": {"id": "intent-001"},
                "execution_result": {"id": "result-001", "attributes_keys": []},
                "outcome": {"id": "out-001"},
                "reflection": {"id": "ref-001"},
            },
            timestamps={
                "cycle_started_at": "2026-03-13T00:00:00+00:00",
                "cycle_completed_at": "2026-03-13T00:00:01+00:00",
            },
        )

        payload = episode.to_dict()
        restored = EpisodeRecord.from_dict(payload)

        self.assertEqual(restored.episode_id, "episode.decision.001")
        self.assertEqual(restored.domain, "software")
        self.assertEqual(restored.cycle_index, 1)
        self.assertEqual(restored.policy.policy_hash, "hash-001")
        self.assertEqual(restored.refs["decision_trace_id"], "trace.dec-001")
        self.assertEqual(restored.records["execution_result"]["id"], "result-001")

    def test_episode_record_requires_canonical_refs(self) -> None:
        with self.assertRaises(ValueError):
            EpisodeRecord(
                episode_id="episode.decision.001",
                domain="software",
                cycle_index=1,
                policy=EpisodePolicyIdentity(
                    policy_name="software.policy",
                    policy_version="0.1",
                    policy_hash="hash-001",
                ),
                refs={
                    "observation_id": "obs-001",
                },
                records={
                    "observation": {"id": "obs-001"},
                    "decision": {"id": "dec-001"},
                    "decision_trace": {"id": "trace.dec-001"},
                    "execution_intent": {"id": "intent-001"},
                    "execution_result": {"id": "result-001"},
                    "outcome": {"id": "out-001"},
                    "reflection": {"id": "ref-001"},
                },
                timestamps={
                    "cycle_started_at": "2026-03-13T00:00:00+00:00",
                    "cycle_completed_at": "2026-03-13T00:00:01+00:00",
                },
            ).to_dict()


if __name__ == "__main__":
    unittest.main()
