from __future__ import annotations

from abc import ABC, abstractmethod

from spice.protocols import ExecutionIntent, ExecutionResult


class Executor(ABC):
    """Execution interface for runtime-intent delegation."""

    @abstractmethod
    def execute(self, intent: ExecutionIntent) -> ExecutionResult:
        """Execute an intent and return a protocol-level execution result."""
