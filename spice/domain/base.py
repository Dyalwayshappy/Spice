from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from spice.protocols import (
    Decision,
    ExecutionIntent,
    ExecutionResult,
    Observation,
    Outcome,
    Reflection,
    WorldState,
)

if TYPE_CHECKING:
    from spice.memory import ContextCompiler, DecisionContext, MemoryProvider, ReflectionContext
    from spice.llm import (
        DecisionModel,
        PerceptionModel,
        ReflectionModel,
        SimulationModel,
    )


class DomainPack(ABC):
    """Domain integration contract for the Spice runtime."""

    domain_name: str = "generic"

    def __init__(
        self,
        *,
        perception_model: "PerceptionModel | None" = None,
        decision_model: "DecisionModel | None" = None,
        simulation_model: "SimulationModel | None" = None,
        reflection_model: "ReflectionModel | None" = None,
        context_compiler: "ContextCompiler | None" = None,
        memory_provider: "MemoryProvider | None" = None,
    ) -> None:
        self.perception_model = perception_model
        self.decision_model = decision_model
        self.simulation_model = simulation_model
        self.reflection_model = reflection_model
        self.context_compiler = context_compiler
        self.memory_provider = memory_provider

    @abstractmethod
    def reduce_observation(self, state: WorldState, observation: Observation) -> WorldState:
        """Reduce an observation into an updated world state."""

    @abstractmethod
    def reduce_outcome(self, state: WorldState, outcome: Outcome) -> WorldState:
        """Reduce an outcome into an updated world state."""

    @abstractmethod
    def decide(
        self,
        state: WorldState,
        *,
        decision_context: "DecisionContext | None" = None,
    ) -> Decision:
        """Produce a decision from the current world state."""

    @abstractmethod
    def plan_execution(self, decision: Decision) -> ExecutionIntent:
        """Plan an execution intent from a decision."""

    @abstractmethod
    def interpret_execution_result(self, result: ExecutionResult) -> Outcome:
        """Interpret an execution result into a domain-level outcome."""

    @abstractmethod
    def reflect(
        self,
        state: WorldState,
        outcome: Outcome,
        *,
        execution_result: ExecutionResult | None = None,
        reflection_context: "ReflectionContext | None" = None,
    ) -> Reflection:
        """Produce a reflection record for a completed cycle step."""
