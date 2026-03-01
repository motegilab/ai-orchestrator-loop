from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_INTERVAL_SEC = 600
DEFAULT_COOLDOWN_SEC = 120
DEFAULT_MAX_CYCLES = 50
DEFAULT_LOG_REL_PATH = "tools/orchestrator_runtime/logs/runner_daemon.log"
LOOP_STATE_REL_PATH = "tools/orchestrator_runtime/state/loop_state.json"
LATEST_RUN_REL_PATH = "tools/orchestrator_runtime/runs/latest.json"


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(ts: Optional[datetime] = None) -> str:
    current = ts or _utc_now()
    return current.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc_iso(text: str) -> Optional[datetime]:
    raw = str(text).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _policy_auto_start_enabled(root: Path) -> bool:
    policy_json = _read_json(root / "policy/policy.json")
    external_runner = policy_json.get("external_runner")
    if isinstance(external_runner, dict) and _as_bool(external_runner.get("auto_start_enabled", False)):
        return True

    latest_run = _read_json(root / LATEST_RUN_REL_PATH)
    latest_policy = latest_run.get("policy")
    if not isinstance(latest_policy, dict):
        return False
    latest_external_runner = latest_policy.get("external_runner")
    if not isinstance(latest_external_runner, dict):
        return False
    return _as_bool(latest_external_runner.get("auto_start_enabled", False))


def _latest_top_error(root: Path) -> str:
    latest_run = _read_json(root / LATEST_RUN_REL_PATH)
    top_errors = latest_run.get("top_errors")
    if isinstance(top_errors, list) and top_errors:
        first = str(top_errors[0]).strip()
        if first:
            return first
    return ""


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _tail_text(text: str, max_lines: int = 20) -> str:
    lines = [line for line in str(text).splitlines() if line.strip()]
    if not lines:
        return "(no output)"
    return "\n".join(lines[-max_lines:])


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _last_trigger_time(log_path: Path) -> Optional[datetime]:
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if str(item.get("action", "")).strip() != "trigger_run_next":
            continue
        timestamp = _parse_utc_iso(str(item.get("timestamp", "")).strip())
        if timestamp:
            return timestamp
    return None


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
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


def _append_log_evidence(log_rel_path: str) -> None:
    root = workspace_root()
    latest_path = root / LATEST_RUN_REL_PATH
    latest_run = _read_json(latest_path)
    if not latest_run:
        return

    evidence_raw = latest_run.get("evidence_paths")
    evidence = [str(item) for item in evidence_raw] if isinstance(evidence_raw, list) else []
    merged = _dedupe_strings([*evidence, log_rel_path])
    latest_run["evidence_paths"] = merged
    _write_json(latest_path, latest_run)

    run_id = str(latest_run.get("run_id", "")).strip()
    if not run_id:
        return
    run_path = root / "tools/orchestrator_runtime/runs" / f"{run_id}.json"
    run_payload = _read_json(run_path)
    if not run_payload:
        return
    run_evidence_raw = run_payload.get("evidence_paths")
    run_evidence = [str(item) for item in run_evidence_raw] if isinstance(run_evidence_raw, list) else []
    run_payload["evidence_paths"] = _dedupe_strings([*run_evidence, log_rel_path])
    _write_json(run_path, run_payload)


