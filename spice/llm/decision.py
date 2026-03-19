from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from spice.protocols import Decision, WorldState


class DecisionModel(ABC):
    """Provider-agnostic interface for decision proposal generation."""

    @abstractmethod
    def propose(
        self,
        state: WorldState,
        *,
        context: dict[str, Any] | None = None,
        max_candidates: int | None = None,
    ) -> list[Decision]:
        """Produce one or more candidate Decisions for the current world state."""
