from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent))
    from log import (  # type: ignore
        iso_utc,
        next_run_id,
        read_json,
        run_file_for_id,
        short_id,
        timestamp_for_filename,
        to_workspace_relative,
        utc_now,
        write_json,
        write_text,
    )
    from normalize import derive_event_id, derive_source, normalize_payload  # type: ignore
    from planner import generate_next_prompt  # type: ignore
    from report import generate_report  # type: ignore
    from ssot import load_config  # type: ignore
else:
    from .log import (
        iso_utc,
        next_run_id,
        read_json,
        run_file_for_id,
        short_id,
        timestamp_for_filename,
        to_workspace_relative,
        utc_now,
        write_json,
        write_text,
    )
    from .normalize import derive_event_id, derive_source, normalize_payload
    from .planner import generate_next_prompt
    from .report import generate_report
    from .ssot import load_config

CONFIG = load_config()
REPORT_FALLBACK_NAME = "REPORT_FAILED.md"
HEARTBEAT_INTERVAL_SECONDS = 30
SERVER_LOG_REL_PATH = "tools/orchestrator_runtime/logs/server.log"
SERVER_READY_REL_PATH = "tools/orchestrator_runtime/state/server.ready.json"
LOOP_STATE_REL_PATH = "tools/orchestrator_runtime/state/loop_state.json"
REPORT_LATEST_REL_PATH = "tools/orchestrator_runtime/reports/REPORT_LATEST.md"
POLICY_JSON_REL_PATH = "policy/policy.json"
ALLOWED_PATH_PREFIXES = (
    "tools/orchestrator/",
    "tools/orchestrator_runtime/",
    "rules/",
    "policy/",
)
ALLOWED_EXACT_FILES = {"makefile", "gnumakefile", "assistant.md"}
DEFAULT_SCOPE_ALLOWED_READ_PREFIXES = (
    "rules/",
    "tools/orchestrator/",
    "tools/orchestrator_runtime/",
    "policy/",
    "ASSISTANT.md",
    "GNUmakefile",
    "Makefile",
)
DEFAULT_SCOPE_DENY_READ_PREFIXES = (
    "9990_System/",
    ".git/",
    "node_modules/",
)
DEFAULT_SCOPE_DENY_READ_GLOBS = (
    "**/AGENTS*.md",
    "**/*.secret",
    "**/*.key",
)
DEFAULT_SCOPE_MUST_READ_FIRST = (
    "rules/SSOT_AI_Orchestrator_Loop.md",
    "tools/orchestrator_runtime/runs/latest.json",
    "tools/orchestrator_runtime/reports/REPORT_LATEST.md",
    "tools/orchestrator_runtime/logs/server.log",
)
DEFAULT_SCOPE_RECORD_FIELDS = (
    "violated_path",
    "matched_rule",
    "blocked_action",
    "next_allowed_actions",
)
DEFAULT_PATH_NORMALIZATION_POLICY = {
    "enabled": True,
    "normalize_slashes": True,
    "lowercase_for_matching": True,
    "record_fields": ["raw_path", "normalized_path"],
}
DEFAULT_SSOT_CHECK_POLICY = {
    "enabled": True,
    "ssot_path": "rules/SSOT_AI_Orchestrator_Loop.md",
    "allow_additional_ssot_files": False,
}
DEFAULT_COMMAND_GUARD_ALLOWED_COMMANDS = (
    "make",
    "type",
    "python",
    "powershell",
    "pwsh",
)
DEFAULT_COMMAND_GUARD_POLICY = {
    "enabled": True,
    "read_targets_must_match_scope": True,
    "on_violation": "abort",
    "violation_message": (
        "COMMAND_GUARD: target path violates policy.scope "
        "(denylist or outside allowed prefixes)."
    ),
}
DEFAULT_ENFORCEMENT_POLICY = {
    "on_scope_violation": "abort",
    "abort_on_scope_violation": True,
    "abort_prompt_generation_on_scope_violation": True,
    "record_in_report": True,
}
DEFAULT_NOISE_CONTROL_POLICY = {
    "enabled": True,
    "stderr_on_scope_violation": "suppress",
    "report_scope_violation_in": [
        "REPORT_LATEST.md",
        "runs/<run_id>.json",
    ],
}
DEFAULT_DECISION_POLICY = {
    "enabled": True,
    "if_run_status_blocked": [
        {
            "when_top_error_contains": "scope_violation",
            "decision": "Fix scope violation / tighten prompt scope. Do NOT run orch-health.",
        },
        {
            "when_top_error_contains": "health_failed",
            "decision": "Fix preflight/restart health gating. Do NOT read outside allowlist.",
        },
    ],
    "default_decision": "Select ONE FIX from priorities, never 'health check only'.",
    "priorities": [
        "preflight_auto_restart",
        "report_exec_log_completeness",
        "scope_guard_false_positive_reduction",
        "windows_server_console_banner_heartbeat",
    ],
}
SERVER_STATE_LOCK = threading.Lock()
SERVER_STATE: Dict[str, Any] = {
    "request_count": 0,
    "last_webhook_time": "",
    "boot_id": "",
    "started_at": "",
}


def _server_log_path() -> Path:
    return CONFIG.logs_dir / "server.log"


def _server_state_dir() -> Path:
    return CONFIG.runtime_root / "state"


def _server_ready_path() -> Path:
    return _server_state_dir() / "server.ready.json"


def _loop_state_path() -> Path:
    return _server_state_dir() / "loop_state.json"


def _emit_server_log_line(message: str) -> None:
    line = str(message).rstrip()
    if not line:
        return
    print(line, flush=True)
    try:
        CONFIG.logs_dir.mkdir(parents=True, exist_ok=True)
        with _server_log_path().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def _initialize_server_identity() -> None:
    with SERVER_STATE_LOCK:
        if str(SERVER_STATE.get("boot_id", "")).strip():
            return
        SERVER_STATE["boot_id"] = short_id()
        SERVER_STATE["started_at"] = iso_utc(utc_now())


def _server_identity_snapshot() -> Tuple[str, str]:
    with SERVER_STATE_LOCK:
        boot_id = str(SERVER_STATE.get("boot_id", "")).strip()
        started_at = str(SERVER_STATE.get("started_at", "")).strip()
    return boot_id, started_at


def _write_server_ready_state() -> None:
    _initialize_server_identity()
    boot_id, started_at = _server_identity_snapshot()
    request_count, last_webhook_time = _server_state_snapshot()
    health_url = f"http://{CONFIG.host}:{CONFIG.port}/health"
    webhook_url = f"http://{CONFIG.host}:{CONFIG.port}/webhook"
    _server_state_dir().mkdir(parents=True, exist_ok=True)
    write_json(
        _server_ready_path(),
        {
            "status": "ok",
            "boot_id": boot_id,
            "started_at": started_at,
            "pid": os.getpid(),
            "host": CONFIG.host,
            "port": CONFIG.port,
            "health_url": health_url,
            "webhook_url": webhook_url,
            "request_count": request_count,
            "last_webhook_time": last_webhook_time,
            "updated_at": iso_utc(utc_now()),
        },
    )


