from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        sys.stderr.write("portable_cli_agent: empty stdin payload\n")
        return 1

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.stderr.write("portable_cli_agent: payload is not valid JSON\n")
        return 1

    if not isinstance(payload, dict):
        sys.stderr.write("portable_cli_agent: payload must be a JSON object\n")
        return 1

    action_type = str(payload.get("action_type", ""))
    target = payload.get("target", {})
    if not isinstance(target, dict):
        target = {}
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict):
        parameters = {}

    if action_type == "repo.request.review":
        output = {
            "outcome_type": "observation",
            "result_type": "observation",
            "summary": "Portable review completed with one suggestion.",
            "action_type": action_type,
            "target": target,
            "findings": [
                {
                    "severity": "medium",
                    "message": "Consider adding explicit timeout handling in subprocess execution path.",
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        sys.stdout.write(json.dumps(output, ensure_ascii=True))
        return 0

    if action_type == "workspace.run.command":
        command = str(parameters.get("command", "echo no-command"))
        output = {
            "outcome_type": "state_delta",
            "result_type": "state_delta",
            "summary": f"Portable command execution simulated for: {command}",
            "action_type": action_type,
            "target": target,
            "command": command,
            "exit_code": 0,
            "effects": [
                "workspace.validation.completed",
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        sys.stdout.write(json.dumps(output, ensure_ascii=True))
        return 0

    sys.stderr.write(f"portable_cli_agent: unsupported action_type={action_type!r}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
