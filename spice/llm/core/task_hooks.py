from __future__ import annotations

from enum import Enum


class LLMTaskHook(str, Enum):
    ASSIST_DRAFT = "assist_draft"
    PERCEPTION_INTERPRET = "perception_interpret"
    DECISION_PROPOSE = "decision_propose"
    SIMULATION_ADVISE = "simulation_advise"
    REFLECTION_SYNTHESIZE = "reflection_synthesize"
