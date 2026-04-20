"""Thin observation bridge for Spice + Hermes demos."""

from spice_hermes_bridge.observations.builder import build_observation
from spice_hermes_bridge.observations.schema import (
    ObservationValidationIssue,
    StructuredObservation,
    validate_observation,
)

__all__ = [
    "ObservationValidationIssue",
    "StructuredObservation",
    "build_observation",
    "validate_observation",
]
