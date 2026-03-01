from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from .ssot import OrchestratorConfig, load_config
except ImportError:
    from ssot import OrchestratorConfig, load_config  # type: ignore

REPORT_FILENAME = "REPORT_LATEST.md"
REPORT_FAILED_FILENAME = "REPORT_FAILED.md"
TAIL_LINES = 100
AUDIT_PREVIEW_LINES = 30
AUDIT_PREVIEW_CHARS = 2000
EXEC_TRACE_COMMAND_CHARS = 800
CANONICAL_SSOT_REL_PATH = "rules/SSOT_AI_Orchestrator_Loop.md"
REQUIRED_META_KEYS = (
    "command",
    "exit_code",
    "started_at",
    "ended_at",
    "duration_ms",
    "stdout_path",
    "stderr_path",
)
DEFAULT_REPORT_INTEGRITY_POLICY: Dict[str, Any] = {
    "enabled": True,
    "verify_commands_must_be_executed": True,
    "verify_commands_source": "report.verify_commands",
    "executed_commands_source": "summaries_meta",
    "require_executed_commands_cover_verify_commands": True,
    "on_mismatch": "blocked",
    "mismatch_error_prefix": "missing_execution_log:",
    "required_evidence_for_claims": {
        "claim_evidence_negative_test": {
            "enabled": True,
            "must_include_run_id": True,
            "must_include_report_excerpt": True,
        }
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_text(path: Path) -> Optional[str]:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        return None
    return None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _tail(path: Optional[Path], line_count: int = TAIL_LINES) -> str:
    if not path:
        return "(no output)"
    if not path.exists():
        return "(no output)"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return "(no output)"
    visible = [line for line in lines if line.strip()]
    if not visible:
        return "(no output)"
    return "\n".join(visible[-line_count:])


def _run_git(workspace_root: Path, args: List[str], timeout_seconds: int = 10) -> Tuple[Optional[str], Optional[str]]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace_root)] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return None, detail or f"exit {completed.returncode}"
    return completed.stdout.strip(), None


def _resolve_workspace_path(config: OrchestratorConfig, text: str) -> Optional[Path]:
    raw = str(text).strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = config.workspace_root / raw
    return candidate.resolve()


def _extract_summary_paths(payload: Any) -> List[str]:
    found: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            summary_paths = node.get("summary_paths")
            if isinstance(summary_paths, dict):
                for value in summary_paths.values():
                    if isinstance(value, str):
                        found.append(value)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def _collect_run_log_candidates(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]]
) -> List[Path]:
    if not latest_run:
        return []

    candidate_texts: List[str] = []

    for key in ("top_errors", "evidence_paths"):
        values = latest_run.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, str):
                    candidate_texts.append(item)

    evidence_paths = latest_run.get("evidence_paths")
    if isinstance(evidence_paths, list):
        for evidence in evidence_paths:
            if not isinstance(evidence, str):
                continue
            evidence_path = _resolve_workspace_path(config, evidence)
            if not evidence_path or not evidence_path.exists():
                continue
            if evidence_path.suffix.lower() != ".json":
                continue
            payload = _read_json(evidence_path)
            if payload:
                candidate_texts.extend(_extract_summary_paths(payload))

    candidates: List[Path] = []
    seen = set()
    for text in candidate_texts:
        normalized = text.replace("\\", "/").strip()
        if not normalized:
            continue
        if not (
            normalized.endswith(".stdout.log")
            or normalized.endswith(".stderr.log")
            or normalized.endswith(".meta.json")
        ):
            continue
        resolved = _resolve_workspace_path(config, normalized)
        if not resolved:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(resolved)
    return candidates


def _resolve_log_paths(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]]
) -> Tuple[Optional[Path], Optional[Path]]:
    candidates = _collect_run_log_candidates(config, latest_run)
    stdout_path: Optional[Path] = None
    stderr_path: Optional[Path] = None

    for candidate in candidates:
        suffix = candidate.name.lower()
        if suffix.endswith(".stdout.log") and stdout_path is None:
            stdout_path = candidate
        elif suffix.endswith(".stderr.log") and stderr_path is None:
            stderr_path = candidate

    if stderr_path and not stdout_path:
        guessed = stderr_path.with_name(stderr_path.name.replace(".stderr.log", ".stdout.log"))
        if guessed.exists():
            stdout_path = guessed
    if stdout_path and not stderr_path:
        guessed = stdout_path.with_name(stdout_path.name.replace(".stdout.log", ".stderr.log"))
        if guessed.exists():
            stderr_path = guessed

    return stdout_path, stderr_path


def _to_workspace_relative(config: OrchestratorConfig, path: Path) -> str:
    resolved = path.resolve()
    root = config.workspace_root.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _dedupe_strings(values: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _deterministic_log_paths(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]]
) -> Tuple[Optional[Path], Optional[Path]]:
    run_id = str((latest_run or {}).get("run_id", "")).strip()
    if not run_id:
        return None, None
    return (
        config.summaries_dir / f"{run_id}.stdout.log",
        config.summaries_dir / f"{run_id}.stderr.log",
    )


