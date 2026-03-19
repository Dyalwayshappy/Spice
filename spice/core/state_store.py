from __future__ import annotations

from uuid import uuid4

from spice.decision import DecisionTrace
from spice.protocols import Observation, Outcome, ProtocolRecord, WorldState


class StateStore:
    """In-memory state store for the Spice runtime protocol loop."""

    def __init__(self, initial_state: WorldState | None = None) -> None:
        self._state = initial_state or WorldState(id=f"worldstate-{uuid4().hex}")
        self._history: list[ProtocolRecord] = [self._state]

    def get_state(self) -> WorldState:
        return self._state

    def set_state(self, state: WorldState) -> WorldState:
        self._state = state
        return self._state

    def apply_observation(
        self,
        observation: Observation,
        next_state: WorldState | None = None,
    ) -> WorldState:
        self.record(observation)

        if next_state is not None:
            self._state = next_state
            self._state.timestamp = observation.timestamp
            return self._state

        # Fallback merge behavior when no reducer is provided.
        self._state.signals.append(
            {
                "type": observation.observation_type,
                "source": observation.source,
                "attributes": observation.attributes,
                "observation_id": observation.id,
            }
        )
        self._state.provenance["last_observation_id"] = observation.id
        self._state.timestamp = observation.timestamp
        return self._state

    def apply_outcome(
        self,
        outcome: Outcome,
        next_state: WorldState | None = None,
    ) -> WorldState:
        self.record(outcome)

        if next_state is not None:
            self._state = next_state
            self._state.timestamp = outcome.timestamp
            return self._state

        # Fallback merge behavior when no reducer is provided.
        self._state.entities.update(outcome.changes)
        self._state.recent_outcomes.append(
            {
                "outcome_id": outcome.id,
                "status": outcome.status,
                "changes": outcome.changes,
            }
        )
        self._state.provenance["last_outcome_id"] = outcome.id
        self._state.timestamp = outcome.timestamp
        return self._state

    def record(self, record: ProtocolRecord) -> None:
        self._history.append(record)

    @property
    def history(self) -> list[ProtocolRecord]:
        # Return a copy to avoid accidental external mutation of history order.
        return list(self._history)

    @property
    def decision_traces(self) -> list[DecisionTrace]:
        return [
            record
            for record in self._history
            if isinstance(record, DecisionTrace)
        ]