def _run_make(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _log_record(
    *,
    log_path: Path,
    action: str,
    run_id: str,
    command: str,
    exit_code: Optional[int],
    reason: str,
    state: str,
    requires_human: bool,
    duration_ms: int = 0,
    stdout_tail: str = "",
    stderr_tail: str = "",
    next_prompt_path: str = "",
) -> None:
    _append_jsonl(
        log_path,
        {
            "timestamp": _utc_iso(),
            "action": action,
            "run_id": run_id,
            "command": command,
            "exit_code": exit_code,
            "reason": reason,
            "state": state,
            "requires_human": requires_human,
            "duration_ms": duration_ms,
            "stdout_tail": stdout_tail or "(no output)",
            "stderr_tail": stderr_tail or "(no output)",
            "next_prompt_path": str(next_prompt_path or "").strip(),
        },
    )


def _tick(args: argparse.Namespace) -> int:
    root = workspace_root()
    loop_state_path = root / LOOP_STATE_REL_PATH
    log_path = root / DEFAULT_LOG_REL_PATH
    log_rel_path = DEFAULT_LOG_REL_PATH

    loop_state = _read_json(loop_state_path)
    if not loop_state:
        _log_record(
            log_path=log_path,
            action="skip_missing_loop_state",
            run_id="",
            command="",
            exit_code=None,
            reason=f"loop_state missing or unreadable: {LOOP_STATE_REL_PATH}",
            state="N/A",
            requires_human=True,
        )
        return 0

    run_id = str(loop_state.get("run_id", "")).strip()
    state = str(loop_state.get("state", "")).strip().upper()
    requires_human = _as_bool(loop_state.get("requires_human", False))
    reason = str(loop_state.get("reason", "")).strip()
    next_prompt_path = str(loop_state.get("next_prompt_path", "")).strip()
    top_error = _latest_top_error(root)

    policy_auto_start_enabled = _policy_auto_start_enabled(root)
    auto_start_enabled = bool(args.auto_start) or policy_auto_start_enabled
    effective_observe_only = bool(args.observe_only) or (not auto_start_enabled)

    if state == "BLOCKED" or requires_human:
        signal_exit_code: Optional[int] = None
        signal_tail_stdout = "(no output)"
        signal_tail_stderr = "(no output)"
        human_reason = reason or top_error or f"state={state or 'N/A'} requires_human={requires_human}"
        if args.emit_requires_human_signal and (not effective_observe_only):
            started = time.monotonic()
            completed = _run_make(["orch-signal", "SIGNAL=requires_human"])
            signal_exit_code = int(completed.returncode)
            signal_tail_stdout = _tail_text(completed.stdout)
            signal_tail_stderr = _tail_text(completed.stderr)
            duration_ms = int(max(0.0, (time.monotonic() - started) * 1000))
            _log_record(
                log_path=log_path,
                action="emit_requires_human_signal",
                run_id=run_id,
                command="make orch-signal SIGNAL=requires_human",
                exit_code=signal_exit_code,
                reason=human_reason,
                state=state or "N/A",
                requires_human=requires_human,
                duration_ms=duration_ms,
                stdout_tail=signal_tail_stdout,
                stderr_tail=signal_tail_stderr,
                next_prompt_path=next_prompt_path,
            )
        _log_record(
            log_path=log_path,
            action="requires_human",
            run_id=run_id,
            command="",
            exit_code=signal_exit_code,
            reason=human_reason,
            state=state or "N/A",
            requires_human=requires_human,
            stdout_tail=signal_tail_stdout,
            stderr_tail=signal_tail_stderr,
            next_prompt_path=next_prompt_path,
        )
        _append_log_evidence(log_rel_path)
        return 0

    if state != "IDLE_READY":
        _log_record(
            log_path=log_path,
            action="skip_not_ready",
            run_id=run_id,
            command="",
            exit_code=None,
            reason=reason or f"state={state or 'N/A'}",
            state=state or "N/A",
            requires_human=requires_human,
            next_prompt_path=next_prompt_path,
        )
        _append_log_evidence(log_rel_path)
        return 0

    if effective_observe_only:
        mode_reason = "observe_only: Phase1-2 NO auto Codex start. Run manually when ready."
        if not auto_start_enabled:
            mode_reason = (
                "observe_only: auto-start disabled. "
                "Enable with --auto-start or policy.external_runner.auto_start_enabled=true."
            )
        _log_record(
            log_path=log_path,
            action="recommend_run_next",
            run_id=run_id,
            command="make orch-run-next-local",
            exit_code=None,
            reason=mode_reason,
            state=state,
            requires_human=requires_human,
            next_prompt_path=next_prompt_path,
        )
        _append_log_evidence(log_rel_path)
        return 0

    last_trigger = _last_trigger_time(log_path)
    if last_trigger is not None:
        age_sec = (_utc_now() - last_trigger).total_seconds()
        if age_sec < args.cooldown_sec:
            _log_record(
                log_path=log_path,
                action="skip_cooldown",
                run_id=run_id,
                command="make orch-run-next-local",
                exit_code=None,
                reason=f"cooldown_active age_sec={int(age_sec)} cooldown_sec={args.cooldown_sec}",
                state=state,
                requires_human=requires_human,
                next_prompt_path=next_prompt_path,
            )
            return 0

    started = time.monotonic()
    completed = _run_make(["orch-run-next-local"])
    duration_ms = int(max(0.0, (time.monotonic() - started) * 1000))
    exit_code = int(completed.returncode)
    _log_record(
        log_path=log_path,
        action="trigger_run_next",
        run_id=run_id,
        command="make orch-run-next-local",
        exit_code=exit_code,
        reason="state=IDLE_READY requires_human=false",
        state=state,
        requires_human=requires_human,
        duration_ms=duration_ms,
        stdout_tail=_tail_text(completed.stdout),
        stderr_tail=_tail_text(completed.stderr),
        next_prompt_path=next_prompt_path,
    )
    _append_log_evidence(log_rel_path)
    return exit_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unattended local runner daemon for orchestrator loop_state polling."
    )
    parser.add_argument(
        "--interval-sec",
        type=int,
        default=int(os.environ.get("ORCH_RUNNER_INTERVAL_SEC", str(DEFAULT_INTERVAL_SEC))),
    )
    parser.add_argument(
        "--cooldown-sec",
        type=int,
        default=int(os.environ.get("ORCH_RUNNER_COOLDOWN_SEC", str(DEFAULT_COOLDOWN_SEC))),
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=int(os.environ.get("ORCH_RUNNER_MAX_CYCLES", str(DEFAULT_MAX_CYCLES))),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--auto-start",
        action="store_true",
        default=_as_bool(os.environ.get("ORCH_RUNNER_AUTO_START", "0")),
        help="Opt-in only. Allows auto-start when observe-only is disabled or policy enables it.",
    )
    parser.add_argument(
        "--observe-only",
        dest="observe_only",
        action="store_true",
        default=_as_bool(os.environ.get("ORCH_RUNNER_OBSERVE_ONLY", "1")),
        help="Phase1-2 default. Observe-only mode; never auto-start codex execution.",
    )
    parser.add_argument(
        "--no-observe-only",
        dest="observe_only",
        action="store_false",
        help="Disable observe-only (manual opt-in for future phases).",
    )
    parser.add_argument(
        "--emit-requires-human-signal",
        action="store_true",
        default=_as_bool(os.environ.get("ORCH_RUNNER_EMIT_REQUIRES_HUMAN_SIGNAL", "0")),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    interval_sec = max(1, int(args.interval_sec))
    max_cycles = 1 if args.once else max(1, int(args.max_cycles))

    overall_exit = 0
    for cycle in range(1, max_cycles + 1):
        exit_code = _tick(args)
        if exit_code != 0 and overall_exit == 0:
            overall_exit = exit_code
        if args.once:
            break
        if cycle < max_cycles:
            time.sleep(interval_sec)
    return overall_exit


if __name__ == "__main__":
    raise SystemExit(main())
