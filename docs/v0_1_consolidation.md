# Spice v0.1 Architecture Consolidation

## 1. Purpose

This document freezes the v0.1 architecture direction for Spice before onboarding and broader domain/adapter expansion.
Some current implementation details are transitional, but the guardrails below are explicit and normative for v0.1.

## 2. Context Compiler Ownership

Current v0.1 implementation is hybrid:

- runtime compiles `DecisionContext` and `ReflectionContext`
- domain pack may compile `SimulationContext`

Long-term target:

- runtime owns context orchestration across all cognitive stages
- domain packs consume compiled contexts instead of orchestrating shared compiler flow

## 3. Cognitive Model Inputs

- Compiled context is the primary input for cognitive models.
- Minimal state envelope exists for identity, provenance, and fallback compatibility only.
- Long-term direction is context-first model interfaces.

## 4. Reflection Write-Back

v0.1 scope:

- write back raw `Reflection` records only

Deferred:

- derived lesson artifacts
- memory distillation pipelines

## 5. DomainPack vs ContextCompiler Boundary

`ContextCompiler` responsibilities:

- retrieval
- bounded slicing
- truncation and budget enforcement
- deterministic serialization
- provenance/confidence envelope

`DomainPack` responsibilities:

- domain interpretation
- policy and hints
- candidate generation
- stage-specific reasoning hooks

Long-term guardrail:

- domain packs should not own shared compiler workflow orchestration

## 6. Explicit Out-of-Scope for v0.1

The following are deferred:

- advanced memory compaction pipelines
- learned or semantic retrieval ranking
- automatic lesson artifact generation
- transactional or event-sourced memory consistency
- multi-agent shared-memory semantics
- long-horizon planner/runtime scheduling
- advanced LLM-driven compression loops

## 7. Core Guardrail

v0.1 targets bounded usefulness, not product-level memory intelligence.
