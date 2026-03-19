from __future__ import annotations

from uuid import uuid4

from spice.executors.base import Executor
from spice.protocols import ExecutionIntent, ExecutionResult


class MockExecutor(Executor):
    """Minimal placeholder executor used for architecture development."""

    def execute(self, intent: ExecutionIntent) -> ExecutionResult:
        operation_name = intent.operation.get("name", "unknown")
        return ExecutionResult(
            id=f"result-{uuid4().hex}",
            result_type="placeholder",
            status="success",
            executor="mock-executor",
            output={"operation": operation_name, "executed": True},
            refs=[intent.id],
        )