def _load_source_log_text(path: Optional[Path]) -> str:
    if not path or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _write_log_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _short_error_summary(exc: Exception, limit: int = 240) -> str:
    text = " ".join(str(exc).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _to_rel_path_text(config: OrchestratorConfig, path: Optional[Path]) -> str:
    if not path:
        return ""
    return _to_workspace_relative(config, path)


def _ensure_report_integrity_policy(run_data: Dict[str, Any]) -> Dict[str, Any]:
    policy = run_data.get("policy")
    policy_map = policy if isinstance(policy, dict) else {}

    report_integrity = policy_map.get("report_integrity")
    integrity_map = report_integrity if isinstance(report_integrity, dict) else {}

    integrity_map["enabled"] = bool(
        integrity_map.get("enabled", DEFAULT_REPORT_INTEGRITY_POLICY["enabled"])
    )
    integrity_map["verify_commands_must_be_executed"] = bool(
        integrity_map.get(
            "verify_commands_must_be_executed",
            DEFAULT_REPORT_INTEGRITY_POLICY["verify_commands_must_be_executed"],
        )
    )
    integrity_map["verify_commands_source"] = str(
        integrity_map.get("verify_commands_source", "")
        or DEFAULT_REPORT_INTEGRITY_POLICY["verify_commands_source"]
    )
    integrity_map["executed_commands_source"] = str(
        integrity_map.get("executed_commands_source", "")
        or DEFAULT_REPORT_INTEGRITY_POLICY["executed_commands_source"]
    )
    integrity_map["require_executed_commands_cover_verify_commands"] = bool(
        integrity_map.get(
            "require_executed_commands_cover_verify_commands",
            DEFAULT_REPORT_INTEGRITY_POLICY["require_executed_commands_cover_verify_commands"],
        )
    )
    integrity_map["on_mismatch"] = str(
        integrity_map.get("on_mismatch", "") or DEFAULT_REPORT_INTEGRITY_POLICY["on_mismatch"]
    )
    integrity_map["mismatch_error_prefix"] = str(
        integrity_map.get("mismatch_error_prefix", "")
        or DEFAULT_REPORT_INTEGRITY_POLICY["mismatch_error_prefix"]
    )

    required_evidence = integrity_map.get("required_evidence_for_claims")
    required_evidence_map = required_evidence if isinstance(required_evidence, dict) else {}
    negative_test = required_evidence_map.get("claim_evidence_negative_test")
    negative_test_map = negative_test if isinstance(negative_test, dict) else {}
    default_negative = DEFAULT_REPORT_INTEGRITY_POLICY["required_evidence_for_claims"][
        "claim_evidence_negative_test"
    ]
    negative_test_map["enabled"] = bool(negative_test_map.get("enabled", default_negative["enabled"]))
    negative_test_map["must_include_run_id"] = bool(
        negative_test_map.get("must_include_run_id", default_negative["must_include_run_id"])
    )
    negative_test_map["must_include_report_excerpt"] = bool(
        negative_test_map.get(
            "must_include_report_excerpt",
            default_negative["must_include_report_excerpt"],
        )
    )
    required_evidence_map["claim_evidence_negative_test"] = negative_test_map
    integrity_map["required_evidence_for_claims"] = required_evidence_map

    policy_map["report_integrity"] = integrity_map
    run_data["policy"] = policy_map
    return integrity_map


def _update_report_fields_in_runs(
    config: OrchestratorConfig,
    *,
    run_id: str,
    report_status: str,
    report_path: str,
    report_error: str,
) -> None:
    latest_run = _read_json(config.latest_run_path)
    if latest_run:
        _ensure_report_integrity_policy(latest_run)
        latest_run["report_status"] = report_status
        latest_run["report_path"] = report_path
        latest_run["report_error"] = report_error
        _write_json(config.latest_run_path, latest_run)

    run_id_text = run_id.strip() or str((latest_run or {}).get("run_id", "")).strip()
    if not run_id_text:
        return

    run_path = config.runs_dir / f"{run_id_text}.json"
    run_payload = _read_json(run_path)
    if not run_payload:
        return
    _ensure_report_integrity_policy(run_payload)
    run_payload["report_status"] = report_status
    run_payload["report_path"] = report_path
    run_payload["report_error"] = report_error
    _write_json(run_path, run_payload)


def _write_report_failed(
    config: OrchestratorConfig,
    *,
    run_id: str,
    error_summary: str,
) -> Path:
    failed_path = config.runtime_root / "reports" / REPORT_FAILED_FILENAME
    lines = [
        "# REPORT_FAILED",
        "",
        f"- run_id: `{run_id or '-'}`",
        f"- error_summary: {error_summary}",
        "- next_action: restart server / rerun orch-report",
        "",
    ]
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    failed_path.write_text("\n".join(lines), encoding="utf-8")
    return failed_path


def _sync_deterministic_logs(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], Optional[Path], Optional[Path]]:
    if not latest_run:
        return latest_run, None, None

    stdout_target, stderr_target = _deterministic_log_paths(config, latest_run)
    if not stdout_target or not stderr_target:
        return latest_run, None, None

    source_stdout, source_stderr = _resolve_log_paths(config, latest_run)
    _write_log_text(stdout_target, _load_source_log_text(source_stdout))
    _write_log_text(stderr_target, _load_source_log_text(source_stderr))

    evidence_paths = latest_run.get("evidence_paths")
    evidence = evidence_paths if isinstance(evidence_paths, list) else []
    stdout_rel = _to_workspace_relative(config, stdout_target)
    stderr_rel = _to_workspace_relative(config, stderr_target)
    merged = _dedupe_strings([*(str(item) for item in evidence), stdout_rel, stderr_rel])
    latest_run["evidence_paths"] = merged

    _write_json(config.latest_run_path, latest_run)

    run_id = str(latest_run.get("run_id", "")).strip()
    if run_id:
        run_path = config.runs_dir / f"{run_id}.json"
        run_payload = _read_json(run_path)
        if run_payload:
            run_evidence = run_payload.get("evidence_paths")
            as_list = run_evidence if isinstance(run_evidence, list) else []
            run_payload["evidence_paths"] = _dedupe_strings(
                [*(str(item) for item in as_list), stdout_rel, stderr_rel]
            )
            _write_json(run_path, run_payload)

    return latest_run, stdout_target, stderr_target


def _collect_audit_paths(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]]
) -> List[Path]:
    if not latest_run:
        return []
    evidence_paths = latest_run.get("evidence_paths")
    if not isinstance(evidence_paths, list):
        return []

    collected: List[Path] = []
    seen = set()
    for raw in evidence_paths:
        if not isinstance(raw, str):
            continue
        normalized = raw.replace("\\", "/").lower().strip()
        if "/artifacts/audits/" not in normalized:
            continue
        if not normalized.endswith(".md"):
            continue
        resolved = _resolve_workspace_path(config, raw)
        if not resolved:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        collected.append(resolved)
    return collected


def _select_latest_audit(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]]
) -> Optional[Path]:
    candidates = _collect_audit_paths(config, latest_run)
    if not candidates:
        return None

    def _sort_key(path: Path) -> Tuple[float, str]:
        try:
            return (path.stat().st_mtime, path.name.lower())
        except Exception:
            return (0.0, path.name.lower())

    candidates.sort(key=_sort_key, reverse=True)
    return candidates[0]


def _audit_preview(path: Optional[Path]) -> str:
    if not path:
        return "None"
    if not path.exists():
        return "N/A (referenced audit not found)"
    text = _read_text(path)
    if text is None:
        return "N/A (failed to read audit)"
    if not text.strip():
        return "(empty)"

    snippet = "\n".join(text.splitlines()[:AUDIT_PREVIEW_LINES])
    if len(snippet) > AUDIT_PREVIEW_CHARS:
        return snippet[:AUDIT_PREVIEW_CHARS].rstrip() + "..."
    return snippet


def _find_evidence_path(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]], needle: str
) -> Optional[Path]:
    if not latest_run:
        return None
    evidence_paths = latest_run.get("evidence_paths")
    if not isinstance(evidence_paths, list):
        return None
    needle_text = needle.replace("\\", "/").lower()
    for raw in evidence_paths:
        if not isinstance(raw, str):
            continue
        normalized = raw.replace("\\", "/").lower()
        if needle_text not in normalized:
            continue
        resolved = _resolve_workspace_path(config, raw)
        if resolved and resolved.exists():
            return resolved
    return None


def _normalize_rel_path_text(text: str) -> str:
    return text.replace("\\", "/").lstrip("./").strip().lower()


def _expected_meta_rel_path(run_id: str) -> str:
    return f"tools/orchestrator_runtime/artifacts/summaries/{run_id}.meta.json"


def _quality_gate_status(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]]
) -> Dict[str, str]:
    run = latest_run or {}
    run_id = str(run.get("run_id", "")).strip()
    if not run_id:
        reason = "run_id is missing in runs/latest.json"
        return {
            "report_status": "blocked",
            "report_error": reason,
            "reason": reason,
            "fix": "runs/latest.json の run_id を生成するよう webhook 正規化処理を修正する。",
            "focus_file": "tools/orchestrator/server.py",
            "expected_meta_rel": "N/A",
            "meta_path": "N/A",
        }

    expected_meta_rel = _expected_meta_rel_path(run_id)
    evidence_paths = run.get("evidence_paths")
    evidence_list = evidence_paths if isinstance(evidence_paths, list) else []
    normalized_evidence = {_normalize_rel_path_text(str(item)) for item in evidence_list}
    expected_key = _normalize_rel_path_text(expected_meta_rel)
    if expected_key not in normalized_evidence:
        reason = f"required meta missing in evidence_paths: {expected_meta_rel}"
        return {
            "report_status": "blocked",
            "report_error": reason,
            "reason": reason,
            "fix": "webhook処理で <run_id>.meta.json を生成し、runs/latest.json の evidence_paths へ追加する。",
            "focus_file": "tools/orchestrator/server.py",
            "expected_meta_rel": expected_meta_rel,
            "meta_path": expected_meta_rel,
        }

    meta_path = _resolve_workspace_path(config, expected_meta_rel)
    if not meta_path or not meta_path.exists():
        reason = f"meta.json path not found: {expected_meta_rel}"
        return {
            "report_status": "blocked",
            "report_error": reason,
            "reason": reason,
            "fix": "evidence_paths に載せた meta.json を実ファイルとして保存する。",
            "focus_file": "tools/orchestrator/server.py",
            "expected_meta_rel": expected_meta_rel,
            "meta_path": expected_meta_rel,
        }

    meta_payload = _read_json(meta_path)
    if not meta_payload:
        reason = f"meta.json parse failed: {expected_meta_rel}"
        return {
            "report_status": "blocked",
            "report_error": reason,
            "reason": reason,
            "fix": "meta.json を UTF-8 の正しい JSON で書き出す。",
            "focus_file": "tools/orchestrator/server.py",
            "expected_meta_rel": expected_meta_rel,
            "meta_path": _to_workspace_relative(config, meta_path),
        }

    missing_keys: List[str] = []
    for key in REQUIRED_META_KEYS:
        value = meta_payload.get(key)
        if value is None:
            missing_keys.append(key)
            continue
        if isinstance(value, str) and not value.strip():
            missing_keys.append(key)

    if missing_keys:
        reason = f"meta.json missing required keys: {', '.join(missing_keys)}"
        return {
            "report_status": "blocked",
            "report_error": reason,
            "reason": reason,
            "fix": "meta.json に command/exit_code/started_at/ended_at/duration_ms/stdout_path/stderr_path を全て保存する。",
            "focus_file": "tools/orchestrator/server.py",
            "expected_meta_rel": expected_meta_rel,
            "meta_path": _to_workspace_relative(config, meta_path),
        }

    return {
        "report_status": "success",
        "report_error": "",
        "reason": "",
        "fix": "",
        "focus_file": "tools/orchestrator_runtime/runs/latest.json",
        "expected_meta_rel": expected_meta_rel,
        "meta_path": _to_workspace_relative(config, meta_path),
    }