def _refresh_ready_state_best_effort() -> None:
    try:
        _write_server_ready_state()
    except Exception:
        pass


def _record_request() -> None:
    with SERVER_STATE_LOCK:
        SERVER_STATE["request_count"] = int(SERVER_STATE.get("request_count", 0)) + 1
    _refresh_ready_state_best_effort()


def _record_last_webhook(received_at: str) -> None:
    with SERVER_STATE_LOCK:
        SERVER_STATE["last_webhook_time"] = str(received_at).strip()
    _refresh_ready_state_best_effort()


def _server_state_snapshot() -> Tuple[int, str]:
    with SERVER_STATE_LOCK:
        request_count = int(SERVER_STATE.get("request_count", 0))
        last_webhook_time = str(SERVER_STATE.get("last_webhook_time", "")).strip()
    return request_count, (last_webhook_time or "N/A")


def _heartbeat_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        request_count, last_webhook_time = _server_state_snapshot()
        _emit_server_log_line(
            f"[{iso_utc(utc_now())}] HEARTBEAT status=ok request_count={request_count} "
            f"last_webhook_time={last_webhook_time}"
        )


def _emit_startup_banner() -> None:
    _initialize_server_identity()
    health_url = f"http://{CONFIG.host}:{CONFIG.port}/health"
    webhook_url = f"http://{CONFIG.host}:{CONFIG.port}/webhook"
    boot_id, _started_at = _server_identity_snapshot()
    log_path = _server_log_path()
    ready_path = _server_ready_path()
    try:
        log_rel = to_workspace_relative(log_path, CONFIG.workspace_root)
    except Exception:
        log_rel = SERVER_LOG_REL_PATH
    try:
        ready_rel = to_workspace_relative(ready_path, CONFIG.workspace_root)
    except Exception:
        ready_rel = SERVER_READY_REL_PATH

    _emit_server_log_line("AI Orchestrator Server")
    _emit_server_log_line(f"Boot ID: {boot_id}")
    _emit_server_log_line(f"PID: {os.getpid()}")
    _emit_server_log_line(f"Port: {CONFIG.port}")
    _emit_server_log_line(f"Health URL: {health_url}")
    _emit_server_log_line(f"Webhook URL: {webhook_url}")
    _emit_server_log_line("Stop: make orch-stop")
    _emit_server_log_line("Note: closing this window stops the server.")
    _emit_server_log_line(f"Ready file path: {ready_rel}")
    _emit_server_log_line(f"Log file path: {log_rel}")


def _emit_webhook_signal_line(run_data: Dict[str, Any]) -> None:
    run_id = str(run_data.get("run_id", "")).strip() or "-"
    event_id = str(run_data.get("event_id", "")).strip() or "-"
    status = str(run_data.get("status", "")).strip() or "-"
    summary = " ".join(str(run_data.get("summary", "")).split()).strip() or "-"
    if len(summary) > 140:
        summary = summary[:137].rstrip() + "..."
    _emit_server_log_line(
        f"[{iso_utc(utc_now())}] SIGNAL run_id={run_id} event_id={event_id} status={status} summary={summary}"
    )


def _key_evidence_paths_for_loop_state(run_data: Dict[str, Any]) -> List[str]:
    evidence_raw = run_data.get("evidence_paths")
    evidence_list = evidence_raw if isinstance(evidence_raw, list) else []
    selected: List[str] = []
    for item in evidence_list:
        path_text = str(item).strip()
        if not path_text:
            continue
        lowered = path_text.replace("\\", "/").lower()
        if (
            "/artifacts/webhooks/" in lowered
            or "/runs/" in lowered
            or lowered.endswith(".meta.json")
            or lowered.endswith("next_prompt.md")
            or lowered.endswith("report_latest.md")
            or lowered.endswith("server.log")
        ):
            selected.append(path_text)
    return _dedupe_list(selected)


def _update_loop_state(run_data: Dict[str, Any], payload: Dict[str, Any]) -> str:
    run_id_text = str(run_data.get("run_id", "")).strip()
    run_status = str(run_data.get("status", "")).strip().lower()
    next_prompt_path = str(run_data.get("next_prompt_path", "")).strip()
    if not next_prompt_path:
        next_prompt_path = "tools/orchestrator_runtime/logs/next_prompt.md"

    top_errors_raw = run_data.get("top_errors")
    top_errors = (
        [str(item).strip() for item in top_errors_raw if str(item).strip()]
        if isinstance(top_errors_raw, list)
        else []
    )

    signal = str(payload.get("signal", "")).strip().lower()
    origin_run_id = str(payload.get("origin_run_id", "")).strip()

    if run_status == "blocked" or top_errors:
        state = "BLOCKED"
        requires_human = True
        reason = top_errors[0] if top_errors else "status=blocked"
    elif signal == "busy":
        state = "BUSY"
        requires_human = False
        reason = ""
    elif signal == "idle_ready" and run_status == "success":
        state = "IDLE_READY"
        requires_human = False
        reason = ""
    else:
        state = "IDLE_READY" if run_status == "success" else "BUSY"
        requires_human = False
        reason = ""

    key_evidence = _key_evidence_paths_for_loop_state(run_data)
    key_evidence = _dedupe_list(
        key_evidence
        + [
            next_prompt_path,
            str(run_data.get("report_path", "")).strip(),
            SERVER_LOG_REL_PATH,
        ]
    )

    loop_payload = {
        "updated_at": iso_utc(utc_now()),
        "state": state,
        "run_id": run_id_text,
        "origin_run_id": origin_run_id,
        "next_prompt_path": next_prompt_path,
        "requires_human": requires_human,
        "reason": reason,
        "evidence_paths": key_evidence,
    }

    state_path = _loop_state_path()
    _server_state_dir().mkdir(parents=True, exist_ok=True)
    write_json(state_path, loop_payload)
    return to_workspace_relative(state_path, CONFIG.workspace_root)


