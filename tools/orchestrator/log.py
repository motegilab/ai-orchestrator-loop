from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

RUN_FILE_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_run(?P<num>\d{3})\.json$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(ts: Optional[datetime] = None) -> str:
    current = ts or utc_now()
    return current.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(ts: Optional[datetime] = None) -> str:
    current = ts or utc_now()
    return current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def short_id(length: int = 8) -> str:
    return uuid.uuid4().hex[:length]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def next_run_id(runs_dir: Path, run_date: date) -> str:
    prefix = run_date.strftime("%Y-%m-%d")
    max_number = 0
    for candidate in runs_dir.glob(f"{prefix}_run*.json"):
        match = RUN_FILE_PATTERN.match(candidate.name)
        if match is None:
            continue
        try:
            number = int(match.group("num"))
        except ValueError:
            continue
        if number > max_number:
            max_number = number
    return f"{prefix}_run{max_number + 1:03d}"


def run_file_for_id(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / f"{run_id}.json"


def to_workspace_relative(path: Path, workspace_root: Path) -> str:
    resolved_path = path.resolve()
    resolved_root = workspace_root.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return resolved_path.as_posix()
