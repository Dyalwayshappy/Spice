from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from spice.protocols import ExecutionResult, Outcome, Reflection, WorldState


class ReflectionModel(ABC):
    """Provider-agnostic interface for reflection synthesis."""

    @abstractmethod
    def synthesize(
        self,
        state: WorldState,
        outcome: Outcome,
        *,
        execution_result: ExecutionResult | None = None,
        context: dict[str, Any] | None = None,
    ) -> Reflection:
        """Produce a Reflection proposal for the completed execution step."""
