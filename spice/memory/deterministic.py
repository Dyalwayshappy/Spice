from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from spice.memory.base import ContextCompiler, MemoryProvider
from spice.memory.context import DecisionContext, ReflectionContext, SimulationContext
from spice.protocols import Decision, ExecutionIntent, ExecutionResult, Outcome, ProtocolRecord, WorldState


class DeterministicContextCompiler(ContextCompiler):
    """Reference deterministic compiler for bounded stage-specific contexts."""

    def __init__(
        self,
        memory_provider: MemoryProvider | None = None,
        *,
        top_k_entities: int = 10,
        top_k_signals: int = 10,
        top_k_risks: int = 10,
        top_k_goals: int = 10,
        top_k_constraints: int = 10,
        top_k_active_intents: int = 10,
        recent_outcomes_limit: int = 10,
        memory_query_limit: int = 10,
        history_ref_limit: int = 20,
        candidate_limit: int = 10,
    ) -> None:
        self.memory_provider = memory_provider
        self.top_k_entities = top_k_entities
        self.top_k_signals = top_k_signals
        self.top_k_risks = top_k_risks
        self.top_k_goals = top_k_goals
        self.top_k_constraints = top_k_constraints
        self.top_k_active_intents = top_k_active_intents
        self.recent_outcomes_limit = recent_outcomes_limit
        self.memory_query_limit = memory_query_limit
        self.history_ref_limit = history_ref_limit
        self.candidate_limit = candidate_limit

    def compile_decision_context(
        self,
        state: WorldState,
        *,
        domain: str = "generic",
        recent_history: list[ProtocolRecord] | None = None,
    ) -> DecisionContext:
        recent_history = recent_history or []
        retrieved = self._query_memory(f"{domain}.decision")
        refs = self._build_refs(state, recent_history, [record.get("id") for record in retrieved])

        return DecisionContext.create(
            world_state_id=state.id,
            domain=domain,
            budget=self._base_budget(),
            confidence={"state": dict(state.confidence), "method": "deterministic"},
            provenance=self._base_provenance(domain, refs, retrieved),
            refs=refs,
            objectives=self._tail(state.goals, self.top_k_goals),
            constraints=self._tail(state.constraints, self.top_k_constraints),
            entities=self._slice_entities(state.entities, self.top_k_entities),
            signals=self._tail(state.signals, self.top_k_signals),
            risks=self._tail(state.risks, self.top_k_risks),
            resources=dict(state.resources),
            active_intents=self._tail(state.active_intents, self.top_k_active_intents),
            recent_outcomes=self._tail(state.recent_outcomes, self.recent_outcomes_limit),
            retrieved_memory=retrieved,
            warnings=self._decision_warnings(state),
        )

    def compile_simulation_context(
        self,
        state: WorldState,
        *,
        domain: str = "generic",
        candidate_decisions: list[Decision] | None = None,
        candidate_intents: list[ExecutionIntent] | None = None,
        recent_history: list[ProtocolRecord] | None = None,
    ) -> SimulationContext:
        recent_history = recent_history or []
        decision_context = self.compile_decision_context(
            state,
            domain=domain,
            recent_history=recent_history,
        )
        retrieved = self._query_memory(f"{domain}.simulation")
        decision_candidates = self._serialize_list(candidate_decisions or [], self.candidate_limit)
        intent_candidates = self._serialize_list(candidate_intents or [], self.candidate_limit)
        refs = self._build_refs(
            state,
            recent_history,
            [
                decision_context.id,
                *[candidate.get("id") for candidate in decision_candidates],
                *[candidate.get("id") for candidate in intent_candidates],
                *[record.get("id") for record in retrieved],
            ],
        )

        return SimulationContext.create(
            world_state_id=state.id,
            domain=domain,
            decision_context_ref=decision_context.id,
            budget={**self._base_budget(), "candidate_limit": self.candidate_limit},
            confidence={"state": dict(state.confidence), "method": "deterministic"},
            provenance=self._base_provenance(domain, refs, retrieved),
            refs=refs,
            candidate_decisions=decision_candidates,
            candidate_intents=intent_candidates,
            assumptions=[
                {
                    "id": "bounded_horizon",
                    "description": "Simulation assumes short-horizon effects only.",
                }
            ],
            evaluation_axes=[
                {"id": "success", "description": "Likelihood of success criteria satisfaction."},
                {"id": "risk", "description": "Risk exposure under candidate execution."},
            ],
            historical_analogs=retrieved[: self.memory_query_limit],
            retrieved_memory=retrieved,
        )

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
        recent_history = recent_history or []
        retrieved = self._query_memory(f"{domain}.reflection")
        refs = self._build_refs(
            state,
            recent_history,
            [
                outcome.id,
                decision.id if decision else None,
                intent.id if intent else None,
                execution_result.id if execution_result else None,
                *[record.get("id") for record in retrieved],
            ],
        )

        expected = intent.success_criteria if intent else []
        actual = {
            "outcome_status": outcome.status,
            "change_count": len(outcome.changes),
            "execution_status": execution_result.status if execution_result else None,
        }

        return ReflectionContext.create(
            world_state_id=state.id,
            domain=domain,
            budget=self._base_budget(),
            confidence={"state": dict(state.confidence), "method": "deterministic"},
            provenance=self._base_provenance(domain, refs, retrieved),
            refs=refs,
            executed_path={
                "decision": self._serialize_record(decision),
                "execution_intent": self._serialize_record(intent),
                "execution_result": self._serialize_record(execution_result),
                "outcome": self._serialize_record(outcome),
            },
            expected_vs_actual={
                "expected": expected,
                "actual": actual,
            },
            impact_summary={
                "outcome_id": outcome.id,
                "outcome_status": outcome.status,
                "world_state_id": state.id,
                "recent_outcomes_count": len(state.recent_outcomes),
            },
            retrieved_lessons=retrieved[: self.memory_query_limit],
            retrieved_memory=retrieved,
            open_questions=[],
        )

    def write_reflection(
        self,
        reflection_record: dict[str, Any],
        *,
        domain: str = "generic",
        provider: MemoryProvider | None = None,
    ) -> list[str]:
        active_provider = provider or self.memory_provider
        if active_provider is None:
            return []

        payload = dict(reflection_record)
        payload.setdefault("domain", domain)
        refs = payload.get("refs")
        ref_list = refs if isinstance(refs, list) else None
        return active_provider.write(
            [payload],
            namespace=f"{domain}.reflection",
            refs=ref_list,
        )

    def _base_budget(self) -> dict[str, Any]:
        return {
            "top_k_entities": self.top_k_entities,
            "top_k_signals": self.top_k_signals,
            "top_k_risks": self.top_k_risks,
            "top_k_goals": self.top_k_goals,
            "top_k_constraints": self.top_k_constraints,
            "top_k_active_intents": self.top_k_active_intents,
            "recent_outcomes_limit": self.recent_outcomes_limit,
            "memory_query_limit": self.memory_query_limit,
        }

    def _base_provenance(
        self,
        domain: str,
        refs: list[str],
        retrieved_memory: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "domain": domain,
            "source_refs": refs,
            "memory_refs": [record.get("id") for record in retrieved_memory if "id" in record],
            "compiler": "DeterministicContextCompiler@0.1",
        }

    def _query_memory(self, namespace: str) -> list[dict[str, Any]]:
        if self.memory_provider is None:
            return []
        return self.memory_provider.query(
            namespace=namespace,
            limit=self.memory_query_limit,
        )

    def _build_refs(
        self,
        state: WorldState,
        recent_history: list[ProtocolRecord],
        extra_refs: list[Any] | None = None,
    ) -> list[str]:
        refs: list[str] = [state.id, *state.refs[-self.history_ref_limit :]]
        refs.extend(record.id for record in recent_history[-self.history_ref_limit :])
        if extra_refs:
            refs.extend(str(ref) for ref in extra_refs if ref)
        return list(dict.fromkeys(refs))

    @staticmethod
    def _tail(values: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        if limit < 0:
            return list(values)
        return list(values[-limit:])

    @staticmethod
    def _slice_entities(entities: dict[str, Any], limit: int) -> dict[str, Any]:
        if limit < 0:
            return dict(entities)
        keys = sorted(entities.keys())[:limit]
        return {key: entities[key] for key in keys}

    def _decision_warnings(self, state: WorldState) -> list[str]:
        warnings: list[str] = []
        if len(state.signals) > self.top_k_signals:
            warnings.append("signals_truncated")
        if len(state.risks) > self.top_k_risks:
            warnings.append("risks_truncated")
        if len(state.recent_outcomes) > self.recent_outcomes_limit:
            warnings.append("recent_outcomes_truncated")
        return warnings

    def _serialize_list(self, values: list[Any], limit: int) -> list[dict[str, Any]]:
        if limit < 0:
            return [self._serialize_record(value) for value in values]
        return [self._serialize_record(value) for value in values[:limit]]

    @staticmethod
    def _serialize_record(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return dict(value)
        return {"value": str(value)}
