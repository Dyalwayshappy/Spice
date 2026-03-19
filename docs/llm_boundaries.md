# Spice LLM Boundaries (Internal, v0.1)

## Why LLM Boundaries Are Needed

Spice combines cognitive reasoning with deterministic runtime guarantees.
Without explicit boundaries, probabilistic model output could corrupt state consistency, break auditability, and bypass protocol contracts.

LLM integration in Spice therefore follows a strict separation:

- LLMs generate proposals and reasoning artifacts.
- Deterministic runtime logic validates, routes, and commits authoritative changes.

## Deterministic Core vs Optional Intelligence

Deterministic core (authoritative) Deterministic core guarantees that state transitions are replayable and auditable.:

- protocol contracts
- `WorldState`
- `WorldDelta`
- `apply_delta(WorldState, WorldDelta)`
- runtime sequencing
- state/history storage
- execution routing contract

Optional intelligence (non-authoritative):

- perception interpretation
- decision generation
- simulation/prediction
- reflection synthesis

## Perception Boundary

`PerceptionModel` may interpret raw input into `Observation` proposals.

Rules:

- Perception produces `Observation`, not authoritative state changes.
- Perception models interpret inputs but do not decide state transitions.
- State transitions remain the responsibility of domain reducers and deterministic delta application.
- Perception may attach reasoning metadata/confidence.
- Perception must not directly produce committed `WorldState` changes.
- Any eventual state transition still goes through domain reducers and deterministic delta application.

## Decision Boundary

`DecisionModel` may generate one or more candidate `Decision` objects.

Rules:

- Decision stage supports multiple candidates (ranking/selection can remain deterministic or policy-driven).
- Decision proposals must conform to protocol schema.
- Chosen decision is committed by runtime/domain logic, not by the model itself.

## Simulation Boundary

`SimulationModel` is advisory and pre-execution only.

Rules:

- Simulation may evaluate candidate decisions/intents and return predicted outcomes/risks/confidence.
- Simulation outputs are reasoning artifacts, not authoritative state.
- Simulation must never mutate `WorldState`.
- Simulation can influence selection of `Decision`/`ExecutionIntent`, but commit remains deterministic.

## Reflection Boundary

`ReflectionModel` may synthesize `Reflection` records from execution context.

Rules:

- Reflection output is a protocol record for traceability and learning context.
- Reflection does not directly mutate `WorldState`.
- Any state impact from reflection must be expressed through deterministic mechanisms (e.g., explicit reducers/deltas in future design).

## Core Design Rule: LLMs Propose, Deterministic Core Commits

Spice authoritative state mutation rule:

`WorldState` may only change through:

`WorldDelta -> apply_delta(WorldState, WorldDelta)`

Therefore:

- LLMs may propose protocol objects or reasoning artifacts.
- LLMs must never directly mutate `WorldState`.
- Deterministic runtime/domain logic is the only commit path.

This boundary preserves reliability, auditability, and cross-domain consistency while still allowing optional model intelligence at cognitive stages.
