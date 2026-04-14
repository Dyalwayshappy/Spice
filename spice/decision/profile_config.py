from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from spice.decision.core import DecisionPolicy
from spice.decision.guidance import (
    DecisionGuidance,
    DecisionGuidanceSupport,
    GuidedDecisionPolicy,
    load_decision_guidance,
    parse_decision_guidance,
)


DEFAULT_PROFILE_PACKAGE = "spice.decision.profiles"
DEFAULT_DECISION_PROFILE_NAME = "default.decision.md"
DEFAULT_SUPPORT_PROFILE_NAME = "default_support.json"
DEFAULT_LOCAL_DECISION_PROFILE = Path(".spice/decision/decision.md")
DEFAULT_LOCAL_SUPPORT_PROFILE = Path(".spice/decision/support/default_support.json")


@dataclass(slots=True)
class DecisionProfileInitReport:
    profile_path: Path
    support_path: Path | None
    copied_profile: bool
    copied_support: bool
    overwritten: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile_path": str(self.profile_path),
            "support_path": str(self.support_path) if self.support_path else "",
            "copied_profile": self.copied_profile,
            "copied_support": self.copied_support,
            "overwritten": self.overwritten,
        }


def load_default_decision_guidance() -> DecisionGuidance:
    return load_decision_guidance_from_profile(DEFAULT_DECISION_PROFILE_NAME)


def load_decision_guidance_from_profile(profile_name: str) -> DecisionGuidance:
    resource = _profile_resource(profile_name)
    return parse_decision_guidance(
        resource.read_text(encoding="utf-8"),
        source_path=f"{DEFAULT_PROFILE_PACKAGE}/{profile_name}",
    )


def load_default_decision_support() -> DecisionGuidanceSupport:
    payload = json.loads(
        _profile_resource(DEFAULT_SUPPORT_PROFILE_NAME).read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        raise ValueError("Default decision support payload must be an object.")
    return DecisionGuidanceSupport.from_dict(payload)


def init_decision_profile(
    *,
    output: str | Path | None = None,
    force: bool = False,
    include_support: bool = True,
    support_output: str | Path | None = None,
) -> DecisionProfileInitReport:
    profile_path = Path(output) if output is not None else DEFAULT_LOCAL_DECISION_PROFILE
    support_path = (
        Path(support_output)
        if support_output is not None
        else profile_path.parent / "support" / DEFAULT_SUPPORT_PROFILE_NAME
    )

    if profile_path.exists() and not force:
        raise FileExistsError(
            f"{profile_path} already exists. Use --force to overwrite it."
        )
    if include_support and support_path.exists() and not force:
        raise FileExistsError(
            f"{support_path} already exists. Use --force to overwrite it."
        )

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_text = _profile_resource(DEFAULT_DECISION_PROFILE_NAME).read_text(
        encoding="utf-8"
    )
    profile_path.write_text(profile_text, encoding="utf-8")

    copied_support = False
    if include_support:
        support_path.parent.mkdir(parents=True, exist_ok=True)
        support_text = _profile_resource(DEFAULT_SUPPORT_PROFILE_NAME).read_text(
            encoding="utf-8"
        )
        support_path.write_text(support_text, encoding="utf-8")
        copied_support = True

    return DecisionProfileInitReport(
        profile_path=profile_path,
        support_path=support_path if include_support else None,
        copied_profile=True,
        copied_support=copied_support,
        overwritten=force,
    )


def guided_policy_from_profile(
    base_policy: DecisionPolicy,
    profile_path: str | Path = DEFAULT_LOCAL_DECISION_PROFILE,
    *,
    support: DecisionGuidanceSupport | None = None,
) -> GuidedDecisionPolicy:
    """Load a decision profile and explicitly wrap a policy with guidance.

    Runtime support comes from the active policy/domain adapter unless callers
    explicitly pass a support object.
    """

    guidance = load_decision_guidance(profile_path)
    return GuidedDecisionPolicy(base_policy, guidance, support=support)


def _profile_resource(name: str):
    return files(DEFAULT_PROFILE_PACKAGE).joinpath(name)