def _summaries_meta_candidates(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]]
) -> List[Path]:
    candidates = _collect_run_log_candidates(config, latest_run)
    meta_paths = [path for path in candidates if path.name.lower().endswith(".meta.json") and path.exists()]

    def _sort_key(path: Path) -> Tuple[float, str]:
        try:
            return (path.stat().st_mtime, path.name.lower())
        except Exception:
            return (0.0, path.name.lower())

    meta_paths.sort(key=_sort_key, reverse=True)
    return meta_paths


def _shorten_single_line(text: Any, limit: int = EXEC_TRACE_COMMAND_CHARS) -> str:
    normalized = " ".join(str(text).split())
    if not normalized:
        return "N/A"
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _format_duration(meta_payload: Dict[str, Any]) -> str:
    for key in ("duration_seconds", "duration_sec", "duration"):
        value = meta_payload.get(key)
        if isinstance(value, (int, float)):
            return f"{value:.3f}s"
        if isinstance(value, str) and value.strip():
            return value.strip()

    ms_value = meta_payload.get("duration_ms")
    if isinstance(ms_value, (int, float)):
        return f"{ms_value}ms"
    if isinstance(ms_value, str) and ms_value.strip():
        return ms_value.strip()

    return "N/A (duration not recorded)"


def _status_exit_code_text(status: str) -> str:
    lowered = status.strip().lower()
    if lowered == "success":
        return "0 (derived from run status)"
    if lowered == "blocked":
        return "2 (derived from run status)"
    if lowered:
        return "1 (derived from run status)"
    return "N/A"


def _build_execution_trace(
    config: OrchestratorConfig,
    latest_run: Optional[Dict[str, Any]],
    stdout_path: Optional[Path],
    stderr_path: Optional[Path],
) -> Dict[str, str]:
    trace: Dict[str, str] = {
        "source": "none",
        "source_path": "",
        "command": "N/A",
        "exit_code": "N/A",
        "start_time": "N/A",
        "end_time": "N/A",
        "duration": "N/A",
        "reason": "no execution trace found in evidence_paths",
        "stdout_path": _to_rel_path_text(config, stdout_path) or "N/A",
        "stderr_path": _to_rel_path_text(config, stderr_path) or "N/A",
    }
    run_status = str((latest_run or {}).get("status", ""))
    received_at = str((latest_run or {}).get("received_at", "")).strip()

    meta_candidates = _summaries_meta_candidates(config, latest_run)
    if meta_candidates:
        meta_path = meta_candidates[0]
        meta_payload = _read_json(meta_path)
        if meta_payload:
            extra = meta_payload.get("extra")
            extra_dict = extra if isinstance(extra, dict) else {}
            command_value = extra_dict.get("command")
            if command_value is None:
                command_value = meta_payload.get("command")

            if isinstance(command_value, list):
                command_text = _shorten_single_line(" ".join(str(part) for part in command_value))
            elif command_value is None:
                command_text = "N/A"
            else:
                command_text = _shorten_single_line(command_value)

            exit_code = extra_dict.get("codex_exit_code")
            if exit_code is None:
                exit_code = meta_payload.get("exit_code")
            exit_code_text = "N/A" if exit_code is None else str(exit_code)

            start_time = str(meta_payload.get("started_at", "")).strip()
            if not start_time:
                start_time = "N/A (started_at not recorded)"
            end_time = str(meta_payload.get("ended_at", "")).strip()
            if not end_time:
                end_time = str(meta_payload.get("timestamp", "")).strip()
            if not end_time:
                end_time = received_at or "N/A (end time not recorded)"

            trace.update(
                {
                    "source": "summaries_meta",
                    "source_path": _to_workspace_relative(config, meta_path),
                    "command": command_text,
                    "exit_code": exit_code_text,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": _format_duration(meta_payload),
                    "reason": "",
                }
            )
            return trace

    webhook_path = _find_evidence_path(config, latest_run, "/artifacts/webhooks/")
    webhook_payload = _read_json(webhook_path) if webhook_path else None
    if webhook_payload:
        command = str(webhook_payload.get("summary", "")).strip()
        if not command:
            event_id = str(webhook_payload.get("event_id", "")).strip()
            command = f"event_id={event_id}" if event_id else "N/A"
        trace.update(
            {
                "source": "webhook_payload",
                "source_path": _to_workspace_relative(config, webhook_path) if webhook_path else "",
                "command": command,
                "exit_code": _status_exit_code_text(run_status),
                "start_time": "N/A (webhook payload has no start time)",
                "end_time": received_at or "N/A",
                "duration": "N/A (webhook payload has no duration)",
                "reason": "derived from webhook payload summary/event_id",
            }
        )
        return trace

    return trace


def _detect_shell() -> str:
    comspec = os.environ.get("COMSPEC", "").strip()
    shell_env = os.environ.get("SHELL", "").strip()
    if comspec:
        lowered = comspec.lower()
        if lowered.endswith("cmd.exe"):
            return f"cmd (COMSPEC={comspec})"
        if "powershell" in lowered:
            return f"PowerShell (COMSPEC={comspec})"
        return f"COMSPEC={comspec}"
    if shell_env:
        return f"SHELL={shell_env}"
    return "N/A (COMSPEC/SHELL not set)"


def _make_execution_route(latest_run: Optional[Dict[str, Any]]) -> str:
    event_id = str((latest_run or {}).get("event_id", "")).strip().lower()
    summary = str((latest_run or {}).get("summary", "")).strip().lower()
    if event_id == "make-post" or "make orch-post" in summary:
        return "manual(make orch-post)"
    if event_id.startswith("orch-run-next-local-"):
        return "orch-run-next-local"
    return "N/A (latest run event_id/summary does not identify route)"


def _latest_blocked_run(config: OrchestratorConfig, current_run_id: str) -> Optional[Dict[str, Any]]:
    if not config.runs_dir.exists():
        return None
    for run_path in sorted(config.runs_dir.glob("*_run*.json"), reverse=True):
        payload = _read_json(run_path)
        if not payload:
            continue
        run_id = str(payload.get("run_id", "")).strip()
        if not run_id or run_id == current_run_id:
            continue
        if str(payload.get("status", "")).strip().lower() == "blocked":
            payload["_run_path"] = _to_workspace_relative(config, run_path)
            return payload
    return None


def _scope_guard_reason_class(top_errors: List[str]) -> str:
    text = " ".join(top_errors).lower()
    if "gnumakefile" in text:
        return "GNUmakefile誤検知（allowlist不足）"
    if "scope_guard" in text:
        return "scope_guard検知（詳細は top_errors 参照）"
    return "その他/判定不能"