class OrchestratorHandler(BaseHTTPRequestHandler):
    server_version = "AIOrchestratorLoop/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        _record_request()
        path = self.path.split("?", 1)[0]
        if path == "/health":
            boot_id, started_at = _server_identity_snapshot()
            request_count, last_webhook_time = _server_state_snapshot()
            try:
                ready_rel = to_workspace_relative(_server_ready_path(), CONFIG.workspace_root)
            except Exception:
                ready_rel = SERVER_READY_REL_PATH
            self._send_json(
                200,
                {
                    "status": "ok",
                    "boot_id": boot_id,
                    "started_at": started_at,
                    "pid": os.getpid(),
                    "request_count": request_count,
                    "last_webhook_time": last_webhook_time,
                    "ready_path": ready_rel,
                },
            )
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        _record_request()
        path = self.path.split("?", 1)[0]
        if path != "/webhook":
            self._send_json(404, {"error": "not_found"})
            return
        self._handle_webhook()

    def _handle_webhook(self) -> None:
        received_ts = utc_now()
        received_at = iso_utc(received_ts)
        timestamp = timestamp_for_filename(received_ts)
        request_short_id = short_id()

        previous_run = read_json(CONFIG.latest_run_path)
        errors: List[str] = []
        _record_last_webhook(received_at)

        payload, parse_error = _parse_request_payload(self)
        if parse_error:
            errors.append(f"payload_parse: {parse_error}")

        server_log_rel = to_workspace_relative(_server_log_path(), CONFIG.workspace_root)
        webhook_rel: str = ""
        try:
            webhook_path = CONFIG.webhooks_dir / f"{timestamp}_{request_short_id}.json"
            write_json(webhook_path, payload)
            webhook_rel = to_workspace_relative(webhook_path, CONFIG.workspace_root)
        except Exception as exc:
            errors.append(f"save_payload: {exc}")

        run_date = received_ts.date()
        run_id = next_run_id(CONFIG.runs_dir, run_date)
        event_id = derive_event_id(payload, fallback=request_short_id)
        source = derive_source(payload, fallback=CONFIG.source)

        next_prompt_rel = to_workspace_relative(CONFIG.next_prompt_path, CONFIG.workspace_root)
        evidence_paths = [path for path in [webhook_rel, server_log_rel] if path]

        try:
            run_data = normalize_payload(
                payload,
                run_id=run_id,
                event_id=event_id,
                received_at=received_at,
                source=source,
                evidence_paths=evidence_paths,
                next_prompt_path=next_prompt_rel,
            )
        except Exception as exc:
            errors.append(f"normalize: {exc}")
            run_data = _fallback_run(
                run_id=run_id,
                event_id=event_id,
                received_at=received_at,
                source=source,
                next_prompt_path=next_prompt_rel,
            )

        run_path = run_file_for_id(CONFIG.runs_dir, run_data["run_id"])
        run_rel = to_workspace_relative(run_path, CONFIG.workspace_root)

        run_data["evidence_paths"] = _dedupe_list(
            list(run_data.get("evidence_paths", [])) + [webhook_rel, run_rel, server_log_rel]
        )

        abort_on_scope_violation = False
        abort_prompt_on_scope_violation = False
        scope_violation = _detect_scope_violation(payload, run_data)
        if scope_violation:
            (
                _scope_policy,
                _path_normalization_policy,
                enforcement_policy,
                _ssot_check_policy,
                _command_guard_policy,
                _noise_control_policy,
                _decision_policy,
            ) = _scope_policy_from_run(run_data)
            abort_on_scope_violation = bool(
                enforcement_policy.get("abort_on_scope_violation", True)
            )
            abort_prompt_on_scope_violation = bool(
                enforcement_policy.get("abort_prompt_generation_on_scope_violation", True)
            )
            run_data["status"] = "blocked"
            run_data["summary"] = "scope_violation: forbidden read path detected."
            run_data["scope_violation"] = scope_violation

            top_errors = run_data.get("top_errors")
            as_list = top_errors if isinstance(top_errors, list) else []
            as_list.append(
                "scope_violation: "
                f"violated_path={scope_violation.get('violated_path', 'N/A')} "
                f"matched_rule={scope_violation.get('matched_rule', 'N/A')}"
            )
            run_data["top_errors"] = _dedupe_list([str(item) for item in as_list])[:5]

            try:
                violation_path = (
                    CONFIG.diffs_dir / f"{timestamp}_{request_short_id}_scope_violation.json"
                )
                write_json(violation_path, scope_violation)
                run_data["evidence_paths"] = _dedupe_list(
                    list(run_data.get("evidence_paths", []))
                    + [to_workspace_relative(violation_path, CONFIG.workspace_root)]
                )
            except Exception as exc:
                errors.append(f"scope_violation_artifact: {exc}")
        else:
            run_data.pop("scope_violation", None)

        if not abort_on_scope_violation:
            scope_violations = _find_scope_violations(CONFIG.workspace_root)
            if scope_violations:
                run_data["status"] = "blocked"
                run_data["summary"] = "Scope guard blocked: changes outside orchestrator allowlist."
                top_errors = run_data.get("top_errors")
                as_list = top_errors if isinstance(top_errors, list) else []
                as_list.append(f"scope_guard: disallowed changes detected ({scope_violations[0]})")
                run_data["top_errors"] = _dedupe_list([str(item) for item in as_list])[:5]

                try:
                    scope_path = CONFIG.diffs_dir / f"{timestamp}_{request_short_id}_scope_guard.txt"
                    write_text(scope_path, _scope_guard_report(scope_violations))
                    run_data["evidence_paths"] = _dedupe_list(
                        list(run_data.get("evidence_paths", []))
                        + [to_workspace_relative(scope_path, CONFIG.workspace_root)]
                    )
                except Exception as exc:
                    errors.append(f"scope_guard_artifact: {exc}")

            if _is_make_post_run(run_data):
                tracked_changes = _find_tracked_diff_paths(CONFIG.workspace_root)
                if tracked_changes:
                    run_data["status"] = "blocked"
                    run_data["summary"] = "Scope guard blocked: make orch-post requires clean git diff."
                    top_errors = run_data.get("top_errors")
                    as_list = top_errors if isinstance(top_errors, list) else []
                    as_list.append(f"scope_guard: tracked diff detected ({tracked_changes[0]})")
                    run_data["top_errors"] = _dedupe_list([str(item) for item in as_list])[:5]

                    try:
                        post_scope_path = (
                            CONFIG.diffs_dir / f"{timestamp}_{request_short_id}_scope_guard_make_post.txt"
                        )
                        write_text(post_scope_path, _make_post_scope_guard_report(tracked_changes))
                        run_data["evidence_paths"] = _dedupe_list(
                            list(run_data.get("evidence_paths", []))
                            + [to_workspace_relative(post_scope_path, CONFIG.workspace_root)]
                        )
                    except Exception as exc:
                        errors.append(f"scope_guard_make_post_artifact: {exc}")

        if errors:
            _merge_errors_into_run(run_data, errors)

        _write_run_files(run_path, run_data, errors)

        try:
            if scope_violation and abort_prompt_on_scope_violation:
                prompt_text = _scope_violation_prompt(run_data, scope_violation)
                write_text(CONFIG.next_prompt_path, prompt_text)
            else:
                prompt_text, blocked = generate_next_prompt(
                    current_run=run_data, previous_run=previous_run, config=CONFIG
                )
                if blocked:
                    run_data["status"] = "blocked"
                    _write_run_files(run_path, run_data, errors)
                write_text(CONFIG.next_prompt_path, prompt_text)
        except Exception as exc:
            errors.append(f"planner: {exc}")
            fallback_prompt = _fallback_prompt(run_data, errors)
            try:
                write_text(CONFIG.next_prompt_path, fallback_prompt)
            except Exception as prompt_exc:
                errors.append(f"write_next_prompt: {prompt_exc}")

        if errors:
            _merge_errors_into_run(run_data, errors)
            _write_run_files(run_path, run_data, errors)

        try:
            meta_rel, stdout_rel, stderr_rel = _write_execution_meta(
                payload=payload,
                run_data=run_data,
                started_ts=received_ts,
                ended_ts=utc_now(),
            )
            run_data["evidence_paths"] = _dedupe_list(
                list(run_data.get("evidence_paths", [])) + [stdout_rel, stderr_rel, meta_rel]
            )
            _write_run_files(run_path, run_data, errors)
        except Exception as exc:
            errors.append(f"write_execution_meta: {_short_error(exc)}")

        try:
            report_paths = generate_report(config=CONFIG, write_archive=True)
            report_path = report_paths.get("latest")
            run_data["report_status"] = "success"
            run_data["report_path"] = (
                to_workspace_relative(report_path, CONFIG.workspace_root)
                if report_path
                else "tools/orchestrator_runtime/reports/REPORT_LATEST.md"
            )
            run_data["report_error"] = ""
        except Exception as exc:
            error_summary = _short_error(exc)
            run_data["report_status"] = "failed"
            run_data["report_error"] = error_summary
            top_errors = run_data.get("top_errors")
            as_list = top_errors if isinstance(top_errors, list) else []
            as_list.append(f"report: {error_summary}")
            run_data["top_errors"] = _dedupe_list([str(item) for item in as_list])[:5]

            failed_path = None
            try:
                failed_path = _write_report_failed(
                    run_id=str(run_data.get("run_id", "-")),
                    error_summary=error_summary,
                )
            except Exception as failed_exc:
                errors.append(f"write_report_failed: {_short_error(failed_exc)}")

            run_data["report_path"] = (
                to_workspace_relative(failed_path, CONFIG.workspace_root)
                if failed_path
                else ""
            )
            errors.append(f"report: {error_summary}")
            print(f"[report] generation failed: {error_summary}")
        finally:
            _merge_report_fields_from_latest(run_data)
            _ensure_report_fields(run_data)
            try:
                loop_state_rel = _update_loop_state(run_data, payload)
                run_data["evidence_paths"] = _dedupe_list(
                    list(run_data.get("evidence_paths", [])) + [loop_state_rel]
                )
            except Exception as exc:
                errors.append(f"loop_state: {_short_error(exc)}")
            _write_run_files(run_path, run_data, errors)
            _emit_webhook_signal_line(run_data)

        self._send_json(
            200,
            {
                "ok": True,
                "run_id": run_data.get("run_id"),
                "status": run_data.get("status"),
                "run_path": run_rel,
                "next_prompt_path": next_prompt_rel,
                "top_errors": run_data.get("top_errors", []),
            },
        )

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _parse_request_payload(handler: BaseHTTPRequestHandler) -> Tuple[Dict[str, Any], Optional[str]]:
    raw_length = handler.headers.get("Content-Length", "0")
    try:
        content_length = int(raw_length)
    except ValueError:
        content_length = 0

    raw = handler.rfile.read(content_length) if content_length > 0 else b"{}"
    text = raw.decode("utf-8", errors="replace")
    if not text.strip():
        return {}, None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"raw_text": text}, str(exc)

    if isinstance(parsed, dict):
        return parsed, None
    return {"payload": parsed}, None


