# Feature Specification: OpenAPI-Compatible Assist Provider

**Feature Branch**: `001-openapi-assist-provider`  
**Created**: 2026-03-23  
**Status**: Draft  
**Input**: User description: "`- openapi_compatible provider - 支持 base_url - 支持 api_key - 支持模型名 - CLI 增加 --assist-base-url / --assist-api-key / --assist-provider 我需要现在的项目支持这些功能`"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure Relay-Backed Assist Drafting (Priority: P1)

As a user initializing a new domain with assist enabled, I want to select an OpenAPI-compatible relay provider and provide a model name, base URL, and API key directly from the CLI so I can draft a DomainSpec without writing a wrapper script.

**Why this priority**: This is the primary value of the feature. Without this path, the requested relay integration does not exist.

**Independent Test**: Can be fully tested by running `init domain --assist` with the relay-backed provider and verifying that the flow reaches the existing assist draft review step using the supplied relay settings.

**Acceptance Scenarios**:

1. **Given** a user runs domain initialization with assist enabled, **When** the user selects `openapi_compatible` and supplies a model name, base URL, and API key, **Then** the assist flow drafts the domain specification through the relay-backed provider.
2. **Given** a relay-backed assist draft succeeds, **When** the user reviews and accepts the draft, **Then** the existing scaffold generation and artifact flow completes without changing the post-draft review experience.

---

### User Story 2 - Fail Fast on Invalid Relay Configuration (Priority: P2)

As a user selecting the relay-backed assist provider, I want the command to validate required provider settings before the first model attempt so that setup problems are reported clearly and immediately.

**Why this priority**: Once the primary relay path exists, the next most important requirement is predictable setup behavior. Early validation reduces ambiguity and support cost.

**Independent Test**: Can be fully tested by running `init domain --assist` with `openapi_compatible` and omitting one required input at a time, then verifying that the command stops before the drafting request begins and reports the missing input.

**Acceptance Scenarios**:

1. **Given** a user selects `openapi_compatible`, **When** the base URL is missing, **Then** the command exits before the first draft attempt and explains that the base URL is required.
2. **Given** a user selects `openapi_compatible`, **When** the API key or model name is missing, **Then** the command exits before the first draft attempt and explains which required value is missing.
3. **Given** a user selects a non-relay assist provider, **When** relay-specific options are absent, **Then** existing assist behavior continues without requiring relay-specific configuration.

---

### User Story 3 - Protect Secrets in Routine Output (Priority: P3)

As a user supplying relay credentials, I want the assist flow to avoid exposing the API key in normal logs, summaries, and artifacts so that relay access remains protected during successful runs and expected failures.

**Why this priority**: Secret handling is critical, but it depends on the relay path and validation behavior existing first.

**Independent Test**: Can be fully tested by running successful and failing relay-backed assist flows and verifying that the full API key does not appear in command output, normalized errors, or written assist artifacts.

**Acceptance Scenarios**:

1. **Given** a user supplies an API key for `openapi_compatible`, **When** the command reports progress or writes assist artifacts, **Then** the full API key is not shown in plain text.
2. **Given** a relay authentication or transport failure occurs, **When** the command reports the error, **Then** the message remains actionable without exposing the raw secret.

### Edge Cases

- The user selects `openapi_compatible` but provides an invalid or unreachable relay base URL.
- The relay rejects the supplied API key.
- The relay returns empty output or malformed JSON that cannot be parsed into the assist contract.
- The relay returns a valid JSON payload that still fails `DomainSpec` validation.
- The user supplies relay-specific flags while using a different assist provider.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support an assist provider option named `openapi_compatible` for `init domain --assist`.
- **FR-002**: The system MUST allow users to select the assist provider explicitly from the CLI.
- **FR-003**: The system MUST expose CLI options named `--assist-provider`, `--assist-base-url`, and `--assist-api-key`.
- **FR-004**: The system MUST preserve the existing `--assist-model` option and treat it as the model name when `openapi_compatible` is selected.
- **FR-005**: The system MUST allow users to provide a relay base URL, API key, and model name when using `openapi_compatible`.
- **FR-006**: The system MUST validate that provider selection and provider-specific inputs are internally consistent before the first assist draft attempt.
- **FR-007**: The system MUST reject relay-backed assist execution when the base URL, API key, or model name is missing.
- **FR-008**: The system MUST preserve existing deterministic assist behavior when relay-backed configuration is not selected.
- **FR-009**: The system MUST preserve existing subprocess assist behavior when relay-backed configuration is not selected.
- **FR-010**: The system MUST route relay-backed assist draft requests through a first-class provider selection path rather than requiring a custom subprocess wrapper.
- **FR-011**: The system MUST keep the existing assist review, retry, edit, acceptance, artifact-writing, and scaffold-generation flow unchanged after a draft response is returned.
- **FR-012**: The system MUST redact or omit the full API key from routine CLI output, persisted assist artifacts, and normalized provider error reporting.
- **FR-013**: The system MUST provide clear user-facing failure messages for relay transport failures, authentication failures, rate limits, malformed responses, and invalid draft payloads.
- **FR-014**: The system MUST record which assist provider backend was used for a completed or failed assist drafting session.

### Key Entities *(include if feature involves data)*

- **Assist Provider Selection**: Represents the selected drafting backend for assist, including deterministic, subprocess, and `openapi_compatible`.
- **Assist Relay Configuration**: Represents user-supplied relay connection data, including base URL, authentication secret, and model name.
- **Assist Draft Session**: Represents one assist run, including provider identity, attempt count, draft validation results, and review outcome.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can start a relay-backed assist draft in a single command invocation without writing a wrapper script.
- **SC-002**: In validation testing, 100% of relay-backed assist runs with complete and correct settings reach the existing draft review step.
- **SC-003**: In validation testing, 100% of relay-backed assist runs with a missing base URL, API key, or model name fail before the first draft request is sent and identify the missing input.
- **SC-004**: No routine CLI progress line or generated assist artifact exposes a full API key during successful runs or expected failure cases.
- **SC-005**: Existing deterministic and subprocess assist flows continue to complete successfully without requiring relay-specific options.
