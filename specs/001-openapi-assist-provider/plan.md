# Implementation Plan: OpenAPI-Compatible Assist Provider

**Branch**: `001-openapi-assist-provider` | **Date**: 2026-03-23 | **Spec**: [spec.md](/opt/project/Spice/specs/001-openapi-assist-provider/spec.md)
**Input**: Feature specification from `/specs/001-openapi-assist-provider/spec.md`

## Summary

Add a first-class `openapi_compatible` assist provider so `init domain --assist` can call a relay endpoint directly using a selected model name, base URL, and API key. The implementation will extend the shared LLM configuration path, add a relay-backed provider, update assist CLI validation, preserve deterministic and subprocess compatibility, and enforce API-key redaction in normal output and artifacts.

## Technical Context

**Language/Version**: Python 3.10+ package, validated in the `codex-work` conda environment  
**Primary Dependencies**: Python standard library plus the project’s existing internal LLM provider abstractions  
**Storage**: Local files for generated assist artifacts and summaries  
**Testing**: `unittest` via `python -m unittest discover -s tests -p 'test_*.py'`  
**Target Platform**: Linux CLI environment  
**Project Type**: Python library and CLI tooling  
**Performance Goals**: Relay-backed assist requests should preserve the current single-request draft workflow and remain within existing assist timeout expectations  
**Constraints**: Preserve backward compatibility for deterministic and subprocess assist flows, avoid leaking API keys, and avoid unnecessary runtime dependencies  
**Scale/Scope**: One new assist provider, shared config extension, CLI flag additions, and focused test coverage for assist and provider behavior

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still an unfilled template in this repository, so no project-specific constitutional rules can be enforced yet. For this feature, the working gates are:

- Preserve backward compatibility for existing deterministic and subprocess assist flows
- Keep the implementation within the current provider abstraction
- Do not expose raw API keys in routine output, artifacts, or normalized provider diagnostics
- Maintain current dependency minimalism unless a new dependency is justified
- Cover user-facing and provider-facing behavior with tests

Initial gate result: PASS

## Project Structure

### Documentation (this feature)

```text
specs/001-openapi-assist-provider/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### Source Code (repository root)

```text
spice/
├── entry/
│   ├── cli.py
│   └── assist.py
├── llm/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── router.py
│   │   └── types.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── deterministic.py
│   │   └── subprocess.py
│   └── services/
│       ├── assist_draft.py
│       └── domain_advisory.py
└── ...

tests/
├── test_entry_init_domain_assist.py
├── test_llm_client_param_precedence.py
├── test_llm_core_provider.py
└── ...
```

**Structure Decision**: This feature fits the existing single Python package layout. Implementation is concentrated in `spice/entry`, `spice/llm/core`, `spice/llm/providers`, and corresponding `tests/` files.

## Complexity Tracking

No constitution violations or extra complexity exceptions are currently required.

## Phase 0: Research

Research output: [research.md](/opt/project/Spice/specs/001-openapi-assist-provider/research.md)

Resolved decisions:

1. Limit the first implementation to assist drafting.
2. Add a first-class `openapi_compatible` provider.
3. Extend model configuration to carry relay connection settings.
4. Preserve deterministic and subprocess defaults.
5. Validate relay inputs before the first model attempt.
6. Reuse `--assist-model` as model name for the new provider.
7. Use single-request synchronous relay execution.
8. Keep the first implementation dependency-light.
9. Redact secrets in both provider and assist/reporting layers.
10. Add tests at provider, setup, and integration layers.

## Phase 1: Design & Contracts

### Design outputs

- Data model: [data-model.md](/opt/project/Spice/specs/001-openapi-assist-provider/data-model.md)
- CLI contract: [assist-cli.md](/opt/project/Spice/specs/001-openapi-assist-provider/contracts/assist-cli.md)
- Relay provider contract: [assist-relay-provider.md](/opt/project/Spice/specs/001-openapi-assist-provider/contracts/assist-relay-provider.md)
- Usage examples: [quickstart.md](/opt/project/Spice/specs/001-openapi-assist-provider/quickstart.md)

### Agent context update

The repository now contains `.specify/scripts/bash/update-agent-context.sh`, but this feature planning pass did not introduce a new external runtime technology beyond the relay-backed provider path. No agent-context update is required before implementation.

## Post-Design Constitution Check

- Backward compatibility: PASS
- Provider abstraction integrity: PASS
- Secret handling: PASS if raw secrets remain excluded from artifacts and provider diagnostics
- Dependency minimization: PASS if implementation uses existing standard-library capabilities
- Test coverage: PASS with provider, CLI integration, and artifact hygiene coverage

## Ready for Task Execution

Planning is complete. The next step is execution against [tasks.md](/opt/project/Spice/specs/001-openapi-assist-provider/tasks.md) on branch `001-openapi-assist-provider`.
