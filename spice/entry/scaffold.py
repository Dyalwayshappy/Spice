from __future__ import annotations

import json
from pathlib import Path
from pprint import pformat
from typing import Any

from spice.entry.spec import (
    DomainSpec,
    derive_domain_pack_class_name,
    derive_package_name,
)


def render_scaffold_files(
    spec: DomainSpec,
    *,
    with_llm: bool = False,
) -> dict[str, str]:
    """Render deterministic scaffold files from a validated DomainSpec."""
    package_name = derive_package_name(spec.domain.id)
    class_name = derive_domain_pack_class_name(spec.domain.id)

    return {
        "domain_spec.json": _render_domain_spec_json(spec),
        "README.md": _render_readme(
            spec,
            package_name=package_name,
            class_name=class_name,
            with_llm=with_llm,
        ),
        "run_demo.py": _render_run_demo(spec, package_name=package_name, class_name=class_name),
        f"{package_name}/__init__.py": _render_package_init(package_name=package_name, class_name=class_name),
        f"{package_name}/vocabulary.py": _render_vocabulary(spec),
        f"{package_name}/reducers.py": _render_reducers(spec),
        f"{package_name}/domain_pack.py": _render_domain_pack(
            spec,
            package_name=package_name,
            class_name=class_name,
            with_llm=with_llm,
        ),
    }


def write_scaffold(
    spec: DomainSpec,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
    with_llm: bool = False,
) -> list[Path]:
    root = Path(output_dir)
    file_map = render_scaffold_files(spec, with_llm=with_llm)
    written: list[Path] = []

    for relative_path in sorted(file_map.keys()):
        target = root / relative_path
        if target.exists() and not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite existing file without overwrite=True: {target}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file_map[relative_path], encoding="utf-8")
        written.append(target)
    return written


