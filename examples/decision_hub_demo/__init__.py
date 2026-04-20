"""Simulation-driven decision demo domain for Spice.

This package is intentionally example-scoped. It demonstrates a complete
decision loop without promoting the demo's state/context contracts into Spice
core APIs.
"""

from examples.decision_hub_demo.policy import (
    DecisionHubCandidatePolicy,
    DecisionHubRecommendationRunner,
)
from examples.decision_hub_demo.reducer import ingest_observation
from examples.decision_hub_demo.execution_adapter import ExecutionFeedbackAdapter
from examples.decision_hub_demo.state import new_world_state

__all__ = [
    "DecisionHubCandidatePolicy",
    "DecisionHubRecommendationRunner",
    "ExecutionFeedbackAdapter",
    "ingest_observation",
    "new_world_state",
]
