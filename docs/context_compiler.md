# Spice Context Compiler (Internal, v0.1)

## 1. Why Spice Needs a ContextCompiler / MemoryCompiler

Spice needs a compiler layer because cognitive stages require bounded, decision-focused context rather than raw state and event streams.
The compiler transforms available runtime state and memory retrievals into compact, stage-specific context packages for decision, simulation, and reflection.

In Spice, memory is not only storage.
Its primary role is to compile useful context for the next cognitive step.

## 2. Why WorldState Is Not Directly Passed to Cognitive Models

`WorldState` is authoritative and broad.
Directly passing it to models creates three problems:

- excessive payload size and noise
- unstable prompts/inputs across cycles
- weaker control over provenance and confidence boundaries

Cognitive models should receive only relevant slices and summaries.
`WorldState` remains the authoritative runtime projection, while compiled context is a bounded model-facing view.

## 3. The Role of a Shared CompiledContextBase

All compiled contexts should share a common envelope (`CompiledContextBase`) so the runtime and model interfaces remain consistent.

At minimum, the base should carry:

- identity and version (`id`, `context_type`, `schema_version`, `timestamp`)
- linkage (`world_state_id`, `domain`, optional `trace_id`)
- budget metadata (`max_items`, optional token/byte budgets)
- confidence metadata
- provenance/references (`source_refs`, memory retrieval refs, compiler version)
- warnings (e.g., truncation indicators)

This shared base supports auditability and consistent cross-stage tooling.

## 4. DecisionContext

`DecisionContext` is a bounded view for candidate decision generation and selection.

Typical payload:

- current objectives/goals
- active constraints
- top relevant entities, signals, and risks
- resource snapshot
- in-flight intents
- recent outcomes (bounded window)
- relevant references/provenance

Purpose:

- provide enough situational context to produce multiple viable `Decision` candidates without overwhelming the model.

## 5. SimulationContext

`SimulationContext` supports advisory what-if evaluation before execution.

Typical payload:

- `DecisionContext` reference or embedded compact subset
- candidate decisions and/or candidate execution intents
- explicit assumptions
- evaluation axes (success/risk/cost criteria)
- relevant historical analogs (bounded)
- references/provenance/confidence

Purpose:

- predict likely consequences and trade-offs without mutating authoritative state.

## 6. ReflectionContext

`ReflectionContext` supports post-execution analysis.

Typical payload:

- executed path (`Decision`, `ExecutionIntent`, `ExecutionResult`, `Outcome`)
- expected vs actual comparison
- compact state-change summary and linked delta refs
- retrieved related lessons from memory (bounded)
- references/provenance/confidence

Purpose:

- produce structured `Reflection` records and support memory write-back preparation.

## 7. Why Compiled Contexts Must Stay Bounded and Structured

Bounded and structured contexts are required for:

- predictable runtime behavior
- controllable latency/cost
- stable model input quality
- deterministic fallback behavior
- easier debugging and replay

Practical constraints should include top-k limits, time windows, section caps, and truncation reporting.
Raw logs and unbounded payloads should remain in external memory systems, referenced by IDs when needed.

## 8. Deterministic vs Optionally LLM-Assisted Compilation

Deterministic responsibilities (core):

- retrieval filtering and slicing
- relevance scoring defaults
- compaction and truncation
- budget enforcement
- schema validation and serialization

Optional LLM-assisted responsibilities:

- semantic reranking
- abstractive summaries
- scenario narrative augmentation

Design rule:

- LLM outputs are advisory proposals.
- Deterministic compiler logic decides the final compiled context artifact used by runtime/model stages.

This preserves Spice's framework-first OSS design: useful default behavior in open source, with optional intelligence layers that do not bypass deterministic control.


## 9. ContextCompiler Position in the Runtime

The ContextCompiler sits between the deterministic runtime state and cognitive model stages.

Typical runtime flow:

Observation
→ WorldDelta
→ apply_delta
→ WorldState

Before cognitive stages execute:

WorldState
→ ContextCompiler
→ DecisionContext / SimulationContext / ReflectionContext
→ Cognitive models

After reflection:

Reflection
→ memory write-back (via MemoryProvider)



## 10. ContextCompiler and MemoryProvider

ContextCompiler does not own storage.

External memory systems are accessed through the MemoryProvider interface.

Typical sources used by the compiler:

- current WorldState
- recent runtime history
- retrieved memory records from providers

Examples of external providers:

- Redis
- Postgres
- Neo4j
- Pinecone
- Weaviate
- local file storage

The compiler retrieves relevant artifacts from these sources and composes bounded context packages.
