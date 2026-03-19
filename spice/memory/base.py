from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from spice.protocols import Decision, ExecutionIntent, ExecutionResult, Outcome, ProtocolRecord, WorldState

from spice.memory.context import DecisionContext, ReflectionContext, SimulationContext


class MemoryProvider(ABC):
    """Provider-agnostic memory storage interface."""

    @abstractmethod
    def write(
        self,
        records: list[dict[str, Any]],
        *,
        namespace: str,
        refs: list[str] | None = None,
    ) -> list[str]:
        """Persist records and return provider-assigned or record IDs."""

    @abstractmethod
    def query(
        self,
        *,
        namespace: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        order_by: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query records from a namespace with lightweight filtering."""


class ContextCompiler(ABC):
    """Compile bounded context artifacts for cognitive stages."""

    @abstractmethod
    def compile_decision_context(
        self,
        state: WorldState,
        *,
        domain: str = "generic",
        recent_history: list[ProtocolRecord] | None = None,
    ) -> DecisionContext:
        """Compile context for decision generation and selection."""

    @abstractmethod
    def compile_simulation_context(
        self,
        state: WorldState,
        *,
        domain: str = "generic",
        candidate_decisions: list[Decision] | None = None,
        candidate_intents: list[ExecutionIntent] | None = None,
        recent_history: list[ProtocolRecord] | None = None,
    ) -> SimulationContext:
        """Compile context for advisory what-if simulation."""

    @abstractmethod
    def compile_reflection_context(
        self,
        state: WorldState,
        outcome: Outcome,
        *,
        domain: str = "generic",
        decision: Decision | None = None,
        intent: ExecutionIntent | None = None,
        execution_result: ExecutionResult | None = None,
        recent_history: list[ProtocolRecord] | None = None,
    ) -> ReflectionContext:
        """Compile context for post-execution reflection."""

    @abstractmethod
    def write_reflection(
        self,
        reflection_record: dict[str, Any],
        *,
        domain: str = "generic",
        provider: MemoryProvider | None = None,
    ) -> list[str]:
        """Write reflection artifacts back to a memory provider."""
