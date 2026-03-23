# Contract: Assist CLI Configuration

## Command Surface

The `init domain --assist` flow will support the following assist-provider-related options:

- `--assist-provider`
- `--assist-model`
- `--assist-base-url`
- `--assist-api-key`
- existing assist options such as brief source and retry count

## Provider Selection Contract

### Supported values

- `deterministic`
- `subprocess`
- `openapi_compatible`

### Behavioral rules

- If `--assist-provider` is omitted, the current default behavior remains in place.
- If `--assist-provider deterministic` is selected, relay-specific options are not required.
- If `--assist-provider subprocess` is selected, the existing subprocess command behavior remains in place.
- If `--assist-provider openapi_compatible` is selected, the command must require a model name, base URL, and API key before drafting begins.

## Validation Matrix

| Provider | `--assist-model` meaning | `--assist-base-url` | `--assist-api-key` |
|----------|--------------------------|---------------------|--------------------|
| `deterministic` | optional existing override token | ignored or rejected predictably | ignored or rejected predictably |
| `subprocess` | subprocess command | ignored or rejected predictably | ignored or rejected predictably |
| `openapi_compatible` | model name | required | required |

## Output Contract

- CLI progress output must identify the resolved backend without printing the raw API key.
- Validation failures must explain which required input is missing or invalid.
- Assist summary artifacts must preserve backend identity while omitting the raw API key.
