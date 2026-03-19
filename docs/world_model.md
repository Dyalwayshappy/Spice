# Spice World Model (Internal, v0.1)

## 1. Why a World Model Is Needed

A decision runtime needs a structured representation of the environment so decisions are made from a consistent state, not from isolated events.
In Spice, the world model is the shared memory between observation, decision, execution, and reflection steps.
Without this layer, each cycle would re-interpret raw inputs independently and lose continuity.

## 2. WorldState

`WorldState` is the current decision-relevant projection of the world.
It stores normalized state such as entities, relations, goals, resources, risks, signals, active intents, recent outcomes, confidence, provenance, and domain-specific state.

`WorldState` intentionally does not store raw logs or raw event history.
Raw inputs are high-volume and execution-facing; `WorldState` is decision-facing.
This keeps the model compact, interpretable, and stable for strategy selection.

## 3. WorldDelta

Spice models transitions as `WorldDelta` changes rather than full state rewrites.
`WorldDelta` expresses explicit operations (upsert/remove) and patches for specific state areas.

This approach provides:

- clear state transition intent
- deterministic update behavior
- easier auditing of how state changed
- domain-specific flexibility without changing core state mechanics

## 4. Observation -> WorldDelta -> WorldState

Current deterministic transition path:

`Observation -> WorldDelta -> apply_delta(WorldState, WorldDelta) -> WorldState`

In runtime flow:

1. an observation enters the domain reducer
2. the domain reducer constructs a `WorldDelta`
3. `apply_delta()` deterministically applies that delta to the current `WorldState`
4. the updated state becomes the new decision context

The same pattern is used for outcomes: domain reducer emits a delta, and core applies it deterministically.

## 5. Domain Reducers

`DomainPack` implementations are responsible for translation, not core mutation mechanics.
They convert domain observations and outcomes into `WorldDelta` instances.

In the current reference implementation (`SoftwareDomainPack`):

- `reduce_observation()` builds an observation-driven `WorldDelta`
- `reduce_outcome()` builds an outcome-driven `WorldDelta`
- both call `apply_delta()` to produce the next `WorldState`

This preserves a stable core while allowing domain-specific interpretation.

## 6. Decision Relevance Principle

Spice follows a strict principle: store only what affects decisions.

The world model should contain:

- state needed for choosing the next action
- confidence/provenance needed for trust and traceability
- concise summaries of recent execution effects

It should avoid storing raw telemetry streams, unfiltered logs, or full event dumps.

## 7. Future Extensions

The current model is designed to support future capabilities without changing core semantics:

- context compilation from structured state and recent deltas
- longer-horizon reasoning over goals, risks, and outcomes
- richer domain-specific state through `domain_state` and domain reducers

These extensions can build on the existing deterministic foundation (`WorldDelta` + `apply_delta`) rather than replacing it.
