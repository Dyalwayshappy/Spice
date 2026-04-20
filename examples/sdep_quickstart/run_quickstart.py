"""
SDEP Quickstart Runner

Demonstrates the SDEP execute.request / execute.response round-trip against
the minimal_executor.py in this directory.

Two paths are shown:
  1. Direct JSON pipe  — manually builds and prints the exchange (no Spice dep)
  2. Spice SDEPExecutor — uses the Spice runtime adapter (requires spice package)

Run from repo root:
    python3 examples/sdep_quickstart/run_quickstart.py

Or run only the standalone path (no Spice package required):
    python3 examples/sdep_quickstart/run_quickstart.py --standalone
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]

EXECUTOR_SCRIPT = THIS_DIR / "minimal_executor.py"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="SDEP Quickstart")
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run without the spice package (direct subprocess JSON only).",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("SDEP Quickstart")
    print("=" * 60)

    if args.standalone:
        return _run_standalone()

    # Try Spice adapter first; fall back to standalone if not installed.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        return _run_with_spice()
    except ImportError:
        print(
            "[info] spice package not found in sys.path — "
            "falling back to standalone mode.\n"
        )
        return _run_standalone()


# ---------------------------------------------------------------------------
# Path 1: Standalone — direct subprocess JSON (no Spice dependency)
# ---------------------------------------------------------------------------

def _run_standalone() -> int:
    print("\n--- Standalone path (direct stdin/stdout JSON) ---\n")

    request = _build_execute_request(
        action_type="quickstart.greet",
        target={"kind": "demo_service", "id": "sdep-quickstart"},
        parameters={"greeting": "Hello from SDEP quickstart"},
        input_payload={"note": "standalone runner"},
    )

    print("Request:")
    print(json.dumps(request, indent=2))
    print()

    response = _call_executor(request)

    print("Response:")
    print(json.dumps(response, indent=2))
    print()

    status = response.get("status")
    outcome_status = response.get("outcome", {}).get("status")
    print(f"Result: protocol={status}, outcome={outcome_status}")
    print()

    # Also show agent.describe.request path
    print("--- Capability discovery (agent.describe.request) ---\n")
    describe_req = _build_describe_request()
    describe_resp = _call_executor(describe_req)
    print("Describe Response:")
    print(json.dumps(describe_resp, indent=2))
    print()

    return 0


def _call_executor(request: dict) -> dict:
    """Pipe request JSON to the executor subprocess and capture response."""
    result = subprocess.run(
        [sys.executable, str(EXECUTOR_SCRIPT)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.stderr:
        print(f"[executor stderr]: {result.stderr.strip()}", file=sys.stderr)
    if not result.stdout.strip():
        return {"error": "executor produced no output", "stderr": result.stderr}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "executor output is not valid JSON", "raw": result.stdout}


# ---------------------------------------------------------------------------
# Path 2: Spice SDEPExecutor adapter
# ---------------------------------------------------------------------------

def _run_with_spice() -> int:
    from spice.executors import SDEPExecutor, SubprocessSDEPTransport  # type: ignore
    from spice.protocols import ExecutionIntent  # type: ignore

    print("\n--- Spice SDEPExecutor path ---\n")

    transport = SubprocessSDEPTransport([sys.executable, str(EXECUTOR_SCRIPT)])
    executor = SDEPExecutor(transport)

    intent = ExecutionIntent(
        id=f"intent.quickstart.{uuid4().hex[:8]}",
        intent_type="quickstart.greet",
        status="planned",
        objective={"id": "obj-qs-1", "description": "Demonstrate SDEP quickstart."},
        executor_type="external-agent",
        target={"kind": "demo_service", "id": "sdep-quickstart"},
        operation={"name": "quickstart.greet", "mode": "sync", "dry_run": False},
        input_payload={"note": "spice runner"},
        parameters={"greeting": "Hello from Spice SDEPExecutor"},
        constraints=[],
        success_criteria=[
            {"id": "exec.ok", "description": "Executor returns success."}
        ],
        failure_policy={"strategy": "fail_fast", "max_retries": 0},
        refs=[],
        provenance={"source": "sdep_quickstart"},
    )

    result = executor.execute(intent)

    print("ExecutionResult:")
    print(f"  id:          {result.id}")
    print(f"  status:      {result.status}")
    print(f"  executor:    {result.executor}")
    print(f"  output keys: {sorted(result.output.keys())}")
    if result.error:
        print(f"  error:       {result.error}")
    sdep_attrs = result.attributes.get("sdep", {})
    sdep_status = sdep_attrs.get("response", {}).get("status")
    print(f"  sdep.status: {sdep_status}")
    print()
    return 0


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------

def _build_execute_request(
    *,
    action_type: str,
    target: dict,
    parameters: dict | None = None,
    input_payload: dict | None = None,
) -> dict:
    req_id = f"sdep-req-qs-{uuid4().hex[:12]}"
    return {
        "protocol": "sdep",
        "sdep_version": "0.1",
        "message_type": "execute.request",
        "message_id": f"sdep-msg-{uuid4().hex}",
        "request_id": req_id,
        "timestamp": _now(),
        "sender": {
            "id": "spice.runtime",
            "name": "Spice Runtime",
            "version": "0.1.0",
            "vendor": "Spice",
            "implementation": "spice-runtime",
            "role": "brain",
        },
        "idempotency_key": f"qs.{req_id}",
        "execution": {
            "action_type": action_type,
            "target": target,
            "parameters": parameters or {},
            "input": input_payload or {},
            "constraints": [],
            "success_criteria": [
                {"id": "exec.ok", "description": "Executor returns success."}
            ],
            "failure_policy": {"strategy": "fail_fast", "max_retries": 0},
            "mode": "sync",
            "dry_run": False,
            "metadata": {"source": "sdep_quickstart"},
        },
        "metadata": {"source": "sdep_quickstart"},
    }


def _build_describe_request() -> dict:
    req_id = f"sdep-req-describe-{uuid4().hex[:12]}"
    return {
        "protocol": "sdep",
        "sdep_version": "0.1",
        "message_type": "agent.describe.request",
        "message_id": f"sdep-msg-{uuid4().hex}",
        "request_id": req_id,
        "timestamp": _now(),
        "sender": {
            "id": "spice.runtime",
            "name": "Spice Runtime",
            "version": "0.1.0",
            "vendor": "Spice",
            "implementation": "spice-runtime",
            "role": "brain",
        },
        "metadata": {},
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
