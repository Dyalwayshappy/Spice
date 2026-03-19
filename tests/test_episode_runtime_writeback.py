from __future__ import annotations

import unittest
from typing import Any
from uuid import uuid4

from spice.core import SpiceRuntime
from spice.executors import Executor
from spice.memory import EpisodeRecord, MemoryProvider
from spice.protocols import ExecutionIntent, ExecutionResult


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
            if refs:
                payload.setdefault("refs", [])
                existing_refs = payload["refs"] if isinstance(payload["refs"], list) else []
                payload["refs"] = list(dict.fromkeys([*existing_refs, *refs]))
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


class _AttributedExecutor(Executor):
    def execute(self, intent: ExecutionIntent) -> ExecutionResult:
        return ExecutionResult(
            id=f"result-{uuid4().hex}",
            result_type="custom.result",
            status="success",
            executor="attributed-executor",
            output={"operation": intent.operation.get("name", "unknown")},
            refs=[intent.id],
            attributes={"sdep": {"response": {"status": "success"}}},
        )


class RuntimeEpisodeWritebackTests(unittest.TestCase):
    def test_runtime_writes_one_episode_per_cycle(self) -> None:
        provider = _InMemoryProvider()
        runtime = SpiceRuntime(memory_provider=provider)

        runtime.run_cycle(
            observation_type="software.build_failure",
            source="ci",
            attributes={"build": "123"},
        )

        records = provider.query(namespace="software.episode", limit=-1)
        self.assertEqual(len(records), 1)

        episode = EpisodeRecord.from_dict(records[0])
        self.assertEqual(episode.domain, "software")
        self.assertEqual(episode.cycle_index, 1)
        self.assertIn("observation_id", episode.refs)
        self.assertEqual(episode.records["execution_result"]["attributes_keys"], [])
        self.assertNotIn("execution_result_attributes", episode.artifacts)

    def test_runtime_episode_writeback_can_be_disabled(self) -> None:
        provider = _InMemoryProvider()
        runtime = SpiceRuntime(
            memory_provider=provider,
            enable_episode_writeback=False,
        )

        runtime.run_cycle(
            observation_type="software.build_failure",
            source="ci",
            attributes={"build": "123"},
        )

        records = provider.query(namespace="software.episode", limit=-1)
        self.assertEqual(records, [])

    def test_runtime_can_optionally_include_execution_trace_artifacts(self) -> None:
        provider = _InMemoryProvider()
        runtime = SpiceRuntime(
            memory_provider=provider,
            executor=_AttributedExecutor(),
            include_episode_execution_traces=True,
        )

        runtime.run_cycle(
            observation_type="software.build_failure",
            source="ci",
            attributes={"build": "123"},
        )

        records = provider.query(namespace="software.episode", limit=-1)
        self.assertEqual(len(records), 1)

        episode = EpisodeRecord.from_dict(records[0])
        self.assertIn("sdep", episode.records["execution_result"]["attributes_keys"])
        self.assertIn("execution_result_attributes", episode.artifacts)


if __name__ == "__main__":
    unittest.main()