def _auto_fill_ad_lines(
    config: OrchestratorConfig,
    latest_run: Optional[Dict[str, Any]],
    trace: Dict[str, str],
    stdout_tail: str,
    stderr_tail: str,
    quality_gate: Dict[str, str],
) -> List[str]:
    run = latest_run or {}
    run_id = str(run.get("run_id", "N/A")).strip() or "N/A"
    evidence_paths = run.get("evidence_paths")
    evidence_list = evidence_paths if isinstance(evidence_paths, list) else []
    make_route = _make_execution_route(run)

    ssot_path = (config.workspace_root / CANONICAL_SSOT_REL_PATH).resolve()
    ssot_text = _read_text(ssot_path)
    has_priority_line = bool(ssot_text and "SSOT > runs/latest.json > REPORT_LATEST.md" in ssot_text)

    blocked = _latest_blocked_run(config, run_id)
    blocked_line = "なし"
    blocked_reason_class = "-"
    blocked_reason_detail = "-"
    if blocked:
        blocked_run_id = str(blocked.get("run_id", "N/A")).strip() or "N/A"
        blocked_line = f"{blocked_run_id} (`{blocked.get('_run_path', 'N/A')}`)"
        blocked_errors = blocked.get("top_errors")
        blocked_error_list = [str(item) for item in blocked_errors] if isinstance(blocked_errors, list) else []
        blocked_reason_class = _scope_guard_reason_class(blocked_error_list)
        blocked_reason_detail = blocked_error_list[0] if blocked_error_list else "N/A"

    server_text = _read_text(config.workspace_root / "tools" / "orchestrator" / "server.py") or ""
    gnumakefile_allowed = '"gnumakefile"' in server_text.lower()
    scope_alignment = (
        "allowlist に Makefile/GNUmakefile の両方を維持（現行コードで適用済み）"
        if gnumakefile_allowed
        else "allowlist に Makefile/GNUmakefile の両方を追加する"
    )

    quality_status = quality_gate.get("report_status", "success")
    quality_reason = quality_gate.get("reason", "")
    quality_fix = quality_gate.get("fix", "")
    expected_meta_rel = quality_gate.get("expected_meta_rel", "N/A")
    meta_path = quality_gate.get("meta_path", "N/A")

    command_ok = trace.get("command", "N/A") != "N/A"
    exit_ok = trace.get("exit_code", "N/A") != "N/A"
    time_ok = (
        trace.get("start_time", "N/A") != "N/A"
        and trace.get("end_time", "N/A") != "N/A"
        and trace.get("duration", "N/A") != "N/A"
        and "N/A" not in trace.get("duration", "")
    )
    stdout_ok = stdout_tail is not None
    stderr_ok = stderr_tail is not None
    evidence_ok = isinstance(evidence_list, list) and len(evidence_list) > 0
    blocked_reason_ok = str(run.get("status", "")).strip().lower() != "blocked" or bool(run.get("top_errors"))

    missing: List[str] = []
    if not command_ok:
        missing.append("command")
    if not exit_ok:
        missing.append("exit_code")
    if not time_ok:
        missing.append("start/end/duration")
    if not stdout_ok:
        missing.append("stdout_tail")
    if not stderr_ok:
        missing.append("stderr_tail")
    if not evidence_ok:
        missing.append("evidence_paths")
    if not blocked_reason_ok:
        missing.append("blocked_reason")
    if quality_status == "blocked":
        missing.append("meta_quality_gate")

    missing_text = ", ".join(missing) if missing else "なし"
    fix_proposal = (
        quality_fix
        if quality_status == "blocked" and quality_fix
        else (
            "artifacts/summaries に run_id ごとの .meta.json（command/exit_code/started_at/ended_at/duration_ms）を毎回保存し、evidence_paths へ追加する。"
            if missing
            else "不要（必須項目は充足）"
        )
    )
    quality_line = (
        f"blocked（{quality_reason}）"
        if quality_status == "blocked"
        else "success（必須項目は充足）"
    )

    return [
        "## A-D AUTO-FILL（evidence-based）",
        "",
        "### A. repo / 実行環境",
        f"- repo_root: `{config.workspace_root}`（根拠: report generator config.workspace_root）",
        f"- os: `{platform.system()} ({os.name})`（根拠: 実行環境）",
        f"- shell: `{_detect_shell()}`（根拠: 環境変数 COMSPEC/SHELL）",
        f"- make 実行経路: `{make_route}`（根拠: runs/latest.json event_id=`{run.get('event_id', '')}` summary=`{run.get('summary', '')}`）",
        "- 根拠ファイル: `tools/orchestrator_runtime/runs/latest.json`",
        "",
        "### B. SSOT 優先順位（憲法順位）",
        f"- (1) `{CANONICAL_SSOT_REL_PATH}`（規範）",
        "- (2) `tools/orchestrator_runtime/runs/latest.json`（監査ログ）",
        "- (3) `tools/orchestrator_runtime/reports/REPORT_LATEST.md`（派生レポート）",
        (
            "- 明文化不足: なし"
            if has_priority_line
            else "- 明文化不足: `優先順位は SSOT > runs/latest.json > REPORT_LATEST.md とする。` をSSOTへ1行追記提案（このrunでは未実施）"
        ),
        "- 根拠ファイル: `rules/SSOT_AI_Orchestrator_Loop.md`, `tools/orchestrator_runtime/runs/latest.json`, `tools/orchestrator_runtime/reports/REPORT_LATEST.md`",
        "",
        "### C. REPORTに載せる実行ログ 必須項目",
        f"- QUALITY GATE: {quality_line}",
        f"- required meta path: `{expected_meta_rel}`",
        f"- resolved meta path: `{meta_path}`",
        f"- command: {'OK' if command_ok else '不足'}（{trace.get('command', 'N/A')}）",
        f"- exit_code: {'OK' if exit_ok else '不足'}（{trace.get('exit_code', 'N/A')}）",
        f"- start/end/duration: {'OK' if time_ok else '不足'}（{trace.get('start_time', 'N/A')} / {trace.get('end_time', 'N/A')} / {trace.get('duration', 'N/A')}）",
        f"- stdout_tail: {'OK' if stdout_ok else '不足'}（source={trace.get('stdout_path', 'N/A')}）",
        f"- stderr_tail: {'OK' if stderr_ok else '不足'}（source={trace.get('stderr_path', 'N/A')}）",
        f"- evidence_paths: {'OK' if evidence_ok else '不足'}（count={len(evidence_list)}）",
        f"- blocked_reason: {'OK' if blocked_reason_ok else '不足'}（run status={run.get('status', 'N/A')}）",
        f"- 不足項目: {missing_text}",
        f"- 不足を埋める最小修正（one fix）: {fix_proposal}",
        "- 根拠ファイル: `tools/orchestrator_runtime/runs/latest.json`, `tools/orchestrator_runtime/artifacts/summaries/<run_id>.meta.json`, `tools/orchestrator_runtime/artifacts/summaries/<run_id>.stdout.log`, `tools/orchestrator_runtime/artifacts/summaries/<run_id>.stderr.log`",
        "",
        "### D. scope_guard の現状",
        f"- 直近 blocked run: {blocked_line}",
        f"- 理由分類: {blocked_reason_class}",
        f"- 理由詳細: {blocked_reason_detail}",
        "- 判定ロジック所在: `tools/orchestrator/server.py` の `_is_allowed_path` / `_find_scope_violations` / `_is_make_post_run`",
        f"- 最小の整合案: {scope_alignment}",
        "- 根拠ファイル: `tools/orchestrator_runtime/runs/<run_id>.json`, `tools/orchestrator/server.py`",
        "",
    ]


def _execution_trace_lines(
    config: OrchestratorConfig,
    latest_run: Optional[Dict[str, Any]],
    stdout_path: Optional[Path],
    stderr_path: Optional[Path],
) -> Tuple[List[str], Dict[str, str]]:
    trace = _build_execution_trace(config, latest_run, stdout_path, stderr_path)
    if trace["command"] == "N/A":
        return (
            [
                "## Executed commands",
                f"- N/A ({trace['reason']})",
                "",
            ],
            trace,
        )

    return (
        [
            "## Executed commands",
            f"- source: `{trace['source']}`",
            f"- source_path: `{trace['source_path'] or 'N/A'}`",
            f"- exit_code: `{trace['exit_code']}`",
            f"- start_time: `{trace['start_time']}`",
            f"- end_time: `{trace['end_time']}`",
            f"- duration: `{trace['duration']}`",
            f"- stdout_path: `{trace['stdout_path']}`",
            f"- stderr_path: `{trace['stderr_path']}`",
            f"- note: `{trace['reason']}`" if trace["reason"] else "- note: `-`",
            "- command:",
            "```text",
            trace["command"],
            "```",
            "",
        ],
        trace,
    )


