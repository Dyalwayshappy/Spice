from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from spice.protocols import Observation


class PerceptionModel(ABC):
    """Provider-agnostic interface for perception-stage interpretation."""

    @abstractmethod
    def interpret(
        self,
        raw_input: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> Observation:
        """Produce an Observation proposal from raw input."""
