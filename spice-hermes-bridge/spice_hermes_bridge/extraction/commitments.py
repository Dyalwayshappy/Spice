from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from spice_hermes_bridge.extraction.proposals import (
    CommitmentProposal,
    CommitmentProposalMeta,
)


_DAY_OFFSETS = {
    "今天": 0,
    "明天": 1,
    "后天": 2,
    "大后天": 3,
}

_COMMITMENT_TERMS = (
    "会议",
    "开会",
    "电话",
    "面试",
    "航班",
    "飞机",
    "出发",
    "出门",
    "appointment",
    "call",
    "flight",
    "interview",
    "meeting",
)
_DECLARATION_RE = re.compile(
    r"(我|俺|本人|这边)?\s*"
    r"(今天|明天|后天|大后天|\d{1,2}月\d{1,2}日?)?.{0,16}"
    r"(有|要|需要|得|去|参加|安排|约了|准备|预计|计划|开|面|飞|出发|出门)"
)
_MEETING_SHORTHAND_RE = re.compile(r"(有|开|参加|安排|约了)\s*(个|一个)?\s*会")
_QUESTION_OR_META_RE = re.compile(
    r"(怎么|如何|什么意思|啥意思|翻译|是什么|是不是|可以吗|行吗|吗[？?]?|[？?])"
)

_TIME_RE = re.compile(
    r"(?P<period>凌晨|早上|上午|中午|下午|晚上|今晚)?\s*"
    r"(?P<hour>[0-2]?\d|[零〇一二两三四五六七八九十]{1,3})"
    r"(?:[:：点](?P<minute>[0-5]?\d)?)?"
)
_MONTH_DAY_RE = re.compile(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日?")
_DURATION_RE = re.compile(
    r"(?:预计需要|预计|大概|大约|需要|约)?\s*"
    r"(?P<value>\d+(?:\.\d+)?|[零〇一二两三四五六七八九十]{1,3})\s*(?:个)?\s*"
    r"(?P<unit>小时|分钟|h|hr|hrs|min|mins)"
)
_PREP_RE = re.compile(
    r"提前\s*"
    r"(?P<value>\d+(?:\.\d+)?|[零〇一二两三四五六七八九十]{1,3})\s*(?:个)?\s*"
    r"(?P<unit>小时|分钟|h|hr|hrs|min|mins)"
)


@dataclass(frozen=True, slots=True)
class CommitmentExtraction:
    summary: str
    start_time: str
    duration_minutes: int
    confidence: float
    duration_source: str
    matched_terms: tuple[str, ...]


def extract_commitment_proposal(
    text: str,
    *,
    reference_time: datetime | None = None,
    default_timezone: str = "Asia/Shanghai",
    default_duration_minutes: int = 60,
) -> CommitmentProposal | None:
    """Extract a commitment proposal without deciding whether it matters."""

    normalized = " ".join(text.strip().split())
    if not normalized:
        return None

    if not looks_like_commitment_candidate(normalized):
        return None

    terms = _matched_commitment_terms(normalized)

    tz = ZoneInfo(default_timezone)
    reference = _normalize_reference_time(reference_time, tz)
    start_time = _extract_start_time(normalized, reference, tz)
    fuzzy_time_only = _has_fuzzy_time_without_precise_time(normalized)

    duration_minutes, duration_source = _extract_duration_minutes(normalized)
    prep_start_time = _extract_prep_start_time(normalized, start_time)
    assumptions: list[str] = []
    uncertain_fields: list[str] = []
    needs_confirmation = False

    if start_time is None:
        uncertain_fields.append("start_time")
        if fuzzy_time_only:
            assumptions.append("time_period_without_precise_start_time")
        needs_confirmation = True

    if duration_minutes is None:
        if start_time is not None and _allows_default_duration(terms):
            duration_minutes = default_duration_minutes
            duration_source = "default_safe"
        else:
            uncertain_fields.append("duration_minutes")
            assumptions.append("duration_missing")
            needs_confirmation = True

    confidence = 0.86
    if duration_source == "explicit":
        confidence = 0.86
    elif duration_source == "default_safe":
        confidence = 0.72
    if needs_confirmation:
        confidence = min(confidence, 0.49)

    return CommitmentProposal(
        summary=normalized,
        start_time=start_time.isoformat() if start_time else None,
        duration_minutes=duration_minutes,
        prep_start_time=prep_start_time.isoformat() if prep_start_time else None,
        meta=CommitmentProposalMeta(
            confidence=confidence,
            uncertain_fields=tuple(uncertain_fields),
            assumptions=tuple(assumptions),
            needs_confirmation=needs_confirmation,
        ),
        extractor="deterministic",
        matched_terms=terms,
        duration_source=duration_source,
    )


def has_precise_time_evidence(text: str) -> bool:
    """Return whether text itself contains a precise time token."""

    return _find_time_match(text) is not None


def looks_like_commitment_candidate(text: str) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False
    if _looks_like_question_or_meta(normalized):
        return False
    if not _matched_commitment_terms(normalized):
        return False
    return _looks_like_declared_commitment(normalized)


def extract_commitment(
    text: str,
    *,
    reference_time: datetime | None = None,
    default_timezone: str = "Asia/Shanghai",
    default_duration_minutes: int = 60,
) -> CommitmentExtraction | None:
    """Extract a declared commitment without deciding whether it matters."""
    proposal = extract_commitment_proposal(
        text,
        reference_time=reference_time,
        default_timezone=default_timezone,
        default_duration_minutes=default_duration_minutes,
    )
    if (
        proposal is None
        or proposal.start_time is None
        or proposal.duration_minutes is None
        or proposal.meta.needs_confirmation
    ):
        return None

    return CommitmentExtraction(
        summary=proposal.summary or "",
        start_time=proposal.start_time,
        duration_minutes=proposal.duration_minutes,
        confidence=proposal.meta.confidence,
        duration_source=proposal.duration_source or "unknown",
        matched_terms=proposal.matched_terms,
    )


def _extract_start_time(
    text: str,
    reference: datetime,
    tz: ZoneInfo,
) -> datetime | None:
    date_base = reference.date()

    for marker, offset in _DAY_OFFSETS.items():
        if marker in text:
            date_base = (reference + timedelta(days=offset)).date()
            break
    else:
        month_day = _MONTH_DAY_RE.search(text)
        if month_day:
            month = int(month_day.group("month"))
            day = int(month_day.group("day"))
            year = reference.year
            candidate = datetime(year, month, day, tzinfo=tz)
            if candidate < reference:
                candidate = datetime(year + 1, month, day, tzinfo=tz)
            date_base = candidate.date()

    match = _find_time_match(text)
    if match is None:
        return None

    hour = _parse_hour(match.group("hour"))
    if hour is None:
        return None
    minute_raw = match.group("minute")
    minute = int(minute_raw) if minute_raw else 0
    period = match.group("period") or ""

    if period in {"下午", "晚上", "今晚"} and hour < 12:
        hour += 12
    elif period == "中午" and hour < 11:
        hour += 12

    if hour > 23 or minute > 59:
        return None

    return datetime(
        date_base.year,
        date_base.month,
        date_base.day,
        hour,
        minute,
        tzinfo=tz,
    )


def _find_time_match(text: str) -> re.Match[str] | None:
    for match in _TIME_RE.finditer(text):
        raw = match.group(0)
        if "月" in raw:
            continue
        if match.group("period") or "点" in raw or ":" in raw or "：" in raw:
            return match
    return None


def _extract_duration_minutes(
    text: str,
) -> tuple[int | None, str | None]:
    for match in _DURATION_RE.finditer(text):
        if text[max(0, match.start() - 2) : match.start()] == "提前":
            continue

        value = _parse_duration_value(match.group("value"))
        if value is None:
            continue
        unit = match.group("unit")
        if unit in {"小时", "h", "hr", "hrs"}:
            return max(1, round(value * 60)), "explicit"
        return max(1, round(value)), "explicit"
    return None, None


def _extract_prep_start_time(text: str, start_time: datetime | None) -> datetime | None:
    if start_time is None:
        return None

    match = _PREP_RE.search(text)
    if not match:
        return None

    value = _parse_duration_value(match.group("value"))
    if value is None:
        return None

    unit = match.group("unit")
    minutes = value * 60 if unit in {"小时", "h", "hr", "hrs"} else value
    return start_time - timedelta(minutes=max(1, round(minutes)))


def _parse_duration_value(value: str) -> float | None:
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)
    parsed = _parse_chinese_number(value)
    return float(parsed) if parsed is not None else None