def _fallback_run(
    *,
    run_id: str,
    event_id: str,
    received_at: str,
    source: str,
    next_prompt_path: str,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "event_id": event_id,
        "received_at": received_at,
        "source": source,
        "intent": "status_update",
        "summary": "Normalization failed. Check top_errors.",
        "status": "failed",
        "top_errors": [],
        "evidence_paths": [],
        "next_prompt_path": next_prompt_path,
    }


def _fallback_prompt(run_data: Dict[str, Any], errors: List[str]) -> str:
    lines = [
        "SSOT CHECK",
        "",
        "## SSOT CHECK（必須）",
        "- ssot_path: `(planner fallback: unknown)`",
        "- key_rules:",
        "- Planner fallback modeのため SSOT 抽出は未実施。",
        "- scope: まず planner エラーの原因を1件だけ修正し、SSOT外の変更を行わない。",
        "",
        "## BLOCKED",
        "- status: blocked",
        "- reason: planner fallback was used due to internal error.",
        "- 解除手順: top_errors の先頭原因を1件修正し、Webhook を再送して next_prompt.md を再生成する。",
        "",
        "## DONE",
        f"- Run `{run_data.get('run_id', '-')}` received but planner fallback was used.",
        "",
        "## NEXT",
        "- Inspect top_errors and apply one focused fix.",
        "- Keep changes local and minimal.",
        "",
        "## FAIL",
    ]
    if errors:
        lines.extend([f"- {item}" for item in errors[:5]])
    else:
        lines.append("- Planner failed without explicit error details.")
    lines.extend(
        [
            "",
            "## FIX",
            "- One cause, one fix.",
            "- No large refactor during webhook handling.",
            "",
            "## VERIFY",
            "- Re-run `/health` and `/webhook` checks.",
            "",
        ]
    )
    return "\n".join(lines)


def _scope_violation_prompt(run_data: Dict[str, Any], scope_violation: Dict[str, Any]) -> str:
    lines = [
        "SSOT CHECK",
        "",
        "## SSOT CHECK（必須）",
        "- ssot_path: `rules/SSOT_AI_Orchestrator_Loop.md`",
        "- key_rules:",
        "- scope_violation 時は prompt 生成を継続せず blocked で停止する。",
        "",
        "## BLOCKED",
        "- status: blocked",
        "- reason: scope_violation detected by command_guard/scope policy.",
        f"- violated_path: `{scope_violation.get('violated_path', 'N/A')}`",
        f"- matched_rule: `{scope_violation.get('matched_rule', 'N/A')}`",
        f"- blocked_action: `{scope_violation.get('blocked_action', 'abort')}`",
        "",
        "## NEXT",
        "- Fix scope violation / tighten prompt scope. Do NOT run orch-health.",
        "- Read only allowlisted paths and resend webhook.",
        "",
        "## VERIFY",
        "- Confirm forbidden paths are removed from command/message/payload.",
        "- Re-send webhook and ensure run status is not blocked by scope_violation.",
        "",
    ]
    return "\n".join(lines)