def _git_diff_stat(workspace_root: Path) -> str:
    text, err = _run_git(workspace_root, ["diff", "--stat"])
    if err is not None:
        return f"N/A (git diff failed: {err})"
    return text if text else "(clean working tree)"


def _git_top_changed_files(workspace_root: Path, limit: int = 3) -> List[str]:
    numstat_text, numstat_err = _run_git(workspace_root, ["diff", "--numstat"])
    if numstat_err is None:
        if not numstat_text:
            return ["(clean working tree)"]

        rows: List[Tuple[int, int, int, str]] = []
        for line in numstat_text.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            ins_raw, del_raw, path = parts[0].strip(), parts[1].strip(), parts[2].strip()
            ins = int(ins_raw) if ins_raw.isdigit() else 0
            dele = int(del_raw) if del_raw.isdigit() else 0
            total = ins + dele
            rows.append((total, ins, dele, path))

        if rows:
            rows.sort(key=lambda item: (-item[0], item[3].lower()))
            return [f"- `{path}` (+{ins} / -{dele}, total {total})" for total, ins, dele, path in rows[:limit]]
        return ["(clean working tree)"]

    stat_text, stat_err = _run_git(workspace_root, ["diff", "--stat"])
    if stat_err is not None:
        return [f"N/A ({stat_err})"]
    if not stat_text:
        return ["(clean working tree)"]

    parsed: List[Tuple[int, str]] = []
    for line in stat_text.splitlines():
        match = re.match(r"^\s*(.+?)\s+\|\s+(\d+)\s*", line)
        if not match:
            continue
        path = match.group(1).strip()
        total = int(match.group(2))
        parsed.append((total, path))

    if not parsed:
        return ["N/A (unable to parse git diff output)"]

    parsed.sort(key=lambda item: (-item[0], item[1].lower()))
    return [f"- `{path}` (total {total})" for total, path in parsed[:limit]]


def _first_matching_line(path: Path, needle: str) -> Optional[str]:
    text = _read_text(path)
    if text is None:
        return None
    for lineno, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return f"{lineno}:{line}"
    return None


def _claim_evidence_lines(
    config: OrchestratorConfig,
    latest_run: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], Optional[str]]:
    ssot_rel = "rules/SSOT_AI_Orchestrator_Loop.md"
    latest_json_rel = "tools/orchestrator_runtime/runs/latest.json"
    next_prompt_rel = "tools/orchestrator_runtime/logs/next_prompt.md"
    assistant_rel = "ASSISTANT.md"
    policy_rel = "policy/policy.json"
    runner_log_rel = "tools/orchestrator_runtime/logs/runner_daemon.log"
    ssot_path = config.workspace_root / ssot_rel
    latest_json_path = config.workspace_root / latest_json_rel
    next_prompt_path = config.workspace_root / next_prompt_rel
    assistant_path = config.workspace_root / assistant_rel
    policy_path = config.workspace_root / policy_rel
    runner_log_path = config.workspace_root / runner_log_rel
    run_data = latest_run if isinstance(latest_run, dict) else _read_json(config.latest_run_path) or {}
    policy_map = run_data.get("policy") if isinstance(run_data.get("policy"), dict) else {}
    black_window_map = (
        policy_map.get("black_window") if isinstance(policy_map.get("black_window"), dict) else {}
    )
    milestones_map = (
        policy_map.get("milestones") if isinstance(policy_map.get("milestones"), dict) else {}
    )
    detached_mode_enabled = _as_bool(black_window_map.get("detached_mode", False)) or _as_bool(
        milestones_map.get("black_window_detached_mode", False)
    )
    detach_audit_path = _find_evidence_path(config, run_data, "_blackwindow_detach_audit.md")
    detach_audit_rel = (
        _to_workspace_relative(config, detach_audit_path) if detach_audit_path else "N/A"
    )
    public_release_audit_path = _find_evidence_path(config, run_data, "_public_release_audit.md")
    if public_release_audit_path is None:
        fallback_candidates = sorted(
            config.runtime_root.glob("artifacts/audits/*_public_release_audit.md"),
            key=lambda p: (p.stat().st_mtime if p.exists() else 0.0, p.name.lower()),
        )
        if fallback_candidates:
            public_release_audit_path = fallback_candidates[-1]
    public_release_audit_rel = (
        _to_workspace_relative(config, public_release_audit_path)
        if public_release_audit_path
        else "N/A"
    )

    claims: List[Dict[str, Any]] = [
        {
            "id": "policy.path_normalization",
            "title": "A) policy.path_normalization exists in latest.json",
            "path": latest_json_path,
            "path_text": latest_json_rel,
            "command": 'rg -n -e "\\"path_normalization\\"" tools/orchestrator_runtime/runs/latest.json',
            "needles": ['"path_normalization": {'],
        },
        {
            "id": "policy.enforcement",
            "title": "B) policy.enforcement exists in latest.json",
            "path": latest_json_path,
            "path_text": latest_json_rel,
            "command": 'rg -n -e "\\"enforcement\\"" tools/orchestrator_runtime/runs/latest.json',
            "needles": ['"enforcement": {'],
        },
        {
            "id": "policy.decision_policy",
            "title": "C) policy.decision_policy exists in latest.json",
            "path": latest_json_path,
            "path_text": latest_json_rel,
            "command": 'rg -n -e "\\"decision_policy\\"" tools/orchestrator_runtime/runs/latest.json',
            "needles": ['"decision_policy": {'],
        },
        {
            "id": "next_prompt.hard_scope_policy_blocks",
            "title": "D) next_prompt.md HARD SCOPE reflects these policy blocks",
            "path": next_prompt_path,
            "path_text": next_prompt_rel,
            "command": (
                "rg -n -e \"## HARD SCOPE\" -e \"- path_normalization:\" "
                "-e \"- enforcement:\" -e \"- decision_policy:\" tools/orchestrator_runtime/logs/next_prompt.md"
            ),
            "needles": [
                "## HARD SCOPE",
                "- path_normalization:",
                "- enforcement:",
                "- decision_policy:",
            ],
        },
        {
            "id": "assistant.md.exists",
            "title": "E) ASSISTANT.md exists",
            "path": assistant_path,
            "path_text": assistant_rel,
            "command": "rg -n -e \"ASSISTANT CONSTITUTION PACK\" ASSISTANT.md",
            "needles": ["# ASSISTANT CONSTITUTION PACK"],
        },
        {
            "id": "policy.policy_json.exists",
            "title": "F) policy/policy.json exists",
            "path": policy_path,
            "path_text": policy_rel,
            "command": "rg -n -e \"\\\"version\\\"\" policy/policy.json",
            "needles": ['"version":'],
        },
        {
            "id": "ssot.external_runner_interface.observe_only",
            "title": "G) SSOT external runner interface section exists and links loop_state",
            "path": ssot_path,
            "path_text": ssot_rel,
            "command": (
                "rg -n -e \"## External Runner Interface (Phase1-2: observe-only)\" "
                "-e \"tools/orchestrator_runtime/state/loop_state.json\" "
                "-e \"NO auto Codex start\" rules/SSOT_AI_Orchestrator_Loop.md"
            ),
            "needles": [
                "## External Runner Interface (Phase1-2: observe-only)",
                "tools/orchestrator_runtime/state/loop_state.json",
                "NO auto Codex start",
            ],
        },
        {
            "id": "runner_daemon.exists_and_logs",
            "title": "H) runner daemon exists and logs activity",
            "path": runner_log_path,
            "path_text": runner_log_rel,
            "command": (
                "rg -n -e \"\\\"action\\\": \" tools/orchestrator_runtime/logs/runner_daemon.log"
            ),
            "needles": ['"action": '],
        },
        {
            "id": "public_release.audit_exists",
            "title": "I) public release audit exists",
            "path": public_release_audit_path,
            "path_text": public_release_audit_rel,
            "command": (
                "rg -n public_release_audit.md "
                "tools/orchestrator_runtime/artifacts/audits "
                "tools/orchestrator_runtime/runs/latest.json"
            ),
            "needles": ["# Public Release Audit (OSS Readiness)"],
            "required": False,
        },
    ]
    if detached_mode_enabled:
        claims.append(
            {
                "id": "black_window.detached_server.audit_exists",
                "title": "H) detached server audit exists",
                "path": detach_audit_path,
                "path_text": detach_audit_rel,
                "command": (
                    "rg -n blackwindow_detach_audit.md "
                    "tools/orchestrator_runtime/runs/latest.json tools/orchestrator_runtime/reports/REPORT_LATEST.md"
                ),
                "needles": ["# Black window detach audit"],
                "required": True,
            }
        )

    lines: List[str] = ["## Claim-Evidence Map", ""]
    missing_claim: Optional[str] = None

    for claim in claims:
        claim_id = str(claim.get("id", "")).strip()
        claim_title = str(claim.get("title", "")).strip()
        path = claim.get("path")
        file_text = str(claim.get("path_text", "")).strip()
        command_text = str(claim.get("command", "")).strip()
        needles = claim.get("needles")
        needle_list = needles if isinstance(needles, list) else []
        claim_required = _as_bool(claim.get("required", True))

        matched_lines: List[str] = []
        missing_needles: List[str] = []
        if isinstance(path, Path):
            for needle in needle_list:
                matched = _first_matching_line(path, str(needle))
                if matched is None:
                    missing_needles.append(str(needle))
                else:
                    matched_lines.append(matched)
        else:
            missing_needles = [str(item) for item in needle_list]

        lines.extend(
            [
                f"### {claim_title}",
                f"- claim_id: `{claim_id}`",
                f"- evidence_file: `{file_text}`",
                f"- command: `{command_text}`",
                "- matched_lines:",
                "```text",
                *(matched_lines if matched_lines else ["N/A"]),
                "```",
            ]
        )

        if missing_needles:
            missing_text = ", ".join(missing_needles)
            lines.append(f"- verdict: FAIL (missing patterns: {missing_text})")
            if claim_required and missing_claim is None and claim_id:
                missing_claim = claim_id
        else:
            lines.append("- verdict: PASS")
        lines.append("")

    return lines, missing_claim


