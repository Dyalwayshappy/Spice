# Quickstart: OpenAPI-Compatible Assist Provider

## Goal

Draft a new domain specification by calling a relay endpoint directly from the assist flow.

## Example 1: Existing deterministic flow

```bash
python -m spice.entry init domain my_domain \
  --assist \
  --assist-brief-file brief.txt \
  --output ./my_domain_out \
  --no-run
```

## Example 2: Relay-backed assist flow

```bash
python -m spice.entry init domain my_domain \
  --assist \
  --assist-provider openapi_compatible \
  --assist-brief-file brief.txt \
  --assist-model relay-model-name \
  --assist-base-url https://relay.example.com/v1 \
  --assist-api-key YOUR_RELAY_KEY \
  --output ./my_domain_out \
  --no-run
```

## Example 3: Explicit subprocess assist flow

```bash
python -m spice.entry init domain my_domain \
  --assist \
  --assist-provider subprocess \
  --assist-brief-file brief.txt \
  --assist-model "ollama run qwen2.5" \
  --output ./my_domain_out \
  --no-run
```

## Expected Behavior

1. The command captures the brief.
2. The command validates provider-specific inputs before drafting begins.
3. The assist flow drafts a DomainSpec using the relay-backed provider.
4. The user reviews the returned draft.
5. Accepted output is written using the existing assist artifact and scaffold flow.

## Failure Examples

### Missing API key

The command should fail before the first draft attempt and explain that the API key is required for the selected provider.

### Invalid relay endpoint

The command should report a transport failure without exposing the raw API key.

### Invalid relay payload

The command should report that the provider returned an unusable response and preserve the existing retry flow.
