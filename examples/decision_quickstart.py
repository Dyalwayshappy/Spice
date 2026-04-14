from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spice.decision import (
    DecisionGuidanceSupport,
    explain_decision_guidance,
    format_decision_guidance_explanation,
)


HERE = Path(__file__).resolve().parent


def main() -> int:
    support_payload = json.loads(
        (HERE / "decision_support.json").read_text(encoding="utf-8")
    )
    support = DecisionGuidanceSupport.from_dict(support_payload)
    report = explain_decision_guidance(HERE / "decision.md", support=support)
    print(format_decision_guidance_explanation(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
