from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from spice_hermes_bridge.observations import (
    ObservationValidationIssue,
    StructuredObservation,
    build_event_key,
    build_observation,
    utc_now_iso,
    validate_observation,
)
from spice_hermes_bridge.storage.delivery import (
    DEFAULT_DELIVERY_STATE,
    DEFAULT_OBSERVATION_AUDIT_LOG,
    append_observation_audit,
    find_audited_observation_id,
    is_event_processed,
    mark_event_processed,
)


GitHubPullFetcher = Callable[[str], list[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class GitHubWorkItemEvent:
    repo: str
    item_id: str
    title: str
    url: str | None
    action: str
    observed_at: str
    time_anchor_source: str
    github_event_id: str
    api_source: str
    requested_reviewer_count: int = 0

    @property
    def event_key(self) -> str:
        return build_event_key(
            source="github",
            namespace=self.repo,
            item_type="pull_request",
            item_id=self.item_id,
            action=self.action,
        )


@dataclass(frozen=True, slots=True)
class GitHubPollResult:
    repo: str
    status: str
    observations_built: tuple[StructuredObservation, ...] = ()
    deduped_event_keys: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    issues: tuple[ObservationValidationIssue, ...] = ()

    @property
    def result_type(self) -> str:
        return "poll_result"

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_type": self.result_type,
            "status": self.status,
            "repo": self.repo,
            "observations_built": [
                observation.to_dict() for observation in self.observations_built
            ],
            "deduped_event_keys": list(self.deduped_event_keys),
            "warnings": list(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def poll_github_repo(
    repo: str,
    *,
    fetcher: GitHubPullFetcher | None = None,
    delivery_state_path: Path = DEFAULT_DELIVERY_STATE,
    observations_log_path: Path = DEFAULT_OBSERVATION_AUDIT_LOG,
    token: str | None = None,
    polled_at: str | None = None,
) -> GitHubPollResult:
    """Poll one GitHub repo and emit deduplicated work_item_opened observations."""

    normalized_repo = repo.strip()
    if not normalized_repo or "/" not in normalized_repo:
        return GitHubPollResult(
            repo=repo,
            status="error",
            issues=(
                ObservationValidationIssue(
                    "error",
                    "repo",
                    "repo must use owner/name format",
                ),
            ),
        )

    poll_time = _coerce_observed_at(polled_at) if polled_at else utc_now_iso()
    pull_fetcher = fetcher or (
        lambda target_repo: fetch_open_pull_requests(target_repo, token=token)
    )

    try:
        pulls = pull_fetcher(normalized_repo)
    except Exception as exc:  # pragma: no cover - exercised by CLI/users.
        return GitHubPollResult(
            repo=normalized_repo,
            status="error",
            issues=(
                ObservationValidationIssue(
                    "error",
                    "github_api",
                    f"failed to fetch GitHub pull requests: {exc}",
                ),
            ),
        )

    observations: list[StructuredObservation] = []
    deduped: list[str] = []
    warnings: list[str] = []
    issues: list[ObservationValidationIssue] = []

    for event in _events_from_pull_requests(pulls, repo=normalized_repo, polled_at=poll_time):
        event_key = event.event_key
        if is_event_processed(event_key, path=delivery_state_path):
            deduped.append(event_key)
            continue
        audited_observation_id = find_audited_observation_id(
            event_key,
            path=observations_log_path,
        )
        if audited_observation_id is not None:
            mark_event_processed(
                event_key,
                observation_id=audited_observation_id,
                path=delivery_state_path,
            )
            deduped.append(event_key)
            warnings.append(f"repaired_delivery_state_from_audit={event_key}")
            continue

        observation = build_work_item_observation(event, polled_at=poll_time)
        validation_issues = tuple(validate_observation(observation))
        errors = [issue for issue in validation_issues if issue.severity == "error"]
        if errors:
            issues.extend(validation_issues)
            warnings.append(f"skipped_invalid_event_key={event_key}")
            continue

        append_observation_audit(observation, path=observations_log_path)
        mark_event_processed(
            event_key,
            observation_id=observation.observation_id or "",
            path=delivery_state_path,
        )
        observations.append(observation)

    status = "ok"
    if issues:
        status = "partial" if observations or deduped else "error"

    return GitHubPollResult(
        repo=normalized_repo,
        status=status,
        observations_built=tuple(observations),
        deduped_event_keys=tuple(deduped),
        warnings=tuple(warnings),
        issues=tuple(issues),
    )


def fetch_open_pull_requests(
    repo: str,
    *,
    token: str | None = None,
    api_base_url: str = "https://api.github.com",
) -> list[dict[str, Any]]:
    url = f"{api_base_url.rstrip('/')}/repos/{repo}/pulls?state=open&per_page=100"
    request = urllib.request.Request(
        url,
        headers=_github_headers(token or os.environ.get("GITHUB_TOKEN")),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub HTTP {exc.code}: {body}") from exc

    if not isinstance(payload, list):
        raise RuntimeError("GitHub pulls API returned a non-list payload")
    return [item for item in payload if isinstance(item, dict)]


def build_work_item_observation(
    event: GitHubWorkItemEvent,
    *,
    polled_at: str,
) -> StructuredObservation:
    attributes = {
        "kind": "pull_request",
        "repo": event.repo,
        "item_id": event.item_id,
        "title": event.title,
        "url": event.url,
        "action": event.action,
        "urgency_hint": "medium",
        "estimated_minutes_hint": 30,
        "requires_attention": True,
        "event_key": event.event_key,
    }
    return build_observation(
        observation_type="work_item_opened",
        source="github",
        observed_at=event.observed_at,
        confidence=1.0,
        attributes={key: value for key, value in attributes.items() if value is not None},
        provenance={
            "adapter": "github_pr.v1",
            "github_event_id": event.github_event_id,
            "polled_at": polled_at,
            "api_source": event.api_source,
            "time_anchor_source": event.time_anchor_source,
            "requested_reviewer_count": event.requested_reviewer_count,
        },
    )


def _events_from_pull_requests(
    pulls: list[dict[str, Any]],
    *,
    repo: str,
    polled_at: str,
) -> tuple[GitHubWorkItemEvent, ...]:
    events: list[GitHubWorkItemEvent] = []
    for pull in pulls:
        item_id = _string_or_int(pull.get("number"))
        if item_id is None:
            events.append(
                GitHubWorkItemEvent(
                    repo=repo,
                    item_id="",
                    title=_string(pull.get("title")) or "",
                    url=_string(pull.get("html_url")),
                    action="opened",
                    observed_at=polled_at,
                    time_anchor_source="poll_time",
                    github_event_id="pull_request::opened",
                    api_source="pulls_api",
                )
            )
            continue

        opened_at = _github_time(pull.get("created_at"))
        opened_observed_at = opened_at or polled_at
        events.append(
            GitHubWorkItemEvent(
                repo=repo,
                item_id=item_id,
                title=_string(pull.get("title")) or "",
                url=_string(pull.get("html_url")),
                action="opened",
                observed_at=opened_observed_at,
                time_anchor_source="github_event_time" if opened_at else "poll_time",
                github_event_id=f"pull_request:{item_id}:opened",
                api_source="pulls_api",
            )
        )

        reviewer_count = _review_request_count(pull)
        if reviewer_count > 0:
            events.append(
                GitHubWorkItemEvent(
                    repo=repo,
                    item_id=item_id,
                    title=_string(pull.get("title")) or "",
                    url=_string(pull.get("html_url")),
                    action="review_requested",
                    observed_at=polled_at,
                    time_anchor_source="poll_time",
                    github_event_id=f"pull_request:{item_id}:review_requested",
                    api_source="pulls_api",
                    requested_reviewer_count=reviewer_count,
                )
            )

    return tuple(events)


def _github_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "spice-hermes-bridge",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_time(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _coerce_observed_at(value)
    except ValueError:
        return None


def _coerce_observed_at(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _review_request_count(pull: dict[str, Any]) -> int:
    reviewers = pull.get("requested_reviewers")
    teams = pull.get("requested_teams")
    reviewer_count = len(reviewers) if isinstance(reviewers, list) else 0
    team_count = len(teams) if isinstance(teams, list) else 0
    return reviewer_count + team_count


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _string_or_int(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return _string(value)
