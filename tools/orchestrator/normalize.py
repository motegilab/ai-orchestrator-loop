from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

EVENT_ID_KEYS = ("event_id", "id", "webhook_id", "request_id")
SOURCE_KEYS = ("source", "provider", "origin")
INTENT_KEYS = ("intent", "event_type", "type", "action", "status")
STATUS_KEYS = ("status", "state", "result", "outcome")
SUMMARY_KEYS = ("summary", "message", "title", "description", "detail")
ERROR_KEYS = ("error", "errors", "stderr", "exception", "traceback", "failure", "failures")

FAILED_HINTS = ("fail", "failed", "error", "exception", "panic")
BLOCKED_HINTS = ("block", "blocked", "waiting", "pending", "hold")
SUCCESS_HINTS = ("success", "completed", "complete", "done", "ok")


def derive_event_id(payload: Dict[str, Any], fallback: str) -> str:
    value = _lookup_value_by_keys(payload, EVENT_ID_KEYS)
    if value is None:
        return fallback
    text = _stringify(value)
    return text or fallback


def derive_source(payload: Dict[str, Any], fallback: str = "cursor") -> str:
    value = _lookup_value_by_keys(payload, SOURCE_KEYS)
    if value is None:
        return fallback
    source = _stringify(value).lower().strip()
    return source or fallback


def infer_intent(payload: Dict[str, Any]) -> str:
    explicit = _lookup_value_by_keys(payload, INTENT_KEYS)
    text = f"{_stringify(explicit)} {_collect_signal_text(payload)}".lower()

    if any(keyword in text for keyword in FAILED_HINTS):
        return "task_failed"
    if any(keyword in text for keyword in SUCCESS_HINTS):
        return "task_completed"
    return "status_update"


def infer_status(payload: Dict[str, Any]) -> str:
    explicit = _lookup_value_by_keys(payload, STATUS_KEYS)
    text = f"{_stringify(explicit)} {_collect_signal_text(payload)}".lower()

    if any(keyword in text for keyword in FAILED_HINTS):
        return "failed"
    if any(keyword in text for keyword in BLOCKED_HINTS):
        return "blocked"
    return "success"


def build_summary(payload: Dict[str, Any], intent: str, status: str) -> str:
    candidate = _lookup_value_by_keys(payload, SUMMARY_KEYS)
    text = _stringify(candidate)
    if text:
        return _truncate(text, 220)
    return f"Webhook received ({intent}, {status})."


def extract_top_errors(payload: Dict[str, Any], limit: int = 5) -> List[str]:
    candidates: List[str] = []

    for key in ERROR_KEYS:
        value = _lookup_value_by_keys(payload, (key,))
        if value is not None:
            candidates.extend(_flatten_error_values(value))

    for text in _collect_strings(payload):
        normalized = text.lower()
        if any(hint in normalized for hint in FAILED_HINTS):
            candidates.append(text)

    unique: List[str] = []
    seen = set()
    for item in candidates:
        compact = " ".join(item.split())
        if not compact:
            continue
        key = compact.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(_truncate(compact, 280))
        if len(unique) >= limit:
            break
    return unique


def normalize_payload(
    payload: Dict[str, Any],
    *,
    run_id: str,
    event_id: str,
    received_at: str,
    source: str,
    evidence_paths: Sequence[str],
    next_prompt_path: str,
) -> Dict[str, Any]:
    intent = infer_intent(payload)
    status = infer_status(payload)
    summary = build_summary(payload, intent=intent, status=status)
    top_errors = extract_top_errors(payload, limit=5) if status == "failed" else []

    normalized = {
        "run_id": run_id,
        "event_id": event_id,
        "received_at": received_at,
        "source": source,
        "intent": intent,
        "summary": summary,
        "status": status,
        "top_errors": top_errors[:5],
        "evidence_paths": [path for path in evidence_paths if path],
        "next_prompt_path": next_prompt_path,
    }
    return normalized


def _collect_signal_text(payload: Dict[str, Any]) -> str:
    return " ".join(_collect_strings(payload))


def _lookup_value_by_keys(
    data: Any,
    keys: Iterable[str],
    depth: int = 0,
    max_depth: int = 5,
) -> Optional[Any]:
    if depth > max_depth:
        return None

    key_set = {key.lower() for key in keys}

    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in key_set and value not in (None, "", [], {}):
                return value
        for value in data.values():
            found = _lookup_value_by_keys(value, keys, depth=depth + 1, max_depth=max_depth)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(data, list):
        for item in data:
            found = _lookup_value_by_keys(item, keys, depth=depth + 1, max_depth=max_depth)
            if found not in (None, "", [], {}):
                return found

    return None


def _collect_strings(data: Any, depth: int = 0, max_depth: int = 5) -> List[str]:
    if depth > max_depth:
        return []

    collected: List[str] = []
    if isinstance(data, str):
        text = data.strip()
        if text:
            collected.append(text)
    elif isinstance(data, dict):
        for value in data.values():
            collected.extend(_collect_strings(value, depth=depth + 1, max_depth=max_depth))
    elif isinstance(data, list):
        for item in data:
            collected.extend(_collect_strings(item, depth=depth + 1, max_depth=max_depth))
    return collected


def _flatten_error_values(value: Any) -> List[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        flattened: List[str] = []
        for item in value:
            flattened.extend(_flatten_error_values(item))
        return flattened
    if isinstance(value, dict):
        flattened = []
        for key, item in value.items():
            key_text = str(key).strip()
            item_text = _stringify(item).strip()
            if key_text and item_text:
                flattened.append(f"{key_text}: {item_text}")
            else:
                flattened.extend(_flatten_error_values(item))
        return flattened
    text = _stringify(value).strip()
    return [text] if text else []


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
