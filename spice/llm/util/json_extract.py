from __future__ import annotations

import json


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if "```" not in stripped:
        return stripped
    lines = stripped.splitlines()
    filtered: list[str] = []
    for line in lines:
        if line.strip().startswith("```"):
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def extract_first_json_object(text: str) -> str | None:
    normalized = strip_markdown_fences(text)
    return _extract_first_valid_payload(normalized, open_token="{", close_token="}", expect="object")


def extract_first_json_array(text: str) -> str | None:
    normalized = strip_markdown_fences(text)
    return _extract_first_valid_payload(normalized, open_token="[", close_token="]", expect="array")


def _extract_first_valid_payload(
    text: str,
    *,
    open_token: str,
    close_token: str,
    expect: str,
) -> str | None:
    for idx, ch in enumerate(text):
        if ch != open_token:
            continue
        candidate = _extract_balanced(text, start_index=idx, open_token=open_token, close_token=close_token)
        if candidate is None:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if expect == "object" and isinstance(parsed, dict):
            return candidate
        if expect == "array" and isinstance(parsed, list):
            return candidate
    return None


def _extract_balanced(
    text: str,
    *,
    start_index: int,
    open_token: str,
    close_token: str,
) -> str | None:
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start_index, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == open_token:
            depth += 1
            continue
        if ch == close_token:
            depth -= 1
            if depth == 0:
                return text[start_index : idx + 1]
    return None
