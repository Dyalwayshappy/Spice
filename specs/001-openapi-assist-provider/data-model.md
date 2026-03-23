# Data Model: OpenAPI-Compatible Assist Provider

## Entity: AssistProviderSelection

Describes which drafting backend the assist flow will use.

### Fields

- `provider_id`: stable provider identifier
- `display_name`: user-facing label for logs and summaries
- `requires_model_name`: whether the provider requires a model name
- `requires_base_url`: whether the provider requires relay endpoint configuration
- `requires_api_key`: whether the provider requires an authentication secret

### Validation Rules

- `provider_id` must be non-empty
- `provider_id` must resolve to a registered provider
- provider requirements must be enforced before the first assist draft attempt

## Entity: AssistRelayConfiguration

Describes the connection settings for relay-backed assist drafting.

### Fields

- `provider_id`: selected provider
- `base_url`: relay endpoint root supplied by the user
- `api_key`: authentication secret supplied by the user
- `model_name`: selected model identifier
- `timeout_sec`: request timeout used for the model call
- `response_format_hint`: expected response shape for the assist contract

### Validation Rules

- `base_url` is required when `provider_id = openapi_compatible`
- `api_key` is required when `provider_id = openapi_compatible`
- `model_name` is required when `provider_id = openapi_compatible`
- `base_url` must be non-empty after trimming whitespace
- `api_key` must be non-empty after trimming whitespace
- `model_name` must be non-empty after trimming whitespace
- `api_key` must never be persisted in clear text in assist artifacts or routine logs

## Entity: AssistModelOverride

Represents the resolved override values passed into the assist draft service.

### Fields

- `provider_id`: resolved provider choice
- `model_name`: resolved model selector
- `base_url`: resolved relay endpoint, if applicable
- `api_key`: resolved secret, if applicable
- `temperature`
- `max_tokens`
- `timeout_sec`
- `response_format_hint`

### Relationships

- produced from CLI inputs and assist defaults
- consumed by the LLM client and selected provider

## Entity: AssistDraftSession

Represents a single assist drafting run from setup through user acceptance.

### Fields

- `brief`
- `model_backend`
- `attempt_count`
- `draft_result`
- `validation_errors`
- `review_decision`
- `action_bindings`

### State Transitions

1. `configured`
2. `drafting`
3. `draft_invalid` or `draft_ready`
4. `accepted`, `retrying`, `editing`, or `cancelled`

### Validation Rules

- a session cannot enter `drafting` with unresolved provider-specific required inputs
- `model_backend` must identify the resolved provider path used for the run
- persisted session artifacts may contain provider identity but must not contain the raw API key

## Entity: ProviderExecutionResult

Represents the normalized result returned by a provider execution attempt.

### Fields

- `provider_id`
- `model_id`
- `output_text`
- `raw_payload`
- `finish_reason`
- `usage`
- `latency_ms`
- `request_id`

### Validation Rules

- `output_text` must be non-empty on success
- provider-specific raw payload content must not expose secrets
- transport, auth, rate-limit, and malformed-response failures must normalize into existing provider error classes
