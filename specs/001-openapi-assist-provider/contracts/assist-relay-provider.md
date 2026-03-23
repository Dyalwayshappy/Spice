# Contract: OpenAPI-Compatible Relay Provider

## Purpose

Define the provider-facing contract for relay-backed assist drafting.

## Input Contract

The provider receives:

- provider identity
- model name
- relay base URL
- API key
- assist prompt text
- request-shaping values such as timeout and response format hint

## Execution Contract

- The provider performs one synchronous relay request for each assist draft attempt.
- The provider returns one normalized text response on success.
- The provider maps transport, authentication, rate-limit, and malformed-response failures into the project’s normalized provider error types.

## Output Contract

On success, the provider must return:

- `provider_id`
- `model_id`
- `output_text`
- `raw_payload`
- `finish_reason`
- `usage`
- `latency_ms`
- `request_id`

## Error Contract

Expected failure classes:

- transport failure
- authentication or authorization failure
- rate-limit or throttling failure
- malformed or empty relay response

## Security Contract

- The provider must not include the raw API key in normalized errors.
- The provider must not include the raw API key in the returned raw payload.
- Any provider diagnostic content that references credentials must use redacted text.
