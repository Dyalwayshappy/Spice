from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from spice.domain import DomainPack, SoftwareDomainPack
from spice.executors import Executor, MockExecutor
from spice.memory import ContextCompiler, EpisodeWriter, MemoryProvider, build_episode_record
from spice.decision import (
    CandidateDecision,
    DecisionObjective,
    DecisionPolicy,
    DecisionTrace,
    PolicyIdentity,
    SafetyConstraint,
    build_policy_hash,
)
from spice.protocols import (
    Decision,
    ExecutionIntent,
    ExecutionResult,
    Observation,
    Outcome,
    Reflection,
    WorldState,
)
from spice.core.state_store import StateStore


class SpiceRuntime:
    """Minimal orchestration skeleton for the Spice decision lifecycle."""

    def __init__(
        self,
        state_store: StateStore | None = None,
        domain_pack: DomainPack | None = None,
        executor: Executor | None = None,
        context_compiler: ContextCompiler | None = None,
        memory_provider: MemoryProvider | None = None,
        decision_policy: DecisionPolicy | None = None,
        strict_attribution: bool = False,
        enable_episode_writeback: bool = True,
        include_episode_execution_traces: bool = False,
    ) -> None:
        self.state_store = state_store or StateStore()
        self.context_compiler = context_compiler
        self.memory_provider = memory_provider
        self.decision_policy = decision_policy
        self.strict_attribution = strict_attribution
        self.enable_episode_writeback = bool(enable_episode_writeback)
        self.include_episode_execution_traces = bool(include_episode_execution_traces)
        self.episode_writer: EpisodeWriter | None = None
        self._latest_decision_trace: DecisionTrace | None = None
        if domain_pack is None:
            self.domain_pack = SoftwareDomainPack(
                context_compiler=context_compiler,
                memory_provider=memory_provider,
            )
        else:
            self.domain_pack = domain_pack
            if getattr(self.domain_pack, "context_compiler", None) is None:
                self.domain_pack.context_compiler = context_compiler
            if getattr(self.domain_pack, "memory_provider", None) is None:
                self.domain_pack.memory_provider = memory_provider
        self.executor = executor or MockExecutor()
        if self.memory_provider is not None and self.enable_episode_writeback:
            self.episode_writer = EpisodeWriter(
                self.memory_provider,
                include_execution_traces=self.include_episode_execution_traces,
            )

    def observe(
        self,
        observation: Observation | None = None,
        *,
        observation_type: str = "generic",
        source: str | None = None,
        attributes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Observation:
        if observation is not None:
            return observation

        return Observation(
            id=self._next_id("obs"),
            observation_type=observation_type,
            source=source,
            attributes=attributes or {},
            metadata=metadata or {},
        )

    def update_state(self, record: Observation | Outcome) -> WorldState:
        if isinstance(record, Observation):
            reduced_state = self.domain_pack.reduce_observation(
                self.state_store.get_state(),
                record,
            )
            return self.state_store.apply_observation(record, next_state=reduced_state)
        if isinstance(record, Outcome):
            reduced_state = self.domain_pack.reduce_outcome(
                self.state_store.get_state(),
                record,
            )
            return self.state_store.apply_outcome(record, next_state=reduced_state)
        raise TypeError(f"Unsupported record type: {type(record)!r}")

    def decide(self, state: WorldState | None = None) -> Decision:
        state = state or self.state_store.get_state()
        decision_context = None
        if self.context_compiler is not None:
            decision_context = self.context_compiler.compile_decision_context(
                state,
                domain=self.domain_pack.domain_name,
                recent_history=self.state_store.history,
            )

        candidates_mode = "synthetic"
        if self.decision_policy is not None:
            candidates = self.decision_policy.propose(state, decision_context)
            if candidates:
                candidates_mode = "policy"
            else:
                domain_fallback_decision = self.domain_pack.decide(
                    state,
                    decision_context=decision_context,
                )
                candidates, is_synthetic = self._extract_candidates(domain_fallback_decision)
                candidates_mode = "synthetic" if is_synthetic else "policy"
            objective = self._objective_from_context(decision_context)
            constraints = self._constraints_from_context(decision_context)
            decision = self.decision_policy.select(candidates, objective, constraints)
            policy_identity = self.decision_policy.identity
        else:
            decision = self.domain_pack.decide(state, decision_context=decision_context)
            candidates, is_synthetic = self._extract_candidates(decision)
            candidates_mode = "synthetic" if is_synthetic else "policy"
            objective = self._objective_from_decision(decision)
            constraints = self._constraints_from_decision(decision)
            policy_identity = self._policy_identity_from_decision(decision)

        if state.id not in decision.refs:
            decision.refs.append(state.id)

        self.state_store.record(decision)
        cycle_index = len(self.state_store.decision_traces) + 1

        decision_trace = self._build_decision_trace(
            decision=decision,
            state=state,
            cycle_index=cycle_index,
            candidates=candidates,
            candidates_mode=candidates_mode,
            objective=objective,
            constraints=constraints,
            policy_identity=policy_identity,
        )
        self.state_store.record(decision_trace)
        self._latest_decision_trace = decision_trace

        return decision

    def plan_execution(self, decision: Decision) -> ExecutionIntent:
        intent = self.domain_pack.plan_execution(decision)
        if decision.id not in intent.refs:
            intent.refs.append(decision.id)
        intent.provenance.setdefault("decision_id", decision.id)
        self.state_store.record(intent)
        return intent

    def execute(self, intent: ExecutionIntent) -> ExecutionResult:
        result = self.executor.execute(intent)
        self.state_store.record(result)
        return result

    def process_execution_result(
        self,
        result: ExecutionResult,
        *,
        decision: Decision | None = None,
        intent: ExecutionIntent | None = None,
    ) -> Outcome:
        outcome = self.domain_pack.interpret_execution_result(result)

        decision_id = self._resolve_decision_id(
            result,
            decision=decision,
            intent=intent,
        )
        if not outcome.decision_id:
            outcome.decision_id = decision_id
        if self.strict_attribution and not outcome.decision_id:
            raise ValueError(
                f"Could not resolve outcome.decision_id for execution result: {result.id}"
            )
        if outcome.decision_id and outcome.decision_id not in outcome.refs:
            outcome.refs.append(outcome.decision_id)
        return outcome

    def reflect(
        self,
        outcome: Outcome,
        *,
        decision: Decision | None = None,
        intent: ExecutionIntent | None = None,
        execution_result: ExecutionResult | None = None,
    ) -> Reflection:
        reflection_context = None
        if self.context_compiler is not None:
            reflection_context = self.context_compiler.compile_reflection_context(
                self.state_store.get_state(),
                outcome,
                domain=self.domain_pack.domain_name,
                decision=decision,
                intent=intent,
                execution_result=execution_result,
                recent_history=self.state_store.history,
            )

        reflection = self.domain_pack.reflect(
            self.state_store.get_state(),
            outcome,
            execution_result=execution_result,
            reflection_context=reflection_context,
        )
        self.state_store.record(reflection)
        if self.context_compiler is not None:
            self.context_compiler.write_reflection(
                asdict(reflection),
                domain=self.domain_pack.domain_name,
                provider=self.memory_provider,
            )
        return reflection

    def run_cycle(
        self,
        observation: Observation | None = None,
        *,
        observation_type: str = "generic",
        source: str | None = None,
        attributes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one full placeholder lifecycle step."""
        state_before = deepcopy(self.state_store.get_state())
        observation = self.observe(
            observation=observation,
            observation_type=observation_type,
            source=source,
            attributes=attributes,
            metadata=metadata,
        )
        state = self.update_state(observation)
        decision = self.decide(state)
        decision_trace = self.latest_decision_trace
        intent = self.plan_execution(decision)
        result = self.execute(intent)
        outcome = self.process_execution_result(
            result,
            decision=decision,
            intent=intent,
        )
        state = self.update_state(outcome)
        reflection = self.reflect(
            outcome,
            decision=decision,
            intent=intent,
            execution_result=result,
        )
        if decision_trace is not None:
            self._write_episode(
                world_state_before=state_before,
                world_state_after=deepcopy(state),
                observation=observation,
                decision=decision,
                decision_trace=decision_trace,
                execution_intent=intent,
                execution_result=result,
                outcome=outcome,
                reflection=reflection,
            )

        return {
            "observation": observation,
            "world_state": state,
            "decision": decision,
            "decision_trace": decision_trace,
            "execution_intent": intent,
            "execution_result": result,
            "outcome": outcome,
            "reflection": reflection,
        }

    @property
    def latest_decision_trace(self) -> DecisionTrace | None:
        return self._latest_decision_trace

    def _build_decision_trace(
        self,
        *,
        decision: Decision,
        state: WorldState,
        cycle_index: int,
        candidates: list[CandidateDecision],
        candidates_mode: str,
        objective: DecisionObjective,
        constraints: list[SafetyConstraint],
        policy_identity: PolicyIdentity,
    ) -> DecisionTrace:
        selected_candidate = self._resolve_selected_candidate(decision, candidates)

        veto_events = decision.attributes.get("veto_events", [])
        veto_list = list(veto_events) if isinstance(veto_events, list) else []

        trace_metadata = dict(decision.metadata)
        if constraints:
            trace_metadata["constraints_used"] = [asdict(constraint) for constraint in constraints]

        return DecisionTrace(
            id=f"trace.{decision.id}",
            refs=[decision.id, state.id],
            metadata=trace_metadata,
            state_ref=state.id,
            cycle_index=cycle_index,
            all_candidates=candidates,
            candidates_mode=candidates_mode,
            selected_candidate=selected_candidate,
            veto_events=veto_list,
            objective_used=objective,
            policy_name=policy_identity.policy_name,
            policy_version=policy_identity.policy_version,
            policy_hash=policy_identity.resolved_hash(),
        )

    @staticmethod
    def _objective_from_context(context: Any) -> DecisionObjective:
        if context is None:
            return DecisionObjective()

        objectives = getattr(context, "objectives", None)
        if isinstance(objectives, list) and objectives:
            first = objectives[0]
            if isinstance(first, dict):
                return DecisionObjective.from_dict(first)

        metadata = getattr(context, "metadata", None)
        if isinstance(metadata, dict):
            objective_payload = metadata.get("objective")
            if isinstance(objective_payload, dict):
                return DecisionObjective.from_dict(objective_payload)

        return DecisionObjective()

    @staticmethod
    def _constraints_from_context(context: Any) -> list[SafetyConstraint]:
        constraints = getattr(context, "constraints", None)
        return SpiceRuntime._normalize_constraints(constraints)

    @staticmethod
    def _objective_from_decision(decision: Decision) -> DecisionObjective:
        objective_payload = decision.attributes.get("objective_used")
        if isinstance(objective_payload, dict):
            return DecisionObjective.from_dict(objective_payload)
        return DecisionObjective()

    @staticmethod
    def _constraints_from_decision(decision: Decision) -> list[SafetyConstraint]:
        raw = decision.attributes.get("constraints_used")
        return SpiceRuntime._normalize_constraints(raw)

    def _policy_identity_from_decision(self, decision: Decision) -> PolicyIdentity:
        policy_name = str(
            decision.attributes.get(
                "policy_name",
                f"{self.domain_pack.domain_name}.domain_pack",
            )
        )
        policy_version = str(decision.attributes.get("policy_version", "0.1"))
        policy_hash = str(decision.attributes.get("policy_hash", ""))
        implementation_fingerprint = str(
            decision.attributes.get("implementation_fingerprint", "")
        )

        if policy_hash:
            return PolicyIdentity(
                policy_name=policy_name,
                policy_version=policy_version,
                policy_hash=policy_hash,
                implementation_fingerprint=implementation_fingerprint,
            )

        return PolicyIdentity(
            policy_name=policy_name,
            policy_version=policy_version,
            policy_hash=build_policy_hash(
                policy_name=policy_name,
                policy_version=policy_version,
                implementation_fingerprint=implementation_fingerprint,
            ),
            implementation_fingerprint=implementation_fingerprint,
        )

    @staticmethod
    def _extract_candidates(decision: Decision) -> tuple[list[CandidateDecision], bool]:
        raw_candidates = decision.attributes.get("all_candidates")
        if isinstance(raw_candidates, list):
            parsed = [
                CandidateDecision.from_dict(entry)
                for entry in raw_candidates
                if isinstance(entry, dict)
            ]
            if parsed:
                return parsed, False

        selected_action = decision.selected_action or "unknown.action"
        return (
            [
                CandidateDecision(
                    id=f"candidate.{decision.id}.selected",
                    action=selected_action,
                    params={},
                    score_total=1.0,
                    score_breakdown={"default": 1.0},
                    risk=0.0,
                    confidence=1.0,
                )
            ],
            True,
        )

    @staticmethod
    def _resolve_selected_candidate(
        decision: Decision,
        candidates: list[CandidateDecision],
    ) -> CandidateDecision | None:
        if not candidates:
            return None

        selected_candidate_id = decision.attributes.get("selected_candidate_id")
        if isinstance(selected_candidate_id, str):
            for candidate in candidates:
                if candidate.id == selected_candidate_id:
                    return candidate

        if decision.selected_action:
            for candidate in candidates:
                if candidate.action == decision.selected_action:
                    return candidate

        return candidates[0]

    def _resolve_decision_id(
        self,
        result: ExecutionResult,
        *,
        decision: Decision | None,
        intent: ExecutionIntent | None,
    ) -> str:
        if decision is not None:
            return decision.id

        if intent is not None:
            decision_id = intent.provenance.get("decision_id")
            if isinstance(decision_id, str) and decision_id:
                return decision_id
            if intent.refs:
                first_ref = intent.refs[0]
                if isinstance(first_ref, str) and first_ref:
                    return first_ref

        for ref in result.refs:
            if not isinstance(ref, str):
                continue
            for record in reversed(self.state_store.history):
                if not isinstance(record, ExecutionIntent):
                    continue
                if record.id != ref:
                    continue

                decision_id = record.provenance.get("decision_id")
                if isinstance(decision_id, str) and decision_id:
                    return decision_id
                if record.refs:
                    first_ref = record.refs[0]
                    if isinstance(first_ref, str) and first_ref:
                        return first_ref
                break

        return ""

    @staticmethod
    def _normalize_constraints(raw: Any) -> list[SafetyConstraint]:
        if not isinstance(raw, list):
            return []

        normalized: list[SafetyConstraint] = []
        for entry in raw:
            if isinstance(entry, SafetyConstraint):
                normalized.append(entry)
                continue
            if isinstance(entry, dict):
                normalized.append(SafetyConstraint.from_dict(entry))
        return normalized

    def _write_episode(
        self,
        *,
        world_state_before: WorldState,
        world_state_after: WorldState,
        observation: Observation,
        decision: Decision,
        decision_trace: DecisionTrace,
        execution_intent: ExecutionIntent,
        execution_result: ExecutionResult,
        outcome: Outcome,
        reflection: Reflection,
    ) -> None:
        if self.episode_writer is None:
            return

        episode = build_episode_record(
            domain=self.domain_pack.domain_name,
            cycle_index=decision_trace.cycle_index if decision_trace.cycle_index > 0 else 1,
            world_state_before=world_state_before,
            world_state_after=world_state_after,
            observation=observation,
            decision=decision,
            decision_trace=decision_trace,
            execution_intent=execution_intent,
            execution_result=execution_result,
            outcome=outcome,
            reflection=reflection,
            include_execution_traces=self.include_episode_execution_traces,
            metadata={
                "runtime": "spice",
                "domain_pack": self.domain_pack.__class__.__name__,
            },
        )
        self.episode_writer.write(episode)

    @staticmethod
    def _next_id(prefix: str) -> str:
        return f"{prefix}-{uuid4().hex}"
