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
    agent_path = THIS_DIR / "echo_agent.py"
    transport = SubprocessSDEPTransport([sys.executable, str(agent_path)])
    executor = SDEPExecutor(transport)

    success_intent = ExecutionIntent(
        id="intent.sdep.demo.success",
        intent_type="demo.action",
        status="planned",
        objective={"id": "obj-1", "description": "Demonstrate SDEP success path."},
        executor_type="external-agent",
        target={"kind": "demo_service", "id": "checkout-api"},
        operation={"name": "demo.echo", "mode": "sync", "dry_run": False},
        input_payload={"ticket_id": "INC-001"},
        parameters={"priority": "high"},
        constraints=[],
        success_criteria=[{"id": "exec.ok", "description": "Agent returns success."}],
        failure_policy={"strategy": "fail_fast", "max_retries": 0},
        refs=[],
        provenance={"source": "sdep_adapter_demo"},
    )

    failed_intent = ExecutionIntent(
        id="intent.sdep.demo.fail",
        intent_type="demo.action",
        status="planned",
        objective={"id": "obj-2", "description": "Demonstrate SDEP error path."},
        executor_type="external-agent",
        target={"kind": "demo_service", "id": "checkout-api"},
        operation={"name": "demo.fail", "mode": "sync", "dry_run": False},
        input_payload={"ticket_id": "INC-002"},
        parameters={},
        constraints=[],
        success_criteria=[{"id": "exec.ok", "description": "Agent returns success."}],
        failure_policy={"strategy": "fail_fast", "max_retries": 0},
        refs=[],
        provenance={"source": "sdep_adapter_demo"},
    )

    success_result = executor.execute(success_intent)
    failed_result = executor.execute(failed_intent)

    print("SDEP Adapter Demo")
    print("success_result:")
    print(json.dumps(_serialize_result(success_result), indent=2, ensure_ascii=True))
    print("failed_result:")
    print(json.dumps(_serialize_result(failed_result), indent=2, ensure_ascii=True))
    return 0


def _serialize_result(result) -> dict:
    return {
        "id": result.id,
        "status": result.status,
        "executor": result.executor,
        "output": dict(result.output),
        "error": result.error,
        "refs": list(result.refs),
        "attributes_keys": sorted(result.attributes.keys()),
        "sdep_status": result.attributes.get("sdep", {}).get("response", {}).get("status"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
