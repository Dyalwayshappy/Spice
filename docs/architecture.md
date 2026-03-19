# Spice Architecture (Internal, v0.1)

## 1. What Spice Is

Spice is a stateful, domain-agnostic decision runtime.
It defines protocol contracts, deterministic state transitions, and runtime orchestration for closed-loop decision execution across domains.

Current implementation focus:

- protocol-first modeling
- deterministic world modeling (`WorldDelta` + `apply_delta`)
- pluggable domain behavior (`DomainPack`)
- pluggable execution backends (`Executor`)

## 2. Main Lifecycle Loop

Spice runtime loop:

`Observation -> WorldDelta -> WorldState -> Decision -> ExecutionIntent -> ExecutionResult -> Outcome -> WorldDelta -> WorldState -> Reflection`

Current runtime orchestration entrypoint is `SpiceRuntime.run_cycle()` in `spice/core/runtime.py`.

## 3. Deterministic Core vs Optional Intelligence Boundary

Deterministic core (implemented now):

- protocol dataclasses and contracts (`spice/protocols/*`)
- state transition function `apply_delta()` (`spice/protocols/world_delta.py`)
- state storage/history (`spice/core/state_store.py`)
- lifecycle routing/orchestration (`spice/core/runtime.py`)
- executor interface boundary (`spice/executors/base.py`)

Optional intelligence boundary (implemented as opt-in proposal interfaces/adapters):

- perception/observation interpretation
- decision generation
- reflection synthesis

These are injected through domain-level components, while state transition and storage remain deterministic.
`spice/llm/core` provides a shared provider/client/router layer, and `spice/llm/adapters` provide thin opt-in stage adapters.
LLM outputs remain non-authoritative proposals and never bypass deterministic commit paths.

## 4. Role of DomainPack

`DomainPack` (`spice/domain/base.py`) defines how a domain integrates with core:

- reduce observations into WorldDelta
- reduce outcomes into WorldDelta
- produce decisions from world state
- plan execution intent from decision
- interpret execution results into outcomes

`SoftwareDomainPack` (`spice/domain/software.py`) is the reference placeholder implementation.

## 5. Role of Executor

`Executor` (`spice/executors/base.py`) is the execution abstraction:

- receives `ExecutionIntent`
- returns `ExecutionResult`

`MockExecutor` (`spice/executors/mock.py`) is the current reference executor used in examples.
This keeps runtime execution routing stable while allowing execution backends to vary.

## 6. Role of WorldState and WorldDelta

`WorldState` (`spice/protocols/world_state.py`) is the current decision-relevant projection of the world(WorldState intentionally stores only decision-relevant projections rather than raw event logs. Raw observations or execution logs are expected to be stored externally.).
It stores structured state (entities, relations, goals, resources, risks, signals, active intents, recent outcomes, confidence, provenance, domain state), not raw event logs.

`WorldDelta` (`spice/protocols/world_delta.py`) is the structured state change contract.
Domain reducers create deltas; `apply_delta()` deterministically applies them to `WorldState`.

Current modeling path:

`Observation -> WorldDelta -> apply_delta -> WorldState`

## 7. Role of ExecutionIntent (Decision-to-Execution Protocol)

`ExecutionIntent` (`spice/protocols/execution.py`) is the handoff contract from decision layer to execution layer.
It carries:

- objective
- executor type
- target
- operation
- input payload and parameters
- constraints
- success criteria
- failure policy
- references and provenance

This keeps execution requests auditable, routable, and domain-agnostic across software, finance, robotics, and other domain packs.
