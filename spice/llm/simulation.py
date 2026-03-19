from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from spice.protocols import Decision, ExecutionIntent, WorldState


class SimulationModel(ABC):
    """Provider-agnostic advisory interface for pre-execution simulation."""

    @abstractmethod
    def simulate(
        self,
        state: WorldState,
        *,
        decision: Decision | None = None,
        intent: ExecutionIntent | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return an advisory simulation artifact for candidate evaluation."""