def _matched_commitment_terms(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    terms = [term for term in _COMMITMENT_TERMS if term.lower() in lowered]
    if _MEETING_SHORTHAND_RE.search(text):
        terms.append("会")
    return tuple(dict.fromkeys(terms))


def _looks_like_question_or_meta(text: str) -> bool:
    return bool(_QUESTION_OR_META_RE.search(text))


def _looks_like_declared_commitment(text: str) -> bool:
    if _MEETING_SHORTHAND_RE.search(text):
        return True
    if _DECLARATION_RE.search(text):
        return True
    if _find_time_match(text) and _matched_commitment_terms(text):
        return True
    return False


def _has_fuzzy_time_without_precise_time(text: str) -> bool:
    if _find_time_match(text):
        return False
    return any(marker in text for marker in ("上午", "中午", "下午", "晚上", "今晚"))


def _allows_default_duration(terms: tuple[str, ...]) -> bool:
    safe_default_terms = {
        "会议",
        "开会",
        "电话",
        "面试",
        "appointment",
        "call",
        "interview",
        "meeting",
        "会",
    }
    risky_terms = {"航班", "飞机", "出发", "出门", "flight"}
    if any(term in risky_terms for term in terms):
        return False
    return any(term in safe_default_terms for term in terms)


def _normalize_reference_time(reference_time: datetime | None, tz: ZoneInfo) -> datetime:
    reference = reference_time or datetime.now(tz)
    if reference.tzinfo is None or reference.utcoffset() is None:
        reference = reference.replace(tzinfo=tz)
    else:
        reference = reference.astimezone(tz)
    return reference


def _parse_hour(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    return _parse_chinese_number(value)


def _parse_chinese_number(value: str) -> int | None:
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if value.startswith("十") and len(value) == 2:
        tail = digits.get(value[1])
        return 10 + tail if tail is not None else None
    if value.endswith("十") and len(value) == 2:
        head = digits.get(value[0])
        return head * 10 if head is not None else None
    if "十" in value and len(value) == 3:
        head = digits.get(value[0])
        tail = digits.get(value[2])
        if head is not None and tail is not None:
            return head * 10 + tail
    if len(value) == 1:
        return digits.get(value)
    return None
