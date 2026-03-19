from __future__ import annotations

"""Vocabulary constants for the incident commander flagship demo."""

INCIDENT_DOMAIN_NAME = "incident_commander"
INCIDENT_ENTITY_ID = "incident.current"
DEFAULT_INCIDENT_ID = "incident-001"

OBS_ALERT_OPENED = "incident.alert_opened"
OBS_METRIC_SNAPSHOT = "incident.metric_snapshot"

ACTION_ROLLBACK_RELEASE = "incident.rollback_release"
ACTION_DISABLE_FEATURE_FLAG = "incident.disable_feature_flag"
ACTION_MONITOR = "incident.monitor"
ACTION_ESCALATE_HUMAN = "incident.escalate_human"
ACTION_REQUEST_HOTFIX = "incident.request_hotfix"

OUTCOME_INCIDENT_TRANSITION = "incident.mitigation_result"

HIGH_ERROR_RATE_THRESHOLD = 0.05
HIGH_LATENCY_P95_THRESHOLD = 1000
STABLE_ERROR_RATE_MAX = 0.01
STABLE_LATENCY_P95_MAX = 250

BASELINE_POLICY_NAME = "incident.baseline"
BASELINE_POLICY_VERSION = "0.2"
CANDIDATE_POLICY_NAME = "incident.context_aware"
CANDIDATE_POLICY_VERSION = "0.2"

OBSERVATION_KINDS = [
    OBS_ALERT_OPENED,
    OBS_METRIC_SNAPSHOT,
]

ACTION_KINDS = [
    ACTION_ROLLBACK_RELEASE,
    ACTION_DISABLE_FEATURE_FLAG,
    ACTION_MONITOR,
    ACTION_ESCALATE_HUMAN,
    ACTION_REQUEST_HOTFIX,
]
