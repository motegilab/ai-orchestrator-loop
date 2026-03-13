from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


def _dedupe_list(items: Sequence[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _run_git(workspace_root: Path, args: List[str]) -> Tuple[List[str], Optional[str]]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace_root)] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return [], detail or f"exit {completed.returncode}"
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return lines, None


def _normalize_path_for_scope(
    path_text: str,
    *,
    normalize_slashes: bool = True,
    lowercase_for_matching: bool = True,
) -> str:
    text = str(path_text or "").strip().strip("\"'")
    if not text:
        return ""
    if normalize_slashes:
        text = text.replace("\\", "/").lstrip("./")
        text = re.sub(r"/{2,}", "/", text)
    if lowercase_for_matching:
        text = text.lower()
    return text.strip()


def is_allowed_path(
    path_text: str,
    *,
    allowed_read_entries: Sequence[str],
    normalize_slashes: bool = True,
    lowercase_for_matching: bool = True,
) -> bool:
    normalized = _normalize_path_for_scope(
        path_text,
        normalize_slashes=normalize_slashes,
        lowercase_for_matching=lowercase_for_matching,
    )
    if not normalized:
        return True

    normalized_allowed_entries = [
        _normalize_path_for_scope(
            item,
            normalize_slashes=normalize_slashes,
            lowercase_for_matching=lowercase_for_matching,
        )
        for item in allowed_read_entries
    ]
    for item in normalized_allowed_entries:
        if not item:
            continue
        if "/" in item:
            prefix = item.rstrip("/")
            if normalized == prefix or normalized.startswith(prefix + "/"):
                return True
            continue
        if normalized == item or Path(normalized).name == item:
            return True

    name = Path(normalized).name
    if name.startswith("config") and name.endswith(".yaml"):
        return True
    return False


def find_scope_violations(
    workspace_root: Path,
    *,
    allowed_read_entries: Sequence[str],
    normalize_slashes: bool = True,
    lowercase_for_matching: bool = True,
) -> List[str]:
    tracked, tracked_error = _run_git(workspace_root, ["diff", "--name-only"])
    untracked, untracked_error = _run_git(
        workspace_root, ["ls-files", "--others", "--exclude-standard"]
    )

    combined = _dedupe_list(tracked + untracked)
    violations = [
        path
        for path in combined
        if not is_allowed_path(
            path,
            allowed_read_entries=allowed_read_entries,
            normalize_slashes=normalize_slashes,
            lowercase_for_matching=lowercase_for_matching,
        )
    ]

    if tracked_error:
        violations.append(f"[git diff error] {tracked_error}")
    if untracked_error:
        violations.append(f"[git ls-files error] {untracked_error}")
    return _dedupe_list(violations)


def find_tracked_diff_paths(workspace_root: Path) -> List[str]:
    tracked, tracked_error = _run_git(workspace_root, ["diff", "--name-only"])
    if tracked_error:
        return [f"[git diff error] {tracked_error}"]
    return _dedupe_list(tracked)


def build_scope_guard_report(
    violations: Sequence[str], allowed_read_entries: Sequence[str]
) -> str:
    lines = [
        "scope_guard: blocked",
        "reason: changes outside orchestrator allowlist detected",
        "allowed_read_entries:",
        *[f"- {str(item).strip()}" for item in allowed_read_entries if str(item).strip()],
        "allowed_config_pattern: config*.yaml",
        "violations:",
        *[f"- {path}" for path in violations],
    ]
    return "\n".join(lines)


def build_make_post_scope_guard_report(changed_paths: Sequence[str]) -> str:
    lines = [
        "scope_guard: blocked",
        "reason: make orch-post requires `git diff --name-only` to be empty",
        "event_filter: event_id == make-post OR summary contains 'make orch-post'",
        "tracked_changes:",
        *[f"- {path}" for path in changed_paths],
    ]
    return "\n".join(lines)