def _render_domain_spec_json(spec: DomainSpec) -> str:
    return json.dumps(spec.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _render_readme(
    spec: DomainSpec,
    *,
    package_name: str,
    class_name: str,
    with_llm: bool,
) -> str:
    readme = (
        f"# {spec.domain.id} Domain Scaffold\n\n"
        "Generated from `domain_spec.json`.\n\n"
        "## Included Files\n\n"
        f"- `{package_name}/domain_pack.py`: `{class_name}` runtime integration skeleton\n"
        f"- `{package_name}/reducers.py`: deterministic reducer stubs\n"
        f"- `{package_name}/vocabulary.py`: vocabulary/constants from DomainSpec\n"
        "- `run_demo.py`: scaffold smoke runner\n\n"
        "## Run Demo\n\n"
        "```bash\n"
        "python3 run_demo.py\n"
        "```\n"
    )
    if with_llm:
        readme += (
            "\n## Optional LLM Activation\n\n"
            "This scaffold includes opt-in domain-level LLM decision + simulation wiring.\n"
            "The deterministic provider path is a dev/test stub fallback.\n\n"
            "Set `SPICE_DOMAIN_MODEL` to override the model/provider command:\n\n"
            "```bash\n"
            "SPICE_DOMAIN_MODEL=\"ollama run qwen2.5\" python3 run_demo.py\n"
            "```\n\n"
            "You can replace the generated policy wiring in `domain_pack.py` with custom logic.\n"
        )
    return readme


def _render_run_demo(spec: DomainSpec, *, package_name: str, class_name: str) -> str:
    observations_literal = _py_literal([item.to_dict() for item in spec.demo.observations])
    return (
        "from __future__ import annotations\n\n"
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        "\n"
        "def _ensure_spice_importable() -> None:\n"
        "    here = Path(__file__).resolve().parent\n"
        "    for candidate in [here, *here.parents]:\n"
        "        marker = candidate / 'spice' / '__init__.py'\n"
        "        if not marker.exists():\n"
        "            continue\n"
        "        candidate_path = str(candidate)\n"
        "        if candidate_path not in sys.path:\n"
        "            sys.path.insert(0, candidate_path)\n"
        "        return\n\n"
        "\n"
        "_ensure_spice_importable()\n\n"
        "from spice.core import SpiceRuntime\n"
        "from spice.executors import MockExecutor\n\n"
        f"from {package_name}.domain_pack import {class_name}\n\n"
        "\n"
        f"DEMO_OBSERVATIONS = {observations_literal}\n\n"
        "\n"
        "def main() -> int:\n"
        f"    runtime = SpiceRuntime(domain_pack={class_name}(), executor=MockExecutor())\n"
        "    cycle_outputs = []\n"
        "    for observation in DEMO_OBSERVATIONS:\n"
        "        result = runtime.run_cycle(\n"
        "            observation_type=str(observation['type']),\n"
        "            source=str(observation['source']),\n"
        "            attributes=dict(observation.get('attributes', {})),\n"
        "            metadata=dict(observation.get('metadata', {})),\n"
        "        )\n"
        "        cycle_outputs.append(\n"
        "            {\n"
        "                'decision_action': result['decision'].selected_action,\n"
        "                'planned_operation': result['execution_intent'].operation.get('name', ''),\n"
        "                'execution_operation': result['execution_result'].output.get('operation', ''),\n"
        "                'execution_status': result['execution_result'].status,\n"
        "            }\n"
        "        )\n\n"
        "    print('SPICE demo cycle completed')\n"
        "    print(f'domain={runtime.domain_pack.domain_name}')\n"
        "    print(f'cycles={len(cycle_outputs)}')\n"
        "    if cycle_outputs:\n"
        "        print('last_cycle=' + json.dumps(cycle_outputs[-1], sort_keys=True))\n"
        "    return 0\n\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    )


def _render_package_init(*, package_name: str, class_name: str) -> str:
    return (
        f"from {package_name}.domain_pack import {class_name}\n\n"
        f"__all__ = [{class_name!r}]\n"
    )


def _render_vocabulary(spec: DomainSpec) -> str:
    state_fields_literal = _py_literal([field.to_dict() for field in spec.state.fields])
    actions_literal = _py_literal([action.to_dict() for action in spec.actions])
    return (
        "from __future__ import annotations\n\n"
        "\"\"\"Generated vocabulary and constants from DomainSpec v1.\"\"\"\n\n"
        f"DOMAIN_ID = {spec.domain.id!r}\n"
        f"STATE_ENTITY_ID = {spec.state.entity_id!r}\n"
        + _render_list("OBSERVATION_TYPES", spec.vocabulary.observation_types)
        + "\n\n"
        + _render_list("ACTION_TYPES", spec.vocabulary.action_types)
        + "\n\n"
        + _render_list("OUTCOME_TYPES", spec.vocabulary.outcome_types)
        + "\n\n"
        f"STATE_FIELDS = {state_fields_literal}\n\n"
        f"ACTIONS = {actions_literal}\n\n"
        "ACTION_CATALOG = {\n"
        "    action['id']: action\n"
        "    for action in ACTIONS\n"
        "}\n\n"
        "OPERATION_TO_EXPECTED_OUTCOME = {\n"
        "    action['executor']['operation']: action['expected_outcome_type']\n"
        "    for action in ACTIONS\n"
        "}\n\n"
        f"DEFAULT_ACTION = {spec.decision.default_action!r}\n"
    )


def _render_reducers(spec: DomainSpec) -> str:
    fallback_outcome_type = spec.vocabulary.outcome_types[0]
    package_name = derive_package_name(spec.domain.id)
    return (
        "from __future__ import annotations\n\n"
        "from typing import Any\n"
        "from uuid import uuid4\n\n"
        "from spice.protocols import (\n"
        "    Decision,\n"
        "    DeltaOp,\n"
        "    ExecutionIntent,\n"
        "    ExecutionResult,\n"
        "    Observation,\n"
        "    Outcome,\n"
        "    Reflection,\n"
        "    WorldDelta,\n"
        "    WorldState,\n"
        ")\n\n"
        f"from {package_name}.vocabulary import (\n"
        "    ACTION_CATALOG,\n"
        "    DEFAULT_ACTION,\n"
        "    DOMAIN_ID,\n"
        "    OPERATION_TO_EXPECTED_OUTCOME,\n"
        "    OUTCOME_TYPES,\n"
        "    STATE_ENTITY_ID,\n"
        "    STATE_FIELDS,\n"
        ")\n\n"
        "\n"
        "def observation_to_delta(state: WorldState, observation: Observation) -> WorldDelta:\n"
        "    entity = _current_entity_snapshot(state)\n"
        "    _apply_state_defaults(entity)\n"
        "    for field in STATE_FIELDS:\n"
        "        name = str(field.get('name', ''))\n"
        "        if not name:\n"
        "            continue\n"
        "        if name in observation.attributes:\n"
        "            entity[name] = observation.attributes[name]\n"
        "    entity['last_observation_type'] = observation.observation_type\n\n"
        "    return WorldDelta(\n"
        "        id=f'delta-{uuid4().hex}',\n"
        "        source_kind='observation',\n"
        "        source_id=observation.id,\n"
        "        entity_ops=[DeltaOp(op='upsert', id=STATE_ENTITY_ID, value=entity)],\n"
        "        signal_ops=[\n"
        "            DeltaOp(\n"
        "                op='upsert',\n"
        "                id=f'signal-{observation.id}',\n"
        "                value={\n"
        "                    'type': observation.observation_type,\n"
        "                    'source': observation.source,\n"
        "                    'observation_id': observation.id,\n"
        "                },\n"
        "            )\n"
        "        ],\n"
        "        resource_patch={'observation_count': state.resources.get('observation_count', 0) + 1},\n"
        "        provenance_patch={\n"
        "            'last_observation_id': observation.id,\n"
        "            'last_observation_source': observation.source,\n"
        "        },\n"
        "    )\n\n"
        "\n"
        "def outcome_to_delta(state: WorldState, outcome: Outcome) -> WorldDelta:\n"
        "    entity = _current_entity_snapshot(state)\n"
        "    _apply_state_defaults(entity)\n"
        "    patch = outcome.changes.get(STATE_ENTITY_ID, {})\n"
        "    if isinstance(patch, dict):\n"
        "        for field in STATE_FIELDS:\n"
        "            name = str(field.get('name', ''))\n"
        "            if name in patch:\n"
        "                entity[name] = patch[name]\n"
        "    entity['last_outcome_status'] = outcome.status\n\n"
        "    return WorldDelta(\n"
        "        id=f'delta-{uuid4().hex}',\n"
        "        source_kind='outcome',\n"
        "        source_id=outcome.id,\n"
        "        entity_ops=[DeltaOp(op='upsert', id=STATE_ENTITY_ID, value=entity)],\n"
        "        provenance_patch={'last_outcome_id': outcome.id},\n"
        "        confidence_patch={'latest_outcome_status': outcome.status},\n"
        "        recent_outcome_additions=[\n"
        "            {\n"
        "                'outcome_id': outcome.id,\n"
        "                'status': outcome.status,\n"
        "                'changes': outcome.changes,\n"
        "            }\n"
        "        ],\n"
        "    )\n\n"
        "\n"
        "def build_default_decision(state: WorldState) -> Decision:\n"
        "    selected_action = DEFAULT_ACTION\n"
        "    if selected_action not in ACTION_CATALOG:\n"
        "        selected_action = next(iter(ACTION_CATALOG)) if ACTION_CATALOG else ''\n"
        "    return Decision(\n"
        "        id=f'dec-{uuid4().hex}',\n"
        "        decision_type=DOMAIN_ID + '.placeholder',\n"
        "        status='proposed',\n"
        "        selected_action=selected_action,\n"
        "        refs=[state.id],\n"
        "        attributes={'reason': 'generated_domain_default_decision'},\n"
        "    )\n\n"
        "\n"
        "def build_execution_intent(decision: Decision) -> ExecutionIntent:\n"
        "    selected_action = decision.selected_action or DEFAULT_ACTION\n"
        "    action_spec = ACTION_CATALOG.get(selected_action)\n"
        "    if action_spec is None and ACTION_CATALOG:\n"
        "        selected_action = next(iter(ACTION_CATALOG))\n"
        "        action_spec = ACTION_CATALOG[selected_action]\n"
        "    if action_spec is None:\n"
        "        action_spec = {\n"
        "            'id': selected_action,\n"
        "            'executor': {'type': 'mock', 'operation': selected_action, 'parameters': {}},\n"
        f"            'expected_outcome_type': {fallback_outcome_type!r},\n"
        "        }\n"
        "    executor_spec = action_spec.get('executor', {})\n"
        "    operation_name = str(executor_spec.get('operation', selected_action))\n"
        "    executor_type = str(executor_spec.get('type', 'mock'))\n"
        "    executor_parameters_raw = executor_spec.get('parameters', {})\n"
        "    executor_parameters = (\n"
        "        dict(executor_parameters_raw)\n"
        "        if isinstance(executor_parameters_raw, dict)\n"
        "        else {}\n"
        "    )\n"
        "    expected_outcome_type = str(\n"
        "        action_spec.get('expected_outcome_type')\n"
        f"        or {fallback_outcome_type!r}\n"
        "    )\n"
        "    return ExecutionIntent(\n"
        "        id=f'intent-{uuid4().hex}',\n"
        "        intent_type=DOMAIN_ID + '.placeholder',\n"
        "        status='planned',\n"
        "        objective={\n"
        "            'id': f'objective-{decision.id}',\n"
        "            'description': 'Generated scaffold objective placeholder.',\n"
        "        },\n"
        "        executor_type=executor_type,\n"
        "        target={'kind': DOMAIN_ID + '_entity', 'id': STATE_ENTITY_ID},\n"
        "        operation={'name': operation_name, 'mode': 'sync', 'dry_run': False},\n"
        "        input_payload={\n"
        "            'decision_id': decision.id,\n"
        "            'selected_action': selected_action,\n"
        "            'expected_outcome_type': expected_outcome_type,\n"
        "        },\n"
        "        parameters=executor_parameters,\n"
        "        constraints=[],\n"
        "        success_criteria=[\n"
        "            {\n"
        "                'id': 'generated.success',\n"
        "                'description': 'Operation returns success status.',\n"
        "            }\n"
        "        ],\n"
        "        failure_policy={'strategy': 'retry', 'max_retries': 1},\n"
        "        refs=[decision.id],\n"
        "        provenance={\n"
        "            'decision_id': decision.id,\n"
        "            'domain': DOMAIN_ID,\n"
        "            'action_id': selected_action,\n"
        "            'expected_outcome_type': expected_outcome_type,\n"
        "        },\n"
        "    )\n\n"
        "\n"
        "def build_outcome_from_result(result: ExecutionResult) -> Outcome:\n"
        "    operation_name = str(result.output.get('operation', ''))\n"
        "    outcome_type = OPERATION_TO_EXPECTED_OUTCOME.get(operation_name, '')\n"
        "    if not outcome_type:\n"
        f"        outcome_type = OUTCOME_TYPES[0] if OUTCOME_TYPES else {fallback_outcome_type!r}\n"
        "    return Outcome(\n"
        "        id=f'out-{uuid4().hex}',\n"
        "        outcome_type=outcome_type,\n"
        "        status='applied',\n"
        "        changes={},\n"
        "        refs=[result.id],\n"
        "        attributes={'execution_status': result.status},\n"
        "    )\n\n"
        "\n"
        "def build_reflection(\n"
        "    outcome: Outcome,\n"
        "    *,\n"
        "    execution_result: ExecutionResult | None = None,\n"
        "    simulation_artifact: dict[str, Any] | None = None,\n"
        ") -> Reflection:\n"
        "    insights: dict[str, Any] = {'summary': 'Generated scaffold reflection placeholder.'}\n"
        "    if execution_result is not None:\n"
        "        insights['execution_status'] = execution_result.status\n"
        "    if simulation_artifact:\n"
        "        insights['simulation'] = simulation_artifact\n"
        "    return Reflection(\n"
        "        id=f'ref-{uuid4().hex}',\n"
        "        reflection_type=DOMAIN_ID + '.placeholder',\n"
        "        status='recorded',\n"
        "        refs=[outcome.id],\n"
        "        insights=insights,\n"
        "    )\n\n"
        "\n"
        "def _current_entity_snapshot(state: WorldState) -> dict[str, Any]:\n"
        "    entity_raw = state.entities.get(STATE_ENTITY_ID)\n"
        "    if isinstance(entity_raw, dict):\n"
        "        return dict(entity_raw)\n"
        "    return {'entity_id': STATE_ENTITY_ID}\n\n"
        "\n"
        "def _apply_state_defaults(entity: dict[str, Any]) -> None:\n"
        "    for field in STATE_FIELDS:\n"
        "        name = str(field.get('name', ''))\n"
        "        if not name:\n"
        "            continue\n"
        "        if name in entity:\n"
        "            continue\n"
        "        if 'default' in field:\n"
        "            entity[name] = field['default']\n"
    )


def _render_domain_pack(
    spec: DomainSpec,
    *,
    package_name: str,
    class_name: str,
    with_llm: bool,
) -> str:
    if not with_llm:
        return (
            "from __future__ import annotations\n\n"
            "from spice.domain.base import DomainPack\n"
            "from spice.memory import DecisionContext, ReflectionContext\n"
            "from spice.protocols import (\n"
            "    Decision,\n"
            "    ExecutionIntent,\n"
            "    ExecutionResult,\n"
            "    Observation,\n"
            "    Outcome,\n"
            "    Reflection,\n"
            "    WorldState,\n"
            "    apply_delta,\n"
            ")\n\n"
            f"from {package_name} import reducers\n"
            f"from {package_name}.vocabulary import DOMAIN_ID\n\n"
            "\n"
            f"class {class_name}(DomainPack):\n"
            "    \"\"\"Generated deterministic DomainPack skeleton.\"\"\"\n\n"
            "    domain_name = DOMAIN_ID\n\n"
            "    def reduce_observation(self, state: WorldState, observation: Observation) -> WorldState:\n"
            "        delta = reducers.observation_to_delta(state, observation)\n"
            "        return apply_delta(state, delta)\n\n"
            "    def reduce_outcome(self, state: WorldState, outcome: Outcome) -> WorldState:\n"
            "        delta = reducers.outcome_to_delta(state, outcome)\n"
            "        return apply_delta(state, delta)\n\n"
            "    def decide(\n"
            "        self,\n"
            "        state: WorldState,\n"
            "        *,\n"
            "        decision_context: DecisionContext | None = None,\n"
            "    ) -> Decision:\n"
            "        return reducers.build_default_decision(state)\n\n"
            "    def plan_execution(self, decision: Decision) -> ExecutionIntent:\n"
            "        return reducers.build_execution_intent(decision)\n\n"
            "    def interpret_execution_result(self, result: ExecutionResult) -> Outcome:\n"
            "        return reducers.build_outcome_from_result(result)\n\n"
            "    def reflect(\n"
            "        self,\n"
            "        state: WorldState,\n"
            "        outcome: Outcome,\n"
            "        *,\n"
            "        execution_result: ExecutionResult | None = None,\n"
            "        reflection_context: ReflectionContext | None = None,\n"
            "    ) -> Reflection:\n"
            "        simulation_artifact = None\n"
            "        if execution_result is not None:\n"
            "            simulation_artifact = execution_result.attributes.get('simulation')\n"
            "        return reducers.build_reflection(\n"
            "            outcome,\n"
            "            execution_result=execution_result,\n"
            "            simulation_artifact=simulation_artifact,\n"
            "        )\n"
        )

    return (
        "from __future__ import annotations\n\n"
        "import os\n\n"
        "from spice.decision import DecisionObjective\n"
        "from spice.domain.base import DomainPack\n"
        "from spice.llm.services import DOMAIN_MODEL_ENV, build_domain_llm_decision_policy\n"
        "from spice.memory import DecisionContext, ReflectionContext\n"
        "from spice.protocols import (\n"
        "    Decision,\n"
        "    ExecutionIntent,\n"
        "    ExecutionResult,\n"
        "    Observation,\n"
        "    Outcome,\n"
        "    Reflection,\n"
        "    WorldState,\n"
        "    apply_delta,\n"
        ")\n\n"
        f"from {package_name} import reducers\n"
        f"from {package_name}.vocabulary import ACTION_TYPES, DOMAIN_ID\n\n"
        "\n"
        f"class {class_name}(DomainPack):\n"
        "    \"\"\"Generated DomainPack with optional domain-level LLM decision/simulation activation.\"\"\"\n\n"
        "    domain_name = DOMAIN_ID\n\n"
        "    def __init__(\n"
        "        self,\n"
        "        *,\n"
        "        llm_enabled: bool = True,\n"
        "        model_override: str | None = None,\n"
        "        **kwargs,\n"
        "    ) -> None:\n"
        "        super().__init__(**kwargs)\n"
        "        resolved_model = model_override\n"
        "        if resolved_model is None:\n"
        "            resolved_model = os.environ.get(DOMAIN_MODEL_ENV)\n"
        "        self._llm_policy = None\n"
        "        if llm_enabled:\n"
        "            self._llm_policy = build_domain_llm_decision_policy(\n"
        "                model=resolved_model,\n"
        "                domain=DOMAIN_ID,\n"
        "                allowed_actions=tuple(ACTION_TYPES),\n"
        "            )\n\n"
        "    def reduce_observation(self, state: WorldState, observation: Observation) -> WorldState:\n"
        "        delta = reducers.observation_to_delta(state, observation)\n"
        "        return apply_delta(state, delta)\n\n"
        "    def reduce_outcome(self, state: WorldState, outcome: Outcome) -> WorldState:\n"
        "        delta = reducers.outcome_to_delta(state, outcome)\n"
        "        return apply_delta(state, delta)\n\n"
        "    def decide(\n"
        "        self,\n"
        "        state: WorldState,\n"
        "        *,\n"
        "        decision_context: DecisionContext | None = None,\n"
        "    ) -> Decision:\n"
        "        if self._llm_policy is None:\n"
        "            return reducers.build_default_decision(state)\n\n"
        "        candidates = self._llm_policy.propose(state, decision_context)\n"
        "        if not candidates:\n"
        "            return reducers.build_default_decision(state)\n\n"
        "        decision = self._llm_policy.select(\n"
        "            candidates,\n"
        "            DecisionObjective(),\n"
        "            [],\n"
        "        )\n"
        "        if state.id not in decision.refs:\n"
        "            decision.refs.append(state.id)\n"
        "        return decision\n\n"
        "    def plan_execution(self, decision: Decision) -> ExecutionIntent:\n"
        "        return reducers.build_execution_intent(decision)\n\n"
        "    def interpret_execution_result(self, result: ExecutionResult) -> Outcome:\n"
        "        return reducers.build_outcome_from_result(result)\n\n"
        "    def reflect(\n"
        "        self,\n"
        "        state: WorldState,\n"
        "        outcome: Outcome,\n"
        "        *,\n"
        "        execution_result: ExecutionResult | None = None,\n"
        "        reflection_context: ReflectionContext | None = None,\n"
        "    ) -> Reflection:\n"
        "        simulation_artifact = None\n"
        "        if execution_result is not None:\n"
        "            simulation_artifact = execution_result.attributes.get('simulation')\n"
        "        return reducers.build_reflection(\n"
        "            outcome,\n"
        "            execution_result=execution_result,\n"
        "            simulation_artifact=simulation_artifact,\n"
        "        )\n"
    )


def _render_list(name: str, values: tuple[str, ...]) -> str:
    lines = [f"{name} = ["]
    for value in values:
        lines.append(f"    {value!r},")
    lines.append("]")
    return "\n".join(lines)


def _py_literal(value: Any) -> str:
    return pformat(value, width=88, sort_dicts=True)
