# Domain Starter v0.1

`spice/domain_starter` is the primary scaffold for creating a new Spice domain.

## Starter Contents

- `vocabulary.py`: editable domain vocabulary
- `reducers.py`: reducer/helper examples
- `domain_pack.py`: runtime-compatible `DomainPack` skeleton
- `adapters/example_adapter.py`: simple input-to-`Observation` adapter example

## Onboarding Sequence

1. Copy this starter into your domain package (for example `spice/domain/my_domain`).
2. Edit `vocabulary.py`:
   - observation kinds
   - entity kinds
   - relation kinds
   - signal kinds
   - operation kinds
3. Update reducer logic in `reducers.py`:
   - `observation_to_delta`
   - `outcome_to_delta`
4. Customize `StarterDomainPack` in `domain_pack.py`.
5. Connect one or two adapters (start from `ExampleInputAdapter`).
   You can also use reference adapters in `spice.adapters`:
   - `FileObservationAdapter` (JSON/JSONL)
   - `WebhookAdapter` (payload normalization helper)
6. Run the deterministic runtime loop before adding model hooks.
7. Optionally add LLM hooks and external memory providers.

## Notes

- Keep reducers deterministic.
- `WorldState` must only change through `WorldDelta -> apply_delta`.
- LLM hooks are optional and should remain advisory.