def _rules_map_lines(
    config: OrchestratorConfig,
    latest_run: Optional[Dict[str, Any]],
) -> Tuple[List[str], List[str]]:
    rules_entries = [
        ("rules/SSOT_AI_Orchestrator_Loop.md", "canonical SSOT"),
        ("rules/SSOT_FIRST_Orchestrator.md", "SSOT-First guard"),
        ("policy/policy.json", "machine policy source"),
        ("tools/orchestrator/scripts/make_tasks.py", "make entrypoints / run orchestration"),
        ("tools/orchestrator/server.py", "webhook server / health endpoint"),
        ("tools/orchestrator/report.py", "report generation / integrity gates"),
        ("tools/orchestrator_runtime/runs/latest.json", "latest runtime audit state"),
        ("tools/orchestrator_runtime/reports/REPORT_LATEST.md", "latest derived report"),
    ]

    lines: List[str] = ["## Rules Map (file -> role)"]
    contradictions: List[str] = []

    for rel_path, role in rules_entries:
        abs_path = config.workspace_root / rel_path
        exists = abs_path.exists()
        lines.append(f"- `{rel_path}`: {role} ({'exists' if exists else 'missing'})")
        if not exists:
            contradictions.append(f"missing_rules_file:{rel_path}")

    run_map = latest_run if isinstance(latest_run, dict) else {}
    policy_map = run_map.get("policy") if isinstance(run_map.get("policy"), dict) else {}
    ssot_check_map = (
        policy_map.get("ssot_check") if isinstance(policy_map.get("ssot_check"), dict) else {}
    )
    actual_ssot_path = str(ssot_check_map.get("ssot_path", "")).strip()
    expected_ssot_path = CANONICAL_SSOT_REL_PATH

    def _norm_rel_path(text: str) -> str:
        return text.replace("\\", "/").strip().lower()

    if not actual_ssot_path:
        contradictions.append("ssot_path_missing_in_latest_json")
    elif _norm_rel_path(actual_ssot_path) != _norm_rel_path(expected_ssot_path):
        contradictions.append(
            f"ssot_path_mismatch:expected={expected_ssot_path},actual={actual_ssot_path}"
        )

    make_tasks_rel = "tools/orchestrator/scripts/make_tasks.py"
    make_tasks_path = config.workspace_root / make_tasks_rel
    run_next_line = _first_matching_line(make_tasks_path, "def task_orch_run_next_local(")
    idle_signal_line = _first_matching_line(make_tasks_path, 'signal="idle_ready"')
    if idle_signal_line is None:
        idle_signal_line = _first_matching_line(make_tasks_path, "signal='idle_ready'")
    busy_signal_line = _first_matching_line(make_tasks_path, 'signal="busy"')
    if busy_signal_line is None:
        busy_signal_line = _first_matching_line(make_tasks_path, "signal='busy'")

    if run_next_line is None:
        contradictions.append("run_next_entrypoint_missing")
    if idle_signal_line is None:
        contradictions.append("idle_ready_signal_missing")

    lines.extend(
        [
            "- evidence(ssot_path):",
            f"  - expected: `{expected_ssot_path}`",
            f"  - actual: `{actual_ssot_path or 'N/A'}`",
            "- evidence(run_next_local signal hooks):",
            f"  - run_next_entrypoint: `{run_next_line or 'N/A'}`",
            f"  - busy_signal: `{busy_signal_line or 'N/A'}`",
            f"  - idle_ready_signal: `{idle_signal_line or 'N/A'}`",
            "",
            "## Rules Contradictions",
        ]
    )
    if contradictions:
        lines.extend(f"- `{item}`" for item in contradictions)
    else:
        lines.append("- (none)")
    lines.append("")
    return lines, contradictions


