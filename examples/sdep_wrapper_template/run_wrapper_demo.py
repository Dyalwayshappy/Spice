from __future__ import annotations

import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spice.executors import SDEPExecutor, SubprocessSDEPTransport
from spice.protocols import ExecutionIntent


def main() -> int:
    wrapper_path = THIS_DIR / "wrapper_main.py"
    native_agent_path = THIS_DIR / "adapters" / "example_non_sdep_agent.py"
    wrapper_command = [
        sys.executable,
        str(wrapper_path),
        "--adapter",
        "subprocess-json",
        "--agent-command",
        f"{sys.executable} {native_agent_path}",
    ]
    transport = SubprocessSDEPTransport(wrapper_command, timeout_seconds=20.0)
    executor = SDEPExecutor(transport)

    intent = ExecutionIntent(
        id="intent.wrapper.demo.success",
        intent_type="personal.assistant.execute",
        status="planned",
        objective={"id": "obj-wrapper-1", "description": "Wrapper demo execute path."},
        executor_type="external-agent",
        target={"kind": "external.service", "id": "research"},
        operation={"name": "personal.gather_evidence", "mode": "sync", "dry_run": False},
        input_payload={"question": "collect one evidence snapshot"},
        parameters={"priority": "normal"},
        constraints=[],
        success_criteria=[{"id": "exec.ok", "description": "native adapter returns success"}],
        failure_policy={"strategy": "fail_fast", "max_retries": 0},
        refs=[],
        provenance={"source": "run_wrapper_demo"},
    )

    result = executor.execute(intent)
    description = executor.describe(action_types=["personal.gather_evidence"])

    print("SDEP Wrapper Template Demo")
    print("execution_result:")
    print(json.dumps(_serialize_result(result), indent=2, ensure_ascii=True))
    print("describe_response:")
    print(json.dumps(description, indent=2, ensure_ascii=True))
    return 0


def _serialize_result(result) -> dict[str, object]:
    return {
        "id": result.id,
        "status": result.status,
        "result_type": result.result_type,
        "executor": result.executor,
        "output": dict(result.output),
        "error": result.error,
        "refs": list(result.refs),
        "has_sdep_payload": bool(result.attributes.get("sdep")),
    }


if __name__ == "__main__":
    raise SystemExit(main())

