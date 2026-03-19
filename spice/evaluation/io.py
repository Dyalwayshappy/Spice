from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from spice.evaluation.types import EpisodeSelector
from spice.memory import EpisodeRecord, MemoryProvider
from spice.protocols import Observation, Outcome
from spice.replay.io import to_replay_record


def load_episodes_from_provider(
    provider: MemoryProvider,
    *,
    domain: str,
    selector: EpisodeSelector | None = None,
) -> list[EpisodeRecord]:
    active_selector = selector or EpisodeSelector()
    rows = provider.query(
        namespace=f"{domain}.episode",
        filters=active_selector.filters,
        limit=active_selector.limit,
        order_by=active_selector.order_by,
    )
    return parse_episode_payloads(rows)


def parse_episode_payloads(
    payloads: Iterable[EpisodeRecord | dict[str, Any]],
) -> list[EpisodeRecord]:
    episodes: list[EpisodeRecord] = []
    for idx, payload in enumerate(payloads, start=1):
        if isinstance(payload, EpisodeRecord):
            episode = payload
        elif isinstance(payload, dict):
            try:
                episode = EpisodeRecord.from_dict(payload)
            except Exception as exc:  # pragma: no cover - defensive context enrichment.
                raise ValueError(f"Invalid episode payload at index={idx}: {exc}") from exc
        else:
            raise ValueError(
                f"Episode payload at index={idx} must be EpisodeRecord or object, got {type(payload)!r}."
            )
        episodes.append(episode)
    episodes.sort(key=_episode_sort_key)
    return episodes


def episodes_to_replay_records(
    episodes: Iterable[EpisodeRecord | dict[str, Any]],
) -> list[Observation | Outcome]:
    parsed_episodes = parse_episode_payloads(episodes)
    records: list[Observation | Outcome] = []
    for episode_index, episode in enumerate(parsed_episodes, start=1):
        observation_payload = episode.records.get("observation", {})
        outcome_payload = episode.records.get("outcome", {})

        observation = to_replay_record(
            dict(observation_payload),
            line_number=(episode_index * 2) - 1,
        )
        outcome = to_replay_record(
            dict(outcome_payload),
            line_number=episode_index * 2,
        )

        if not isinstance(observation, Observation):
            raise ValueError(
                f"Episode {episode.episode_id} produced non-observation record for observation payload."
            )
        if not isinstance(outcome, Outcome):
            raise ValueError(
                f"Episode {episode.episode_id} produced non-outcome record for outcome payload."
            )

        records.extend([observation, outcome])
    return records


def _episode_sort_key(episode: EpisodeRecord) -> tuple[int, str]:
    started = episode.timestamps.get("cycle_started_at", "")
    started_at = _safe_parse_timestamp(started)
    return (
        int(episode.cycle_index),
        started_at,
    )


def _safe_parse_timestamp(value: str) -> str:
    if not value:
        return ""
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).isoformat()
    except ValueError:
        return str(value)
