from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from typing import Any


EPISODE_SCHEMA_VERSION = "0.1"

REQUIRED_REF_KEYS = (
    "observation_id",
    "decision_id",
    "decision_trace_id",
    "execution_intent_id",
    "execution_result_id",
    "outcome_id",
    "reflection_id",
    "world_state_before_id",
    "world_state_after_id",
)

REQUIRED_RECORD_KEYS = (
    "observation",
    "decision",
    "decision_trace",
    "execution_intent",
    "execution_result",
    "outcome",
    "reflection",
)

REQUIRED_TIMESTAMP_KEYS = (
    "cycle_started_at",
    "cycle_completed_at",
)


def _as_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return ""


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    return value


def serialize_record(record: Any) -> dict[str, Any]:
    if is_dataclass(record):
        payload = asdict(record)
    elif isinstance(record, dict):
        payload = dict(record)
    else:
        payload = {"value": str(record)}
    return _to_jsonable(payload)


@dataclass(slots=True)
class EpisodePolicyIdentity:
    policy_name: str
    policy_version: str
    policy_hash: str

    def validate(self) -> None:
        if not self.policy_name:
            raise ValueError("episode.policy.policy_name is required.")
        if not self.policy_version:
            raise ValueError("episode.policy.policy_version is required.")
        if not self.policy_hash:
            raise ValueError("episode.policy.policy_hash is required.")

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EpisodePolicyIdentity":
        identity = cls(
            policy_name=str(payload.get("policy_name", "")),
            policy_version=str(payload.get("policy_version", "")),
            policy_hash=str(payload.get("policy_hash", "")),
        )
        identity.validate()
        return identity


@dataclass(slots=True)
class EpisodeRecord:
    episode_id: str
    domain: str
    cycle_index: int
    policy: EpisodePolicyIdentity
    refs: dict[str, str]
    records: dict[str, dict[str, Any]]
    timestamps: dict[str, str]
    schema_version: str = EPISODE_SCHEMA_VERSION
    state: dict[str, Any] = field(default_factory=dict)
    world_deltas: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.episode_id:
            raise ValueError("episode.episode_id is required.")
        if self.schema_version != EPISODE_SCHEMA_VERSION:
            raise ValueError(
                f"episode.schema_version must be {EPISODE_SCHEMA_VERSION!r}, got {self.schema_version!r}."
            )
        if not self.domain:
            raise ValueError("episode.domain is required.")
        if self.cycle_index <= 0:
            raise ValueError("episode.cycle_index must be > 0.")

        self.policy.validate()

        if not isinstance(self.refs, dict):
            raise ValueError("episode.refs must be an object.")
        for key in REQUIRED_REF_KEYS:
            value = self.refs.get(key, "")
            if not isinstance(value, str) or not value:
                raise ValueError(f"episode.refs.{key} is required.")

        if not isinstance(self.records, dict):
            raise ValueError("episode.records must be an object.")
        for key in REQUIRED_RECORD_KEYS:
            payload = self.records.get(key)
            if not isinstance(payload, dict):
                raise ValueError(f"episode.records.{key} must be an object.")

        if not isinstance(self.timestamps, dict):
            raise ValueError("episode.timestamps must be an object.")
        for key in REQUIRED_TIMESTAMP_KEYS:
            value = self.timestamps.get(key, "")
            if not isinstance(value, str) or not value:
                raise ValueError(f"episode.timestamps.{key} is required.")

        if not isinstance(self.state, dict):
            raise ValueError("episode.state must be an object.")
        if not isinstance(self.world_deltas, dict):
            raise ValueError("episode.world_deltas must be an object.")
        if not isinstance(self.artifacts, dict):
            raise ValueError("episode.artifacts must be an object.")
        if not isinstance(self.metadata, dict):
            raise ValueError("episode.metadata must be an object.")

    def reference_ids(self) -> list[str]:
        refs: list[str] = [self.episode_id]
        refs.extend(value for _, value in sorted(self.refs.items()) if value)
        return list(dict.fromkeys(refs))

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "episode_id": self.episode_id,
            "schema_version": self.schema_version,
            "domain": self.domain,
            "cycle_index": self.cycle_index,
            "policy": self.policy.to_dict(),
            "refs": dict(self.refs),
            "records": _to_jsonable(self.records),
            "timestamps": dict(self.timestamps),
            "state": _to_jsonable(self.state),
            "world_deltas": _to_jsonable(self.world_deltas),
            "artifacts": _to_jsonable(self.artifacts),
            "metadata": _to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EpisodeRecord":
        refs_payload = payload.get("refs")
        records_payload = payload.get("records")
        timestamps_payload = payload.get("timestamps")
        state_payload = payload.get("state", {})
        world_deltas_payload = payload.get("world_deltas", {})
        artifacts_payload = payload.get("artifacts", {})
        metadata_payload = payload.get("metadata", {})

        refs = dict(refs_payload) if isinstance(refs_payload, dict) else {}
        records = dict(records_payload) if isinstance(records_payload, dict) else {}
        timestamps = dict(timestamps_payload) if isinstance(timestamps_payload, dict) else {}

        episode = cls(
            episode_id=str(payload.get("episode_id", "")),
            schema_version=str(payload.get("schema_version", "")),
            domain=str(payload.get("domain", "")),
            cycle_index=int(payload.get("cycle_index", 0)),
            policy=EpisodePolicyIdentity.from_dict(
                payload.get("policy", {})
                if isinstance(payload.get("policy"), dict)
                else {}
            ),
            refs={str(key): str(value) for key, value in refs.items()},
            records={
                str(key): dict(value) if isinstance(value, dict) else {}
                for key, value in records.items()
            },
            timestamps={
                str(key): _as_iso(value) if not isinstance(value, str) else value
                for key, value in timestamps.items()
            },
            state=dict(state_payload) if isinstance(state_payload, dict) else {},
            world_deltas=dict(world_deltas_payload)
            if isinstance(world_deltas_payload, dict)
            else {},
            artifacts=dict(artifacts_payload) if isinstance(artifacts_payload, dict) else {},
            metadata=dict(metadata_payload) if isinstance(metadata_payload, dict) else {},
        )
        episode.validate()
        return episode
