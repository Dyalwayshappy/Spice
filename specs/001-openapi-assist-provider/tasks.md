# Tasks: OpenAPI-Compatible Assist Provider

**Input**: Design documents from `/specs/001-openapi-assist-provider/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Verification tasks are included because this feature changes user-facing CLI behavior, provider behavior, and secret-handling guarantees already covered by the repository’s test suite.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the feature is aligned with the initialized `.specify` workflow before implementation.

- [X] T001 Confirm feature prerequisites with `.specify/scripts/bash/check-prerequisites.sh --json --include-tasks`
- [X] T002 Review and preserve existing feature documentation under `specs/001-openapi-assist-provider/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core LLM configuration and provider registration work that blocks all user stories

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Extend shared configuration types in `spice/llm/core/types.py` to carry provider-aware relay settings
- [X] T004 Extend override resolution in `spice/llm/core/router.py` to preserve provider-aware relay settings
- [X] T005 Export any new shared configuration surface in `spice/llm/core/__init__.py`
- [X] T006 Add provider registration wiring in `spice/llm/providers/__init__.py` for `openapi_compatible`
- [X] T007 Create the new relay-backed provider module in `spice/llm/providers/openapi_compatible.py`

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Configure Relay-Backed Assist Drafting (Priority: P1) 🎯 MVP

**Goal**: Let `init domain --assist` call a relay endpoint directly with provider selection, model name, base URL, and API key

**Independent Test**: Run relay-backed assist with valid settings and verify the flow reaches the normal draft review and acceptance path without a wrapper script

### Implementation for User Story 1

- [X] T008 [US1] Add CLI flags and help text for `--assist-provider`, `--assist-base-url`, and `--assist-api-key` in `spice/entry/cli.py`
- [X] T009 [US1] Extend assist model resolution in `spice/entry/assist.py` to support provider selection and relay configuration
- [X] T010 [US1] Update assist provider registry construction in `spice/entry/assist.py` to include `openapi_compatible`
- [X] T011 [US1] Ensure assist service backend reporting remains accurate for deterministic, subprocess, and relay-backed runs in `spice/entry/assist.py`
- [X] T012 [US1] Add provider-level success coverage for relay-backed draft generation in `tests/test_llm_core_provider.py`
- [X] T013 [US1] Add CLI integration coverage for successful relay-backed assist runs in `tests/test_entry_init_domain_assist.py`

**Checkpoint**: User Story 1 should be functional and independently testable

---

## Phase 4: User Story 2 - Fail Fast on Invalid Relay Configuration (Priority: P2)

**Goal**: Reject incomplete or inconsistent relay setup before the first draft attempt

**Independent Test**: Run relay-backed assist with missing model name, base URL, or API key and verify the command exits early with a clear message

### Implementation for User Story 2

- [X] T014 [US2] Add provider-specific validation for relay-backed assist configuration in `spice/entry/cli.py`
- [X] T015 [US2] Add assist-side validation helpers for provider-specific required inputs in `spice/entry/assist.py`
- [X] T016 [US2] Normalize relay transport, auth, rate-limit, empty-response, and malformed-response failures in `spice/llm/providers/openapi_compatible.py`
- [X] T017 [US2] Add provider-level failure coverage in `tests/test_llm_core_provider.py`
- [X] T018 [US2] Add CLI integration coverage for missing-input and invalid-combination failures in `tests/test_entry_init_domain_assist.py`
- [X] T019 [US2] Add configuration precedence coverage for new relay fields in `tests/test_llm_client_param_precedence.py`

**Checkpoint**: User Stories 1 and 2 should both work independently

---

## Phase 5: User Story 3 - Protect Secrets in Routine Output (Priority: P3)

**Goal**: Keep relay API keys out of normal logs, artifacts, and normalized errors

**Independent Test**: Run successful and failing relay-backed assist flows and confirm the full API key never appears in CLI output, summaries, or provider diagnostics

### Implementation for User Story 3

- [X] T020 [US3] Add API-key redaction or omission rules to relay-backed provider diagnostics in `spice/llm/providers/openapi_compatible.py`
- [X] T021 [US3] Ensure assist artifact writing and user-facing output do not persist raw relay secrets in `spice/entry/assist.py`
- [X] T022 [US3] Add provider-level redaction coverage in `tests/test_llm_core_provider.py`
- [X] T023 [US3] Add artifact and output hygiene coverage in `tests/test_entry_init_domain_assist.py`

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final verification and cleanup across all user stories

- [X] T024 [P] Update usage examples if needed in `specs/001-openapi-assist-provider/quickstart.md`
- [X] T025 Run targeted verification for `tests/test_llm_core_provider.py`, `tests/test_llm_client_param_precedence.py`, and `tests/test_entry_init_domain_assist.py` in the `codex-work` environment
- [X] T026 Run the full repository test suite covering `tests/` from the repository root in the `codex-work` environment
- [X] T027 Review final user-facing text in `spice/entry/cli.py` and `spice/entry/assist.py` for consistency and backward compatibility

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational completion
- **User Story 2 (Phase 4)**: Depends on Foundational completion and benefits from User Story 1 paths existing
- **User Story 3 (Phase 5)**: Depends on Foundational completion and relay-backed execution paths existing
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Starts after Foundational - defines the MVP path
- **User Story 2 (P2)**: Starts after Foundational - relies on the relay-backed path but remains independently testable
- **User Story 3 (P3)**: Starts after Foundational - relies on relay-backed execution and reporting paths

### Parallel Opportunities

- T003-T007 can be split carefully when file ownership does not overlap
- T012 and T013 can run in parallel after the relay-backed path exists
- T017 and T018 can run in parallel after validation and provider failure paths exist
- T022 and T023 can run in parallel after redaction logic is implemented

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. Validate relay-backed assist happy path

### Incremental Delivery

1. Add relay-backed assist execution
2. Add early validation for incomplete relay configuration
3. Add secret-handling protections and artifact hygiene
4. Run full verification

---

## Notes

- `.specify/memory/constitution.md` is still a placeholder template and should be finalized separately if you want full Spec Kit governance.
- Tasks are intentionally scoped only to the assist drafting flow, matching the existing feature plan.