def _merge_errors_into_run(run_data: Dict[str, Any], errors: List[str]) -> None:
    existing = run_data.get("top_errors")
    merged: List[str] = []
    if isinstance(existing, list):
        merged.extend(str(item) for item in existing if str(item).strip())
    merged.extend(str(item) for item in errors if str(item).strip())

    run_data["status"] = "failed"
    run_data["top_errors"] = _dedupe_list(merged)[:5]
    summary = str(run_data.get("summary", "")).strip()
    if "error" not in summary.lower():
        run_data["summary"] = f"{summary} (pipeline errors captured)"


def _write_run_files(run_path: Path, run_data: Dict[str, Any], errors: List[str]) -> None:
    _apply_latest_contract_fields(run_data)
    try:
        write_json(run_path, run_data)
    except Exception as exc:
        errors.append(f"write_run: {exc}")
    try:
        write_json(CONFIG.latest_run_path, run_data)
    except Exception as exc:
        errors.append(f"write_latest: {exc}")


def _dedupe_list(items: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _deep_merge_dict(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(existing, value)
        else:
            merged[key] = value
    return merged


def _load_policy_snapshot() -> Dict[str, Any]:
    policy_path = CONFIG.workspace_root / POLICY_JSON_REL_PATH
    payload = read_json(policy_path)
    if isinstance(payload, dict):
        return payload
    return {}


def _normalize_string_list(value: Any, default: Tuple[str, ...]) -> List[str]:
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if normalized:
            return normalized
    return list(default)


def _normalize_path_for_scope(
    path_text: Any,
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


def _scope_policy_from_run(
    run_data: Dict[str, Any],
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    policy = run_data.get("policy")
    policy_map = policy if isinstance(policy, dict) else {}
    policy_must_read_first = _normalize_string_list(
        policy_map.get("must_read_first"), DEFAULT_SCOPE_MUST_READ_FIRST
    )

    scope = policy_map.get("scope")
    scope_map = scope if isinstance(scope, dict) else {}
    repo_root_raw = str(scope_map.get("repo_root", "")).strip()
    repo_root = repo_root_raw if repo_root_raw else str(CONFIG.workspace_root)

    scope_policy = {
        "repo_root": repo_root,
        "allowed_read_prefixes": _normalize_string_list(
            scope_map.get("allowed_read_prefixes"), DEFAULT_SCOPE_ALLOWED_READ_PREFIXES
        ),
        "deny_read_prefixes": _normalize_string_list(
            scope_map.get("deny_read_prefixes"), DEFAULT_SCOPE_DENY_READ_PREFIXES
        ),
        "deny_read_globs": _normalize_string_list(
            scope_map.get("deny_read_globs"), DEFAULT_SCOPE_DENY_READ_GLOBS
        ),
        "must_read_first": _normalize_string_list(
            scope_map.get("must_read_first"), tuple(policy_must_read_first)
        ),
    }

    path_normalization = policy_map.get("path_normalization")
    path_normalization_map = path_normalization if isinstance(path_normalization, dict) else {}
    path_normalization_policy = {
        "enabled": bool(
            path_normalization_map.get("enabled", DEFAULT_PATH_NORMALIZATION_POLICY["enabled"])
        ),
        "normalize_slashes": bool(
            path_normalization_map.get(
                "normalize_slashes",
                DEFAULT_PATH_NORMALIZATION_POLICY["normalize_slashes"],
            )
        ),
        "lowercase_for_matching": bool(
            path_normalization_map.get(
                "lowercase_for_matching",
                DEFAULT_PATH_NORMALIZATION_POLICY["lowercase_for_matching"],
            )
        ),
        "record_fields": _normalize_string_list(
            path_normalization_map.get("record_fields"),
            tuple(DEFAULT_PATH_NORMALIZATION_POLICY["record_fields"]),
        ),
    }

    enforcement = policy_map.get("enforcement")
    enforcement_map = enforcement if isinstance(enforcement, dict) else {}
    on_violation = (
        str(enforcement_map.get("on_scope_violation", "")).strip()
        or str(DEFAULT_ENFORCEMENT_POLICY["on_scope_violation"])
    )
    record_in_report = bool(enforcement_map.get("record_in_report", True))

    enforcement_policy = {
        "on_scope_violation": on_violation,
        "abort_on_scope_violation": bool(
            enforcement_map.get(
                "abort_on_scope_violation",
                DEFAULT_ENFORCEMENT_POLICY["abort_on_scope_violation"],
            )
        ),
        "abort_prompt_generation_on_scope_violation": bool(
            enforcement_map.get(
                "abort_prompt_generation_on_scope_violation",
                DEFAULT_ENFORCEMENT_POLICY["abort_prompt_generation_on_scope_violation"],
            )
        ),
        "record_in_report": record_in_report,
        "record_fields": _normalize_string_list(
            enforcement_map.get("record_fields"), DEFAULT_SCOPE_RECORD_FIELDS
        ),
    }

    ssot_check = policy_map.get("ssot_check")
    ssot_check_map = ssot_check if isinstance(ssot_check, dict) else {}
    ssot_check_policy = {
        "enabled": bool(ssot_check_map.get("enabled", DEFAULT_SSOT_CHECK_POLICY["enabled"])),
        "ssot_path": str(ssot_check_map.get("ssot_path", "")).strip()
        or str(DEFAULT_SSOT_CHECK_POLICY["ssot_path"]),
        "allow_additional_ssot_files": bool(
            ssot_check_map.get(
                "allow_additional_ssot_files",
                DEFAULT_SSOT_CHECK_POLICY["allow_additional_ssot_files"],
            )
        ),
    }

    command_guard = policy_map.get("command_guard")
    command_guard_map = command_guard if isinstance(command_guard, dict) else {}
    command_guard_policy = {
        "enabled": bool(command_guard_map.get("enabled", DEFAULT_COMMAND_GUARD_POLICY["enabled"])),
        "allowed_commands": _normalize_string_list(
            command_guard_map.get("allowed_commands"), DEFAULT_COMMAND_GUARD_ALLOWED_COMMANDS
        ),
        "read_targets_must_match_scope": bool(
            command_guard_map.get(
                "read_targets_must_match_scope",
                DEFAULT_COMMAND_GUARD_POLICY["read_targets_must_match_scope"],
            )
        ),
        "on_violation": str(command_guard_map.get("on_violation", "")).strip()
        or str(DEFAULT_COMMAND_GUARD_POLICY["on_violation"]),
        "violation_message": str(command_guard_map.get("violation_message", "")).strip()
        or str(DEFAULT_COMMAND_GUARD_POLICY["violation_message"]),
    }

    noise_control = policy_map.get("noise_control")
    noise_control_map = noise_control if isinstance(noise_control, dict) else {}
    noise_control_policy = {
        "enabled": bool(noise_control_map.get("enabled", DEFAULT_NOISE_CONTROL_POLICY["enabled"])),
        "stderr_on_scope_violation": str(
            noise_control_map.get(
                "stderr_on_scope_violation",
                DEFAULT_NOISE_CONTROL_POLICY["stderr_on_scope_violation"],
            )
        ).strip()
        or str(DEFAULT_NOISE_CONTROL_POLICY["stderr_on_scope_violation"]),
        "report_scope_violation_in": _normalize_string_list(
            noise_control_map.get("report_scope_violation_in"),
            tuple(DEFAULT_NOISE_CONTROL_POLICY["report_scope_violation_in"]),
        ),
        "report_fields": _normalize_string_list(
            noise_control_map.get("report_fields"), DEFAULT_SCOPE_RECORD_FIELDS
        ),
    }

    decision_policy = policy_map.get("decision_policy")
    decision_policy_map = decision_policy if isinstance(decision_policy, dict) else {}
    blocked_rules_raw = decision_policy_map.get("if_run_status_blocked")
    blocked_rules = blocked_rules_raw if isinstance(blocked_rules_raw, list) else []
    normalized_rules: List[Dict[str, str]] = []
    for item in blocked_rules:
        if not isinstance(item, dict):
            continue
        needle = str(item.get("when_top_error_contains", "")).strip()
        decision = str(item.get("decision", "")).strip()
        if not needle or not decision:
            continue
        normalized_rules.append(
            {
                "when_top_error_contains": needle,
                "decision": decision,
            }
        )
    if not normalized_rules:
        normalized_rules = list(DEFAULT_DECISION_POLICY["if_run_status_blocked"])  # type: ignore[arg-type]

    decision_policy_normalized = {
        "enabled": bool(decision_policy_map.get("enabled", DEFAULT_DECISION_POLICY["enabled"])),
        "if_run_status_blocked": normalized_rules,
        "default_decision": str(
            decision_policy_map.get("default_decision", "")
            or DEFAULT_DECISION_POLICY["default_decision"]
        ),
        "priorities": _normalize_string_list(
            decision_policy_map.get("priorities"),
            tuple(DEFAULT_DECISION_POLICY["priorities"]),  # type: ignore[arg-type]
        ),
    }

    return (
        scope_policy,
        path_normalization_policy,
        enforcement_policy,
        ssot_check_policy,
        command_guard_policy,
        noise_control_policy,
        decision_policy_normalized,
    )


def _collect_payload_strings(node: Any) -> List[str]:
    collected: List[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str):
                    collected.append(key)
                walk(item)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, str):
            collected.append(value)

    walk(node)
    return collected


def _extract_path_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    pattern = re.compile(r"[A-Za-z0-9_.:-]+(?:[\\/][A-Za-z0-9_.:-]+)+")
    for match in pattern.finditer(text):
        token = match.group(0).strip()
        if token:
            tokens.append(token)

    cleaned = re.sub(r"[\"'`(),;{}\[\]]", " ", text)
    for raw in cleaned.split():
        token = raw.strip().strip(".,:;!?")
        if not token:
            continue
        normalized = token.replace("\\", "/")
        if "/" in normalized or normalized.lower().startswith("9990_system"):
            tokens.append(token)

    return _dedupe_list(tokens)


def _find_path_scope_violation(
    *,
    strings: List[str],
    deny_prefixes: List[str],
    deny_globs: List[str],
    normalize_slashes: bool,
    lowercase_for_matching: bool,
) -> Optional[Tuple[str, str, str]]:
    normalized_prefixes = [
        _normalize_path_for_scope(
            prefix,
            normalize_slashes=normalize_slashes,
            lowercase_for_matching=lowercase_for_matching,
        )
        for prefix in deny_prefixes
        if _normalize_path_for_scope(
            prefix,
            normalize_slashes=normalize_slashes,
            lowercase_for_matching=lowercase_for_matching,
        )
    ]
    normalized_globs = [
        _normalize_path_for_scope(
            pattern,
            normalize_slashes=normalize_slashes,
            lowercase_for_matching=lowercase_for_matching,
        )
        for pattern in deny_globs
        if str(pattern).strip()
    ]

    for raw_text in strings:
        text = str(raw_text)
        candidates = _extract_path_tokens(text)
        if not candidates:
            normalized_text = _normalize_path_for_scope(
                text,
                normalize_slashes=normalize_slashes,
                lowercase_for_matching=lowercase_for_matching,
            )
            if normalized_text:
                candidates = [normalized_text]

        for candidate in candidates:
            raw_candidate = str(candidate).strip()
            normalized = _normalize_path_for_scope(
                candidate,
                normalize_slashes=normalize_slashes,
                lowercase_for_matching=lowercase_for_matching,
            )
            if not normalized:
                continue

            for prefix in normalized_prefixes:
                target = prefix.rstrip("/")
                if not target:
                    continue
                if normalized == target or normalized.startswith(target + "/"):
                    return raw_candidate, normalized, f"deny_read_prefixes:{prefix}"

            for pattern in normalized_globs:
                if fnmatch.fnmatch(normalized, pattern):
                    return raw_candidate, normalized, f"deny_read_globs:{pattern}"

    return None


def _detect_scope_violation(
    payload: Dict[str, Any], run_data: Dict[str, Any]
) -> Optional[Dict[str, str]]:
    (
        scope_policy,
        path_normalization_policy,
        enforcement_policy,
        _ssot_check_policy,
        command_guard_policy,
        _noise_control_policy,
        _decision_policy,
    ) = _scope_policy_from_run(run_data)
    deny_prefixes = scope_policy.get("deny_read_prefixes")
    deny_globs = scope_policy.get("deny_read_globs")
    prefixes = [str(item) for item in deny_prefixes] if isinstance(deny_prefixes, list) else []
    globs = [str(item) for item in deny_globs] if isinstance(deny_globs, list) else []
    normalization_enabled = bool(path_normalization_policy.get("enabled", True))
    normalize_slashes = bool(path_normalization_policy.get("normalize_slashes", True))
    lowercase_for_matching = bool(path_normalization_policy.get("lowercase_for_matching", True))
    if not normalization_enabled:
        normalize_slashes = False
        lowercase_for_matching = False

    guard_enabled = bool(command_guard_policy.get("enabled", True))
    command_text = ""
    for key in ("command", "message", "summary"):
        value = payload.get(key)
        text = " ".join(str(value).split()).strip() if value is not None else ""
        if text:
            command_text = text
            break

    command_name_raw = (
        command_text.split(" ", 1)[0].strip().strip("\"'`").strip(".,:;!?")
        if command_text
        else ""
    )
    command_name = (
        command_name_raw.lower() if (command_name_raw and lowercase_for_matching) else command_name_raw
    )
    if guard_enabled and command_name:
        allowed_raw = command_guard_policy.get("allowed_commands")
        allowed_commands = (
            {
                str(item).strip().lower()
                if lowercase_for_matching
                else str(item).strip()
                for item in allowed_raw
                if str(item).strip()
            }
            if isinstance(allowed_raw, list)
            else set()
        )
        if allowed_commands and command_name not in allowed_commands:
            normalized_command = _normalize_path_for_scope(
                command_name_raw,
                normalize_slashes=normalize_slashes,
                lowercase_for_matching=lowercase_for_matching,
            )
            return {
                "violated_path": normalized_command or command_name,
                "raw_path": command_name_raw or command_name,
                "normalized_path": normalized_command or command_name,
                "matched_rule": "command_guard.allowed_commands",
                "blocked_action": str(command_guard_policy.get("on_violation", "abort")),
                "next_allowed_actions": str(
                    command_guard_policy.get(
                        "violation_message",
                        DEFAULT_COMMAND_GUARD_POLICY["violation_message"],
                    )
                ),
            }

    strings = []
    if guard_enabled and bool(command_guard_policy.get("read_targets_must_match_scope", True)):
        if command_text:
            strings.append(command_text)
    strings.extend(_collect_payload_strings(payload))
    strings.append(str(run_data.get("summary", "")))
    strings.append(str(run_data.get("event_id", "")))

    violation = _find_path_scope_violation(
        strings=strings,
        deny_prefixes=prefixes,
        deny_globs=globs,
        normalize_slashes=normalize_slashes,
        lowercase_for_matching=lowercase_for_matching,
    )
    if not violation:
        return None

    raw_path, normalized_path, matched_rule = violation
    return {
        "violated_path": normalized_path,
        "raw_path": raw_path,
        "normalized_path": normalized_path,
        "matched_rule": matched_rule,
        "blocked_action": str(command_guard_policy.get("on_violation", "abort"))
        if guard_enabled
        else str(enforcement_policy.get("on_scope_violation", "abort")),
        "next_allowed_actions": str(
            command_guard_policy.get(
                "violation_message",
                "COMMAND_GUARD: target path violates policy.scope (denylist or outside allowed prefixes).",
            )
        )
        if guard_enabled
        else "Read only allowed prefixes and resend webhook.",
    }


def _run_report_rel_path(run_id: str) -> str:
    run_id_text = str(run_id).strip()
    if not run_id_text:
        return "tools/orchestrator_runtime/reports/<run_id>.md"
    return f"tools/orchestrator_runtime/reports/{run_id_text}.md"


def _apply_latest_contract_fields(run_data: Dict[str, Any]) -> None:
    run_id_text = str(run_data.get("run_id", "")).strip()

    paths = run_data.get("paths")
    if not isinstance(paths, dict):
        paths = {}
    paths["report_latest"] = REPORT_LATEST_REL_PATH
    paths["run_report"] = _run_report_rel_path(run_id_text)
    paths["server_log"] = SERVER_LOG_REL_PATH
    paths["loop_state"] = LOOP_STATE_REL_PATH
    run_data["paths"] = paths

    policy = run_data.get("policy")
    policy_map = policy if isinstance(policy, dict) else {}
    policy_snapshot = _load_policy_snapshot()
    if policy_snapshot:
        policy_map = _deep_merge_dict(policy_map, policy_snapshot)
        policy_map["source_path"] = POLICY_JSON_REL_PATH

    policy_must_read_first = _normalize_string_list(
        policy_map.get("must_read_first"), DEFAULT_SCOPE_MUST_READ_FIRST
    )
    policy_map["must_read_first"] = list(policy_must_read_first)

    anti_lost = policy_map.get("anti_lost")
    if not isinstance(anti_lost, dict):
        anti_lost = {}
    if not isinstance(anti_lost.get("must_read_first"), list) or not anti_lost.get("must_read_first"):
        anti_lost["must_read_first"] = list(policy_must_read_first)
    policy_map["anti_lost"] = anti_lost

    self_repair_loop = policy_map.get("self_repair_loop")
    if not isinstance(self_repair_loop, dict):
        self_repair_loop = {}
    self_repair_loop["enabled"] = bool(self_repair_loop.get("enabled", True))
    try:
        max_iters = int(self_repair_loop.get("max_iters", 3))
    except (TypeError, ValueError):
        max_iters = 3
    self_repair_loop["max_iters"] = max(max_iters, 1)
    self_repair_loop["must_report_each_iter"] = bool(
        self_repair_loop.get("must_report_each_iter", True)
    )
    self_repair_loop["report_fields_required"] = _normalize_string_list(
        self_repair_loop.get("report_fields_required"),
        (
            "hypothesis_one_cause",
            "one_fix",
            "files_changed",
            "verify_commands",
            "exit_codes",
            "stdout_stderr_tail",
            "evidence_paths",
            "decision",
        ),
    )
    policy_map["self_repair_loop"] = self_repair_loop

    run_data["policy"] = policy_map

    (
        scope_policy,
        path_normalization_policy,
        enforcement_policy,
        ssot_check_policy,
        command_guard_policy,
        noise_control_policy,
        decision_policy,
    ) = _scope_policy_from_run(run_data)
    policy_map["scope"] = scope_policy
    policy_map["path_normalization"] = path_normalization_policy
    policy_map["enforcement"] = enforcement_policy
    policy_map["ssot_check"] = ssot_check_policy
    policy_map["command_guard"] = command_guard_policy
    policy_map["noise_control"] = noise_control_policy
    policy_map["decision_policy"] = decision_policy
    run_data["policy"] = policy_map

    report_embedding = run_data.get("report_embedding")
    if not isinstance(report_embedding, dict):
        report_embedding = {}
    report_embedding["embed_latest_json_in_report"] = True
    report_embedding["embed_section_title"] = "## Latest JSON Snapshot"
    run_data["report_embedding"] = report_embedding


def _short_error(exc: Exception, limit: int = 240) -> str:
    text = " ".join(str(exc).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _merge_report_fields_from_latest(run_data: Dict[str, Any]) -> None:
    latest = read_json(CONFIG.latest_run_path)
    if not latest:
        return

    latest_run_id = str(latest.get("run_id", "")).strip()
    current_run_id = str(run_data.get("run_id", "")).strip()
    if latest_run_id and current_run_id and latest_run_id != current_run_id:
        return

    for key in ("report_status", "report_path", "report_error"):
        if key in latest:
            run_data[key] = latest.get(key, "")


def _ensure_report_fields(run_data: Dict[str, Any]) -> None:
    status = str(run_data.get("report_status", "")).strip().lower()
    if status not in {"success", "failed", "blocked"}:
        run_data["report_status"] = "failed"
    else:
        run_data["report_status"] = status

    run_data["report_path"] = str(run_data.get("report_path", "")).strip()
    run_data["report_error"] = str(run_data.get("report_error", "")).strip()


def _status_to_exit_code(status_text: str) -> int:
    status = status_text.strip().lower()
    if status == "success":
        return 0
    if status == "blocked":
        return 2
    return 1


def _derive_command_text(payload: Dict[str, Any], run_data: Dict[str, Any]) -> str:
    for key in ("command", "summary"):
        value = payload.get(key)
        if value is None:
            continue
        text = " ".join(str(value).split()).strip()
        if text:
            return text

    run_summary = " ".join(str(run_data.get("summary", "")).split()).strip()
    if run_summary:
        return run_summary

    event_id = " ".join(str(run_data.get("event_id", "")).split()).strip()
    if event_id:
        return event_id
    return "N/A"


def _write_execution_meta(
    *,
    payload: Dict[str, Any],
    run_data: Dict[str, Any],
    started_ts,
    ended_ts,
) -> Tuple[str, str, str]:
    run_id = str(run_data.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("run_id is missing")

    stdout_path = CONFIG.summaries_dir / f"{run_id}.stdout.log"
    stderr_path = CONFIG.summaries_dir / f"{run_id}.stderr.log"
    meta_path = CONFIG.summaries_dir / f"{run_id}.meta.json"

    if not stdout_path.exists():
        write_text(stdout_path, "")
    if not stderr_path.exists():
        write_text(stderr_path, "")

    duration_ms = int(max(0.0, (ended_ts - started_ts).total_seconds() * 1000))
    meta_payload = {
        "command": _derive_command_text(payload, run_data),
        "exit_code": _status_to_exit_code(str(run_data.get("status", ""))),
        "started_at": iso_utc(started_ts),
        "ended_at": iso_utc(ended_ts),
        "duration_ms": duration_ms,
        "stdout_path": to_workspace_relative(stdout_path, CONFIG.workspace_root),
        "stderr_path": to_workspace_relative(stderr_path, CONFIG.workspace_root),
    }
    write_json(meta_path, meta_payload)

    return (
        to_workspace_relative(meta_path, CONFIG.workspace_root),
        to_workspace_relative(stdout_path, CONFIG.workspace_root),
        to_workspace_relative(stderr_path, CONFIG.workspace_root),
    )


def _scope_guard_report(violations: List[str]) -> str:
    lines = [
        "scope_guard: blocked",
        "reason: changes outside orchestrator allowlist detected",
        "allowed_prefixes:",
        *[f"- {item}" for item in ALLOWED_PATH_PREFIXES],
        "allowed_exact_files:",
        *[f"- {item}" for item in sorted(ALLOWED_EXACT_FILES)],
        "allowed_config_pattern: config*.yaml",
        "violations:",
        *[f"- {path}" for path in violations],
    ]
    return "\n".join(lines)


def _make_post_scope_guard_report(changed_paths: List[str]) -> str:
    lines = [
        "scope_guard: blocked",
        "reason: make orch-post requires `git diff --name-only` to be empty",
        "event_filter: event_id == make-post OR summary contains 'make orch-post'",
        "tracked_changes:",
        *[f"- {path}" for path in changed_paths],
    ]
    return "\n".join(lines)


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


def _is_allowed_path(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/").lstrip("./").strip()
    if not normalized:
        return True
    lowered = normalized.lower()

    if lowered in ALLOWED_EXACT_FILES:
        return True
    if any(lowered.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
        return True

    name = Path(normalized).name.lower()
    if name.startswith("config") and name.endswith(".yaml"):
        return True
    return False


def _find_scope_violations(workspace_root: Path) -> List[str]:
    tracked, tracked_error = _run_git(workspace_root, ["diff", "--name-only"])
    untracked, untracked_error = _run_git(
        workspace_root, ["ls-files", "--others", "--exclude-standard"]
    )

    combined = _dedupe_list(tracked + untracked)
    violations = [path for path in combined if not _is_allowed_path(path)]

    if tracked_error:
        violations.append(f"[git diff error] {tracked_error}")
    if untracked_error:
        violations.append(f"[git ls-files error] {untracked_error}")
    return _dedupe_list(violations)


def _find_tracked_diff_paths(workspace_root: Path) -> List[str]:
    tracked, tracked_error = _run_git(workspace_root, ["diff", "--name-only"])
    if tracked_error:
        return [f"[git diff error] {tracked_error}"]
    return _dedupe_list(tracked)


def _is_make_post_run(run_data: Dict[str, Any]) -> bool:
    event_id = str(run_data.get("event_id", "")).strip().lower()
    summary = str(run_data.get("summary", "")).strip().lower()
    return event_id == "make-post" or "make orch-post" in summary


def _write_report_failed(*, run_id: str, error_summary: str) -> Path:
    failed_path = CONFIG.runtime_root / "reports" / REPORT_FALLBACK_NAME
    lines = [
        "# REPORT_FAILED",
        "",
        f"- run_id: `{run_id}`",
        f"- error_summary: {error_summary}",
        "- next_action: restart server / rerun orch-report",
        "",
    ]
    write_text(failed_path, "\n".join(lines))
    return failed_path


def main() -> None:
    _initialize_server_identity()
    server = ThreadingHTTPServer((CONFIG.host, CONFIG.port), OrchestratorHandler)
    stop_event = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(stop_event,),
        daemon=True,
        name="orchestrator-heartbeat",
    )
    _emit_startup_banner()
    _emit_server_log_line(
        f"[{iso_utc(utc_now())}] INFO listening on http://{CONFIG.host}:{CONFIG.port}"
    )
    _refresh_ready_state_best_effort()
    _emit_server_log_line("KIDOU_SUCCESS (起動成功): AI Orchestrator Server is ready.")
    heartbeat_thread.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=1.0)
        try:
            _server_ready_path().unlink(missing_ok=True)
        except Exception:
            pass
        _emit_server_log_line(f"[{iso_utc(utc_now())}] INFO server stopped")
        server.server_close()


if __name__ == "__main__":
    main()