def _normalize_command_for_compare(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _is_signal_run(latest_run: Optional[Dict[str, Any]]) -> bool:
    run_map = latest_run if isinstance(latest_run, dict) else {}
    event_id = str(run_map.get("event_id", "")).strip().lower()
    summary = " ".join(str(run_map.get("summary", "")).split()).strip().lower()
    return event_id.startswith("codex-signal") or summary.startswith("make orch-signal")


def _event_specific_verify_commands(latest_run: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    run_map = latest_run if isinstance(latest_run, dict) else {}
    event_id = str(run_map.get("event_id", "")).strip().lower()
    summary = " ".join(str(run_map.get("summary", "")).split()).strip().lower()

    if _is_signal_run(latest_run):
        return ["make orch-signal"]
    if event_id == "make-post" or summary.startswith("make orch-post"):
        return ["make orch-post"]
    if event_id in {"make-report", "manual_report"} or summary.startswith("make orch-report"):
        return ["make orch-report"]
    return None


def _extract_verify_commands(next_prompt_text: Optional[str]) -> List[str]:
    if not next_prompt_text:
        return []

    commands: List[str] = []
    in_verify = False
    for raw in next_prompt_text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_verify = line.lower().startswith("## verify")
            continue
        if not in_verify:
            continue
        match = re.match(r"^-\s*`([^`]+)`\s*$", line)
        if not match:
            continue
        command_text = " ".join(match.group(1).strip().split())
        if command_text:
            commands.append(command_text)
    return _dedupe_strings(commands)


def _extract_command_from_meta(meta_payload: Dict[str, Any]) -> str:
    extra = meta_payload.get("extra")
    extra_map = extra if isinstance(extra, dict) else {}
    command_value: Any = extra_map.get("command")
    if command_value is None:
        command_value = meta_payload.get("command")

    if isinstance(command_value, list):
        command_text = " ".join(str(part) for part in command_value)
    elif command_value is None:
        command_text = ""
    else:
        command_text = str(command_value)
    return " ".join(command_text.split()).strip()


def _executed_commands_from_meta(
    config: OrchestratorConfig, latest_run: Optional[Dict[str, Any]]
) -> Tuple[List[str], List[str]]:
    commands: List[str] = []
    sources: List[str] = []
    for meta_path in _summaries_meta_candidates(config, latest_run):
        meta_payload = _read_json(meta_path)
        if not meta_payload:
            continue
        command_text = _extract_command_from_meta(meta_payload)
        if command_text:
            commands.append(command_text)
        sources.append(_to_workspace_relative(config, meta_path))
    return _dedupe_strings(commands), _dedupe_strings(sources)


def _latest_missing_evidence_run(config: OrchestratorConfig) -> Optional[Dict[str, str]]:
    if not config.runs_dir.exists():
        return None

    for run_path in sorted(config.runs_dir.glob("*_run*.json"), reverse=True):
        payload = _read_json(run_path)
        if not payload:
            continue
        report_error = str(payload.get("report_error", "")).strip()
        if not report_error.startswith("missing_evidence:"):
            continue

        run_id = str(payload.get("run_id", "")).strip() or run_path.stem
        report_path_text = str(payload.get("report_path", "")).strip()
        report_path = _resolve_workspace_path(config, report_path_text) if report_path_text else None
        if report_path is None:
            fallback = config.runtime_root / "reports" / f"{run_id}.md"
            report_path = fallback if fallback.exists() else None

        excerpt = "N/A"
        if report_path and report_path.exists():
            report_text = _read_text(report_path) or ""
            for line in report_text.splitlines():
                if "missing_evidence:" in line:
                    excerpt = line.strip()
                    break
            if excerpt == "N/A" and report_text.strip():
                excerpt = "\n".join(report_text.splitlines()[:6]).strip()
        return {
            "run_id": run_id,
            "report_error": report_error,
            "report_path": _to_workspace_relative(config, report_path) if report_path else "N/A",
            "report_excerpt": excerpt,
        }
    return None


def _report_integrity_gate_lines(
    config: OrchestratorConfig,
    latest_run: Optional[Dict[str, Any]],
    next_prompt_text: Optional[str],
    integrity_policy: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    event_verify_commands = _event_specific_verify_commands(latest_run)
    verify_commands = event_verify_commands or _extract_verify_commands(next_prompt_text)
    executed_commands, meta_sources = _executed_commands_from_meta(config, latest_run)

    enabled = _as_bool(integrity_policy.get("enabled", True))
    require_exec = _as_bool(integrity_policy.get("verify_commands_must_be_executed", True))
    require_cover = _as_bool(
        integrity_policy.get("require_executed_commands_cover_verify_commands", True)
    )
    verify_source_default = str(integrity_policy.get("verify_commands_source", "report.verify_commands"))
    event_id = str((latest_run or {}).get("event_id", "")).strip().lower()
    verify_source = (
        f"event.verify_commands({event_id or 'summary-match'})"
        if event_verify_commands
        else verify_source_default
    )
    executed_source = str(integrity_policy.get("executed_commands_source", "summaries_meta"))

    missing: List[str] = []
    if enabled and require_exec and require_cover:
        executed_norm = {_normalize_command_for_compare(item) for item in executed_commands}
        for command in verify_commands:
            if _normalize_command_for_compare(command) not in executed_norm:
                missing.append(command)

    lines: List[str] = [
        "## Report Integrity Gate",
        f"- enabled: `{str(enabled).lower()}`",
        f"- verify_commands_source: `{verify_source}`",
        f"- executed_commands_source: `{executed_source}`",
        "- verify_commands (declared):",
    ]
    if verify_commands:
        lines.extend(f"- `{item}`" for item in verify_commands)
    else:
        lines.append("- (none)")

    lines.append("- executed_commands (logged):")
    if executed_commands:
        lines.extend(f"- `{item}`" for item in executed_commands)
    else:
        lines.append("- (none)")

    lines.append("- meta_sources:")
    if meta_sources:
        lines.extend(f"- `{item}`" for item in meta_sources)
    else:
        lines.append("- (none)")

    lines.append("- missing_execution_logs:")
    if missing:
        lines.extend(f"- `{item}`" for item in missing)
    else:
        lines.append("- (none)")

    lines.append("- verdict: PASS" if not missing else "- verdict: FAIL")
    lines.append("")
    return lines, missing


def _negative_test_evidence_lines(
    config: OrchestratorConfig,
    integrity_policy: Dict[str, Any],
) -> List[str]:
    required_evidence = integrity_policy.get("required_evidence_for_claims")
    required_evidence_map = required_evidence if isinstance(required_evidence, dict) else {}
    negative_test = required_evidence_map.get("claim_evidence_negative_test")
    negative_test_map = negative_test if isinstance(negative_test, dict) else {}
    enabled = _as_bool(negative_test_map.get("enabled", True))

    lines: List[str] = ["## Negative Test Evidence (missing_evidence)"]
    if not enabled:
        lines.append("- disabled")
        lines.append("")
        return lines

    record = _latest_missing_evidence_run(config)
    if not record:
        lines.extend(
            [
                "- run_id: `None`",
                "- report_error: `None`",
                "- report_path: `None`",
                "```text",
                "None",
                "```",
                "",
            ]
        )
        return lines

    lines.extend(
        [
            f"- run_id: `{record.get('run_id', 'N/A')}`",
            f"- report_error: `{record.get('report_error', 'N/A')}`",
            f"- report_path: `{record.get('report_path', 'N/A')}`",
            "```text",
            record.get("report_excerpt", "N/A"),
            "```",
            "",
        ]
    )
    return lines


def _build_report_text(
    config: OrchestratorConfig,
    *,
    report_status: str,
    report_path: str,
    report_error: str,
) -> Tuple[str, Optional[str], str, str, str]:
    latest_run = _read_json(config.latest_run_path)
    latest_run, stdout_path, stderr_path = _sync_deterministic_logs(config, latest_run)
    if latest_run is None:
        latest_run = {}
    report_integrity_policy = _ensure_report_integrity_policy(latest_run)

    quality_gate = _quality_gate_status(config, latest_run)
    report_status_effective = report_status
    report_error_effective = report_error
    if report_status == "success" and quality_gate.get("report_status") == "blocked":
        report_status_effective = "blocked"
        report_error_effective = quality_gate.get("report_error", "")

    next_prompt_text = _read_text(config.next_prompt_path)
    rules_map_lines, rules_contradictions = _rules_map_lines(config, latest_run)
    if rules_contradictions and report_status_effective == "success":
        report_status_effective = "blocked"
        report_error_effective = f"rules_contradiction:{rules_contradictions[0]}"
    claim_evidence_lines, missing_claim = _claim_evidence_lines(config, latest_run)
    if missing_claim:
        report_status_effective = "blocked"
        report_error_effective = f"missing_evidence:{missing_claim}"

    integrity_gate_lines, missing_execution_logs = _report_integrity_gate_lines(
        config,
        latest_run,
        next_prompt_text,
        report_integrity_policy,
    )
    on_mismatch = str(report_integrity_policy.get("on_mismatch", "blocked")).strip().lower()
    mismatch_prefix = str(
        report_integrity_policy.get("mismatch_error_prefix", "missing_execution_log:")
    ).strip()
    if missing_execution_logs and on_mismatch == "blocked":
        report_status_effective = "blocked"
        report_error_effective = f"{mismatch_prefix}{missing_execution_logs[0]}"

    negative_test_evidence_lines = _negative_test_evidence_lines(config, report_integrity_policy)

    latest_run["report_status"] = report_status_effective
    latest_run["report_path"] = report_path
    latest_run["report_error"] = report_error_effective

    latest_json_text = (
        json.dumps(latest_run, ensure_ascii=False, indent=2) if latest_run else None
    )
    embed_config = latest_run.get("report_embedding")
    embed_latest_json = False
    embed_section_title = "## Latest JSON Snapshot"
    if isinstance(embed_config, dict):
        embed_latest_json = _as_bool(embed_config.get("embed_latest_json_in_report"))
        raw_title = str(embed_config.get("embed_section_title", "")).strip()
        if raw_title:
            embed_section_title = raw_title if raw_title.startswith("#") else f"## {raw_title}"
    latest_json_section_title = embed_section_title if embed_latest_json else "## runs/latest.json"

    run_status = str(latest_run.get("status", "N/A"))
    run_id = str(latest_run.get("run_id", "N/A"))
    timestamp = str(latest_run.get("received_at", "N/A"))
    generated_at = _utc_now_iso()

    stdout_tail = _tail(stdout_path, line_count=TAIL_LINES)
    stderr_tail = _tail(stderr_path, line_count=TAIL_LINES)
    execution_trace_lines, trace = _execution_trace_lines(config, latest_run, stdout_path, stderr_path)
    auto_fill_ad_lines = _auto_fill_ad_lines(
        config, latest_run, trace, stdout_tail, stderr_tail, quality_gate
    )
    latest_audit_path = _select_latest_audit(config, latest_run)
    latest_audit_preview = _audit_preview(latest_audit_path)
    git_stat = _git_diff_stat(config.workspace_root)
    top_changed_files = _git_top_changed_files(config.workspace_root, limit=3)
    policy_map = latest_run.get("policy") if isinstance(latest_run.get("policy"), dict) else {}
    noise_control_map = (
        policy_map.get("noise_control")
        if isinstance(policy_map.get("noise_control"), dict)
        else {}
    )
    enforcement_map = (
        policy_map.get("enforcement")
        if isinstance(policy_map.get("enforcement"), dict)
        else {}
    )
    record_scope_violation_in_report = _as_bool(enforcement_map.get("record_in_report", True))
    scope_violation = (
        latest_run.get("scope_violation")
        if isinstance(latest_run.get("scope_violation"), dict)
        else {}
    )
    stderr_tail_render = stderr_tail
    if scope_violation and _as_bool(noise_control_map.get("enabled", False)):
        if str(noise_control_map.get("stderr_on_scope_violation", "")).strip().lower() == "suppress":
            stderr_tail_render = "(suppressed by noise_control: scope violation)"

    scope_violation_lines: List[str] = []
    if scope_violation and record_scope_violation_in_report:
        scope_violation_lines.extend(
            [
                "## Scope violation",
                f"- raw_path: `{scope_violation.get('raw_path', 'N/A')}`",
                f"- normalized_path: `{scope_violation.get('normalized_path', 'N/A')}`",
                f"- violated_path: `{scope_violation.get('violated_path', 'N/A')}`",
                f"- matched_rule: `{scope_violation.get('matched_rule', 'N/A')}`",
                f"- blocked_action: `{scope_violation.get('blocked_action', 'N/A')}`",
                f"- next_allowed_actions: `{scope_violation.get('next_allowed_actions', 'N/A')}`",
                "",
            ]
        )

    if report_status_effective == "blocked":
        if report_error_effective.startswith("missing_evidence:"):
            ask_text = (
                f"{report_error_effective} 最小修正: tools/orchestrator/report.py の "
                "Claim-Evidence Map の missing patterns を埋める。"
            )
            focus_text = "tools/orchestrator/report.py"
        elif report_error_effective.startswith("missing_execution_log:"):
            ask_text = (
                f"{report_error_effective} 最小修正: VERIFY に宣言したコマンドを "
                "summaries/<run_id>.meta.json の command として記録する。"
            )
            focus_text = "tools/orchestrator/report.py"
        else:
            ask_text = (
                f"{quality_gate.get('reason', 'QUALITY GATE blocked')} "
                f"最小修正: {quality_gate.get('fix', 'tools/orchestrator/server.py を確認')}"
            ).strip()
            focus_text = quality_gate.get("focus_file", "tools/orchestrator/server.py")
    else:
        ask_text = "QUALITY GATE pass: required meta.json keys are complete."
        focus_text = "確認項目: `make orch-health` で /health が 200 を返すこと。"

    lines: List[str] = [
        "# REPORT_LATEST",
        "",
        f"- generated_at: `{generated_at}`",
        f"- status: `{run_status}`",
        f"- run_status: `{run_status}`",
        f"- report_status: `{report_status_effective}`",
        f"- report_error: `{report_error_effective}`",
        f"- run_id: `{run_id}`",
        f"- timestamp: `{timestamp}`",
        "",
        "## next_prompt.md",
        "```markdown",
        next_prompt_text if next_prompt_text is not None else "N/A",
        "```",
        "",
        latest_json_section_title,
        "```json",
        latest_json_text if latest_json_text is not None else "N/A",
        "```",
        "",
        *rules_map_lines,
        *claim_evidence_lines,
        *integrity_gate_lines,
        *negative_test_evidence_lines,
        "## git diff --stat",
        "```text",
        git_stat,
        "```",
        "",
        "## top changed files",
        *top_changed_files,
        "",
        *auto_fill_ad_lines,
        *execution_trace_lines,
        "## stdout tail (~100 lines)",
        f"- source: `{stdout_path}`" if stdout_path else "- source: `(empty)`",
        "```text",
        stdout_tail,
        "```",
        "",
        "## stderr tail (~100 lines)",
        f"- source: `{stderr_path}`" if stderr_path else "- source: `(empty)`",
        "```text",
        stderr_tail_render,
        "```",
        "",
        "## External audit notes",
        f"- source: `{latest_audit_path}`" if latest_audit_path else "- source: `None`",
        "```markdown",
        latest_audit_preview,
        "```",
        "",
        *scope_violation_lines,
        "## ASK / FOCUS",
        f"- ASK: {ask_text}",
        f"- FOCUS: {focus_text}",
        "",
    ]
    report_text = "\n".join(lines)
    archive_name = run_id if re.match(r"^\d{4}-\d{2}-\d{2}_run\d+$", run_id) else None
    return report_text, archive_name, run_id, report_status_effective, report_error_effective


def generate_report(config: Optional[OrchestratorConfig] = None, write_archive: bool = True) -> Dict[str, Path]:
    cfg = config or load_config()
    reports_dir = cfg.runtime_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    latest_run = _read_json(cfg.latest_run_path) or {}
    run_id_hint = str(latest_run.get("run_id", "")).strip()
    latest_path = reports_dir / REPORT_FILENAME

    try:
        report_text, archive_name, run_id, report_status_effective, report_error_effective = _build_report_text(
            cfg,
            report_status="success",
            report_path=_to_rel_path_text(cfg, latest_path),
            report_error="",
        )
        latest_path.write_text(report_text, encoding="utf-8")

        output: Dict[str, Path] = {"latest": latest_path}
        if write_archive and archive_name:
            archive_path = reports_dir / f"{archive_name}.md"
            archive_path.write_text(report_text, encoding="utf-8")
            output["archive"] = archive_path

        _update_report_fields_in_runs(
            cfg,
            run_id=run_id,
            report_status=report_status_effective,
            report_path=_to_rel_path_text(cfg, latest_path),
            report_error=report_error_effective,
        )
        return output
    except Exception as exc:
        error_summary = _short_error_summary(exc)
        failed_path = _write_report_failed(
            cfg,
            run_id=run_id_hint,
            error_summary=error_summary,
        )
        _update_report_fields_in_runs(
            cfg,
            run_id=run_id_hint,
            report_status="failed",
            report_path=_to_rel_path_text(cfg, failed_path),
            report_error=error_summary,
        )
        raise


def main() -> int:
    try:
        paths = generate_report()
    except Exception as exc:  # noqa: BLE001
        print(f"report generation failed: {exc}")
        return 1

    latest = paths.get("latest")
    archive = paths.get("archive")
    if latest:
        print(f"report updated: {latest}")
    if archive:
        print(f"report archived: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
