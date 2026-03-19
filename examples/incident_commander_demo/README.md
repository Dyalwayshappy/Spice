# Checkout Incident in 5 Cycles: Why History-Aware Decisions Win

This is the flagship Incident Commander demo for Spice.

## What This Demo Proves
Spice is a **decision runtime** with deterministic evidence, not only orchestration glue.

Core proof claims:

1. The same current signal can lead to different decisions when prior outcomes differ.
2. A history-aware candidate policy can outperform a history-agnostic baseline policy.
3. Replay + Offline Shadow make the difference auditable and reproducible.

Key metric:

`candidate_cycles_to_stable < baseline_cycles_to_stable`

Presentation layers in this demo:

- `README` = story and onboarding
- `CLI` = deterministic evidence
- `Visualizer` = presentation clarity for video/screenshots

## Story In 6 Scenes
1. **Trigger**: checkout incident opens right after deploy; error rate and latency stay high.
2. **Baseline Loop**: baseline keeps selecting `rollback_release` under unchanged pressure.
3. **Divergence**: after rollback failure, candidate switches action under the same current signal.
4. **Recovery**: candidate mitigation stabilizes service.
5. **Proactive Closure**: candidate performs one `request_hotfix` follow-up step.
6. **Proof Complete**: replay/shadow reports show measurable candidate improvement.

## Run In 60 Seconds
From repository root:

```bash
python3 examples/incident_commander_demo/run_replay_baseline.py
python3 examples/incident_commander_demo/run_replay_candidate.py
python3 examples/incident_commander_demo/run_shadow_compare.py
```

## CLI Proof
The three runners provide deterministic evidence:

- `run_replay_baseline.py`
- `run_replay_candidate.py`
- `run_shadow_compare.py`

With current demo inputs, expected proof lines are:

- `baseline_cycles_to_stable=not_reached`
- `candidate_cycles_to_stable=3`
- `divergent_cycle_after_rollback_failure=2 (baseline=incident.rollback_release, candidate=incident.disable_feature_flag)`
- `proactive_request_hotfix_cycle=3`
- `proof_metric_candidate_lt_baseline=True`

## Generate Canonical Artifact
All story/CLI/visual outputs should read from one canonical artifact:

```bash
python3 examples/incident_commander_demo/generate_demo_artifact.py
```

This generates:

- `examples/incident_commander_demo/demo_timeline.json`

## Open The Visualizer
Serve static files locally:

```bash
python3 -m http.server 8000
```

Then open:

- `http://localhost:8000/examples/incident_commander_demo/visualizer/`

The visualizer is read-only and consumes only `demo_timeline.json`.

## Cycle Summary Table
Current canonical path (from `demo_timeline.json`):

| Cycle | Scene | Observed Signal | Previous Outcome | Baseline Action | Candidate Action | Stable After Cycle (B/C) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Trigger | High error + high latency post-deploy | None | `rollback_release` | `rollback_release` | `false / false` |
| 2 | Divergence | Same high signal | Rollback failed | `rollback_release` | `disable_feature_flag` | `false / true` |
| 3 | Proactive Closure | Same observed pressure signal | Candidate recovered in prior cycle | `rollback_release` | `request_hotfix` | `false / true` |
| 4 | Monitoring | Same observed pressure signal | Candidate hotfix requested | `rollback_release` | `monitor` | `false / true` |
| 5 | Proof Complete | Same observed pressure signal | Candidate remains stable | `rollback_release` | `monitor` | `false / true` |

## Divergence Moment
`Cycle 2` is the key divergence:

- `Cycle 1` rollback fails.
- `Cycle 2` observed signal remains high.
- Baseline repeats rollback.
- Candidate switches to `disable_feature_flag` because visible history now includes rollback failure.

## Proactive Step
`Cycle 3` is the proactive follow-up:

- Candidate is already stabilized after its mitigation step.
- Candidate still performs one `request_hotfix` to reduce immediate recurrence risk.
- This is explicitly tracked as `proactive_request_hotfix_cycle=3`.

## Hidden-Truth Boundary
The replay fixture is observation-only. Hidden simulator truth stays internal.

- Hidden truth exists only inside `incident_simulator.py` (for example, `_HiddenTruth` internals).
- Policies read only visible world state/history produced by reducers.
- Hidden truth is never written into replay observations or world state.
- Replay/shadow proof remains deterministic and auditable.
