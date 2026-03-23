# Research: OpenAPI-Compatible Assist Provider

**Feature**: [spec.md](/opt/project/Spice/specs/001-openapi-assist-provider/spec.md)  
**Date**: 2026-03-23

## Decision 1: Scope the first implementation to the assist drafting flow only

- Decision: Add relay support only to `init domain --assist` for this feature.
- Rationale: The feature request, current spec, and current user pain are all focused on assist drafting. The generated-domain advisory path uses the same LLM abstractions but serves a separate activation flow and would materially increase scope, regression risk, and review size.
- Alternatives considered:
  - Extend both assist drafting and generated domain advisory in one change.
    - Rejected because it broadens CLI, environment, provider, and scaffold behavior at the same time.
  - Implement relay support only through a wrapper example.
    - Rejected because it does not satisfy the requested first-class provider support.

## Decision 2: Register a new provider instead of overloading the subprocess provider

- Decision: Introduce a dedicated `openapi_compatible` provider in the LLM provider registry.
- Rationale: The existing provider model is explicit and registry-based. A first-class provider keeps routing, testing, error handling, and provider-specific validation clearer than overloading `subprocess` with HTTP behavior.
- Alternatives considered:
  - Add HTTP behavior behind the existing `subprocess` provider.
    - Rejected because it mixes unrelated execution modes and weakens operator understanding.
  - Bypass the provider registry and call the relay directly from assist code.
    - Rejected because it breaks the current layering and would make later reuse harder.

## Decision 3: Extend model configuration to carry relay connection settings

- Decision: Extend LLM model configuration and override objects to include relay-specific connection fields needed by the new provider.
- Rationale: Current configuration only carries `provider_id`, `model_id`, and request-shaping fields. Relay-backed execution needs structured connection data that should travel through the same resolution pipeline as existing model overrides.
- Alternatives considered:
  - Encode base URL and API key inside the model string.
    - Rejected because it is brittle, hard to validate, and unsafe for logging.
  - Store provider-specific settings only inside request metadata.
    - Rejected because metadata is request-oriented and not part of model resolution semantics.

## Decision 4: Keep compatibility with existing assist flows and defaults

- Decision: Preserve deterministic assist as the default and keep subprocess assist unchanged.
- Rationale: Existing tests and documented flows rely on deterministic and subprocess behavior. The new provider should be opt-in rather than changing defaults.
- Alternatives considered:
  - Make `openapi_compatible` the default provider whenever `--assist-model` is present.
    - Rejected because it would silently reinterpret existing subprocess commands.
  - Remove subprocess support from assist.
    - Rejected because it would be a breaking change.

## Decision 5: Validate provider-specific inputs before the first draft attempt

- Decision: Fail fast during assist setup when `openapi_compatible` is selected without a base URL, API key, or model name.
- Rationale: Early validation gives better UX, reduces ambiguous errors, and avoids half-created assist output that appears to come from a model call.
- Alternatives considered:
  - Allow the provider to fail later during the first request.
    - Rejected because it delays a deterministic validation error into a transport error.
  - Auto-fallback missing values from implicit defaults.
    - Rejected because there is no safe universal default for relay settings.

## Decision 6: Treat `--assist-model` as the model name for the new provider

- Decision: Keep the existing `--assist-model` flag and reinterpret it as model name only when `--assist-provider openapi_compatible` is selected.
- Rationale: This preserves the current public option surface while still satisfying the feature requirement for configurable model selection.
- Alternatives considered:
  - Introduce a separate `--assist-model-name` flag.
    - Rejected because it duplicates an existing concept and complicates CLI usage.
  - Keep `--assist-model` as subprocess-only and add an entirely new flag for relay models.
    - Rejected because it fragments the user experience without enough benefit.

## Decision 7: Use a simple single-request chat relay pattern for provider transport

- Decision: Plan around a single synchronous text-in/text-out relay request pattern that produces one draft response per attempt.
- Rationale: The existing assist flow is single-shot per attempt and expects one returned text payload. A synchronous relay pattern matches current behavior and keeps retry/edit logic unchanged.
- Alternatives considered:
  - Streaming or multi-step relay interactions.
    - Rejected because the current assist architecture has no need for partial output handling.
  - Relay-specific asynchronous jobs or polling.
    - Rejected because it adds complexity outside current feature scope.

## Decision 8: Prefer standard-library HTTP transport for the first implementation

- Decision: Implement relay transport without adding a third-party dependency.
- Rationale: The package currently has no runtime dependencies declared. Preserving that property keeps installation simple and aligns with the lightweight runtime approach already used elsewhere in the project.
- Alternatives considered:
  - Add a dedicated HTTP client dependency.
    - Rejected for the first pass because the transport needs are narrow and synchronous.

## Decision 9: Redact secrets at both validation/reporting and provider-error layers

- Decision: Apply redaction in assist setup and in provider error normalization so secrets do not appear in normal output, artifacts, or expected failure messages.
- Rationale: API keys can leak through direct status output, exception messages, raw payloads, or serialized artifacts. Redaction at multiple layers is safer than relying on a single call site.
- Alternatives considered:
  - Redact only at CLI print points.
    - Rejected because errors and artifacts can bypass those prints.
  - Store the API key in artifacts for reproducibility.
    - Rejected because it conflicts with the feature’s secrecy requirement.

## Decision 10: Add focused tests at three layers

- Decision: Extend tests at provider, assist setup, and CLI integration layers.
- Rationale: The feature spans provider execution, model resolution, validation UX, and artifact hygiene. Covering only one layer would miss regressions.
- Alternatives considered:
  - Add only CLI integration tests.
    - Rejected because provider-specific error mapping would remain under-tested.
  - Add only unit tests.
    - Rejected because CLI behavior and artifact side effects are part of the user-facing contract.
