from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from uuid import uuid4


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        _write(
            {
                "status": "failed",
                "error": "Invalid native request JSON.",
                "error_code": "native.request.invalid_json",
                "retryable": False,
                "metadata": {"agent": "example_non_sdep_agent"},
            }
        )
        return 0

    if not isinstance(payload, dict):
        _write(
            {
                "status": "failed",
                "error": "Native request must be a JSON object.",
                "error_code": "native.request.invalid_payload",
                "retryable": False,
                "metadata": {"agent": "example_non_sdep_agent"},
            }
        )
        return 0

    action_type = str(payload.get("action_type", "")).strip()
    if not action_type:
        _write(
            {
                "status": "failed",
                "error": "action_type is required.",
                "error_code": "native.request.missing_action",
                "retryable": False,
                "metadata": {"agent": "example_non_sdep_agent"},
            }
        )
        return 0

    if action_type == "demo.native.fail":
        _write(
            {
                "status": "failed",
                "error": "Intentional native-agent failure for demo/testing.",
                "error_code": "native.operation.failed",
                "retryable": False,
                "metadata": {"agent": "example_non_sdep_agent"},
            }
        )
        return 0

    target = payload.get("target")
    if not isinstance(target, dict):
        target = {}
    input_payload = payload.get("input_payload")
    if not isinstance(input_payload, dict):
        input_payload = {}
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {}

    _write(
        {
            "status": "success",
            "execution_id": f"native-exec-{uuid4().hex}",
            "outcome_type": "observation",
            "output": {
                "native_agent": "example_non_sdep_agent",
                "action_type": action_type,
                "target": target,
                "echo_input_payload": input_payload,
                "echo_parameters": parameters,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            },
            "metadata": {"agent": "example_non_sdep_agent"},
        }
    )
    return 0


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())

