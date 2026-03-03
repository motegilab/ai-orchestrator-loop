from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import request
from urllib.error import URLError

DEFAULT_REPORT_LATEST = "tools/orchestrator_runtime/reports/REPORT_LATEST.md"
DEFAULT_SERVER_LOG = "tools/orchestrator_runtime/logs/server.log"
DEFAULT_NEXT_PROMPT = "tools/orchestrator_runtime/logs/next_prompt.md"
DEFAULT_RUNNER_DAEMON_LOG = "tools/orchestrator_runtime/logs/runner_daemon.log"
DEFAULT_SCOPE_ALLOWED_READ_PREFIXES = [
    "rules/",
    "tools/orchestrator/",
    "tools/orchestrator_runtime/",
    "GNUmakefile",
    "Makefile",
]
DEFAULT_SCOPE_DENY_READ_PREFIXES = [
    "9990_System/",
    ".git/",
    "node_modules/",
]
DEFAULT_SCOPE_DENY_READ_GLOBS = [
    "**/AGENTS*.md",
    "**/*.secret",
    "**/*.key",
]
DEFAULT_SCOPE_MUST_READ_FIRST = [
    "rules/SSOT_AI_Orchestrator_Loop.md",
    "tools/orchestrator_runtime/runs/latest.json",
    "tools/orchestrator_runtime/reports/REPORT_LATEST.md",
    "tools/orchestrator_runtime/logs/server.log",
]
DEFAULT_SCOPE_RECORD_FIELDS = [
    "violated_path",
    "matched_rule",
    "blocked_action",
    "next_allowed_actions",
]
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
DEFAULT_COMMAND_GUARD_ALLOWED_COMMANDS = [
    "make",
    "type",
    "python",
    "powershell",
    "pwsh",
]
DEFAULT_COMMAND_GUARD_POLICY = {
    "enabled": True,
    "read_targets_must_match_scope": True,
    "on_violation": "abort",
    "violation_message": (
        "COMMAND_GUARD: target path violates policy.scope (denylist or outside allowed prefixes)."
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
DEFAULT_REQUIRED_FIELDS = [
    "hypothesis_one_cause",
    "one_fix",
    "files_changed",
    "verify_commands",
    "exit_codes",
    "stdout_stderr_tail",
    "evidence_paths",
    "decision",
]


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(ts: datetime | None = None) -> str:
    current = ts or _utc_now()
    return current.strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp_for_filename(ts: datetime | None = None) -> str:
    current = ts or _utc_now()
    return current.strftime("%Y%m%dT%H%M%SZ")


def _to_rel_path(path: Path) -> str:
    root = workspace_root().resolve()
    target = path.resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return target.as_posix()


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def _append_evidence_paths(run_payload: dict[str, object], additions: list[str]) -> bool:
    evidence = run_payload.get("evidence_paths")
    evidence_list = [str(item) for item in evidence] if isinstance(evidence, list) else []
    merged = _dedupe_strings([*evidence_list, *additions])
    if merged == evidence_list:
        return False
    run_payload["evidence_paths"] = merged
    return True


def _append_evidence_for_run(run_id: str, additions: list[str]) -> None:
    root = workspace_root()
    runs_dir = root / "tools/orchestrator_runtime/runs"
    targets = [runs_dir / "latest.json", runs_dir / f"{run_id}.json"]
    for target in targets:
        payload = _read_json(target)
        if not payload:
            continue
        if _append_evidence_paths(payload, additions):
            _write_json(target, payload)


def _normalize_captured_output(text: str) -> str:
    normalized = str(text).rstrip()
    return normalized if normalized else "(no output)"


def _run_id_for_date(runs_dir: Path, run_date: datetime) -> str:
    prefix = run_date.strftime("%Y-%m-%d")
    max_num = 0
    pattern = re.compile(rf"^{re.escape(prefix)}_run(\d{{3}})\.json$", re.IGNORECASE)
    for path in runs_dir.glob(f"{prefix}_run*.json"):
        match = pattern.match(path.name)
        if not match:
            continue
        try:
            num = int(match.group(1))
        except ValueError:
            continue
        max_num = max(max_num, num)
    return f"{prefix}_run{max_num + 1:03d}"


def _ensure_contract_fields(run_data: dict[str, object]) -> None:
    run_id = str(run_data.get("run_id", "")).strip()
    paths = run_data.get("paths")
    path_map = paths if isinstance(paths, dict) else {}
    path_map["report_latest"] = DEFAULT_REPORT_LATEST
    path_map["run_report"] = (
        f"tools/orchestrator_runtime/reports/{run_id}.md"
        if run_id
        else "tools/orchestrator_runtime/reports/<run_id>.md"
    )
    path_map["server_log"] = DEFAULT_SERVER_LOG
    run_data["paths"] = path_map

    policy = run_data.get("policy")
    policy_map = policy if isinstance(policy, dict) else {}
    anti_lost = policy_map.get("anti_lost")
    anti_lost_map = anti_lost if isinstance(anti_lost, dict) else {}
    anti_lost_map["must_read_first"] = [
        "runs/latest.json",
        "reports/REPORT_LATEST.md",
        "reports/<run_id>.md",
    ]
    policy_map["anti_lost"] = anti_lost_map

    self_repair = policy_map.get("self_repair_loop")
    self_repair_map = self_repair if isinstance(self_repair, dict) else {}
    self_repair_map["enabled"] = True
    self_repair_map["max_iters"] = 3
    self_repair_map["must_report_each_iter"] = True
    self_repair_map["report_fields_required"] = list(DEFAULT_REQUIRED_FIELDS)
    policy_map["self_repair_loop"] = self_repair_map

    scope = policy_map.get("scope")
    scope_map = scope if isinstance(scope, dict) else {}
    scope_map["repo_root"] = str(scope_map.get("repo_root", "") or workspace_root())
    scope_map["allowed_read_prefixes"] = list(
        scope_map.get("allowed_read_prefixes")
        if isinstance(scope_map.get("allowed_read_prefixes"), list)
        else DEFAULT_SCOPE_ALLOWED_READ_PREFIXES
    )
    scope_map["deny_read_prefixes"] = list(
        scope_map.get("deny_read_prefixes")
        if isinstance(scope_map.get("deny_read_prefixes"), list)
        else DEFAULT_SCOPE_DENY_READ_PREFIXES
    )
    scope_map["deny_read_globs"] = list(
        scope_map.get("deny_read_globs")
        if isinstance(scope_map.get("deny_read_globs"), list)
        else DEFAULT_SCOPE_DENY_READ_GLOBS
    )
    scope_map["must_read_first"] = list(
        scope_map.get("must_read_first")
        if isinstance(scope_map.get("must_read_first"), list)
        else DEFAULT_SCOPE_MUST_READ_FIRST
    )
    policy_map["scope"] = scope_map

    path_normalization = policy_map.get("path_normalization")
    path_normalization_map = path_normalization if isinstance(path_normalization, dict) else {}
    path_normalization_map["enabled"] = bool(
        path_normalization_map.get("enabled", DEFAULT_PATH_NORMALIZATION_POLICY["enabled"])
    )
    path_normalization_map["normalize_slashes"] = bool(
        path_normalization_map.get(
            "normalize_slashes",
            DEFAULT_PATH_NORMALIZATION_POLICY["normalize_slashes"],
        )
    )
    path_normalization_map["lowercase_for_matching"] = bool(
        path_normalization_map.get(
            "lowercase_for_matching",
            DEFAULT_PATH_NORMALIZATION_POLICY["lowercase_for_matching"],
        )
    )
    path_normalization_map["record_fields"] = list(
        path_normalization_map.get("record_fields")
        if isinstance(path_normalization_map.get("record_fields"), list)
        else DEFAULT_PATH_NORMALIZATION_POLICY["record_fields"]
    )
    policy_map["path_normalization"] = path_normalization_map

    enforcement = policy_map.get("enforcement")
    enforcement_map = enforcement if isinstance(enforcement, dict) else {}
    enforcement_map["on_scope_violation"] = str(
        enforcement_map.get("on_scope_violation", "")
        or DEFAULT_ENFORCEMENT_POLICY["on_scope_violation"]
    )
    enforcement_map["abort_on_scope_violation"] = bool(
        enforcement_map.get(
            "abort_on_scope_violation",
            DEFAULT_ENFORCEMENT_POLICY["abort_on_scope_violation"],
        )
    )
    enforcement_map["abort_prompt_generation_on_scope_violation"] = bool(
        enforcement_map.get(
            "abort_prompt_generation_on_scope_violation",
            DEFAULT_ENFORCEMENT_POLICY["abort_prompt_generation_on_scope_violation"],
        )
    )
    enforcement_map["record_in_report"] = bool(
        enforcement_map.get("record_in_report", DEFAULT_ENFORCEMENT_POLICY["record_in_report"])
    )
    enforcement_map["record_fields"] = list(
        enforcement_map.get("record_fields")
        if isinstance(enforcement_map.get("record_fields"), list)
        else DEFAULT_SCOPE_RECORD_FIELDS
    )
    policy_map["enforcement"] = enforcement_map

    ssot_check = policy_map.get("ssot_check")
    ssot_check_map = ssot_check if isinstance(ssot_check, dict) else {}
    ssot_check_map["enabled"] = bool(
        ssot_check_map.get("enabled", DEFAULT_SSOT_CHECK_POLICY["enabled"])
    )
    ssot_check_map["ssot_path"] = str(
        ssot_check_map.get("ssot_path", "") or DEFAULT_SSOT_CHECK_POLICY["ssot_path"]
    )
    ssot_check_map["allow_additional_ssot_files"] = bool(
        ssot_check_map.get(
            "allow_additional_ssot_files",
            DEFAULT_SSOT_CHECK_POLICY["allow_additional_ssot_files"],
        )
    )
    policy_map["ssot_check"] = ssot_check_map

    command_guard = policy_map.get("command_guard")
    command_guard_map = command_guard if isinstance(command_guard, dict) else {}
    command_guard_map["enabled"] = bool(
        command_guard_map.get("enabled", DEFAULT_COMMAND_GUARD_POLICY["enabled"])
    )
    command_guard_map["allowed_commands"] = list(
        command_guard_map.get("allowed_commands")
        if isinstance(command_guard_map.get("allowed_commands"), list)
        else DEFAULT_COMMAND_GUARD_ALLOWED_COMMANDS
    )
    command_guard_map["read_targets_must_match_scope"] = bool(
        command_guard_map.get(
            "read_targets_must_match_scope",
            DEFAULT_COMMAND_GUARD_POLICY["read_targets_must_match_scope"],
        )
    )
    command_guard_map["on_violation"] = str(
        command_guard_map.get("on_violation", "") or DEFAULT_COMMAND_GUARD_POLICY["on_violation"]
    )
    command_guard_map["violation_message"] = str(
        command_guard_map.get("violation_message", "")
        or DEFAULT_COMMAND_GUARD_POLICY["violation_message"]
    )
    policy_map["command_guard"] = command_guard_map

    noise_control = policy_map.get("noise_control")
    noise_control_map = noise_control if isinstance(noise_control, dict) else {}
    noise_control_map["enabled"] = bool(
        noise_control_map.get("enabled", DEFAULT_NOISE_CONTROL_POLICY["enabled"])
    )
    noise_control_map["stderr_on_scope_violation"] = str(
        noise_control_map.get(
            "stderr_on_scope_violation",
            DEFAULT_NOISE_CONTROL_POLICY["stderr_on_scope_violation"],
        )
        or DEFAULT_NOISE_CONTROL_POLICY["stderr_on_scope_violation"]
    )
    noise_control_map["report_scope_violation_in"] = list(
        noise_control_map.get("report_scope_violation_in")
        if isinstance(noise_control_map.get("report_scope_violation_in"), list)
        else DEFAULT_NOISE_CONTROL_POLICY["report_scope_violation_in"]
    )
    noise_control_map["report_fields"] = list(
        noise_control_map.get("report_fields")
        if isinstance(noise_control_map.get("report_fields"), list)
        else DEFAULT_SCOPE_RECORD_FIELDS
    )
    policy_map["noise_control"] = noise_control_map

    decision_policy = policy_map.get("decision_policy")
    decision_policy_map = decision_policy if isinstance(decision_policy, dict) else {}
    decision_policy_map["enabled"] = bool(
        decision_policy_map.get("enabled", DEFAULT_DECISION_POLICY["enabled"])
    )
    decision_policy_map["if_run_status_blocked"] = list(
        decision_policy_map.get("if_run_status_blocked")
        if isinstance(decision_policy_map.get("if_run_status_blocked"), list)
        else DEFAULT_DECISION_POLICY["if_run_status_blocked"]
    )
    decision_policy_map["default_decision"] = str(
        decision_policy_map.get("default_decision", "")
        or DEFAULT_DECISION_POLICY["default_decision"]
    )
    decision_policy_map["priorities"] = list(
        decision_policy_map.get("priorities")
        if isinstance(decision_policy_map.get("priorities"), list)
        else DEFAULT_DECISION_POLICY["priorities"]
    )
    policy_map["decision_policy"] = decision_policy_map
    run_data["policy"] = policy_map

    report_embedding = run_data.get("report_embedding")
    embed_map = report_embedding if isinstance(report_embedding, dict) else {}
    embed_map["embed_latest_json_in_report"] = True
    embed_map["embed_section_title"] = "## Latest JSON Snapshot"
    run_data["report_embedding"] = embed_map


def _format_preflight_audit(preflight: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# Preflight log")
    lines.append(f"- timestamp: {_utc_iso()}")
    lines.append(f"- trace: {preflight.get('trace', '')}")
    lines.append(f"- initial_health: {preflight.get('initial_health', '')}")
    lines.append(f"- restart: {preflight.get('restart', '')}")
    lines.append(f"- final_health: {preflight.get('final_health', '')}")
    attempts = preflight.get("attempts")
    if isinstance(attempts, list) and attempts:
        lines.append("- attempts:")
        for item in attempts:
            if not isinstance(item, dict):
                continue
            step = str(item.get("step", "")).strip()
            ok = str(item.get("ok", "")).strip()
            detail = str(item.get("detail", "")).strip()
            lines.append(f"  - {step}: ok={ok} detail={detail}")
    else:
        lines.append("- attempts: N/A")

    restart_state = str(preflight.get("restart", "skipped")).strip()
    if restart_state and restart_state != "skipped":
        lines.append("")
        lines.append("## Restart failure details")
        lines.append(f"- command: {preflight.get('restart_command', 'N/A')}")
        lines.append(f"- rc: {preflight.get('restart_rc', 'N/A')}")
        lines.append(f"- duration_ms: {preflight.get('restart_duration_ms', 'N/A')}")
        exception_text = str(preflight.get("restart_exception", "")).strip()
        lines.append(f"- exception: {exception_text if exception_text else 'N/A'}")
        if str(preflight.get("restart_rc", "")) == "0":
            lines.append(f"- restart_ok: {preflight.get('restart_ok_info', 'restart ok')}")
        lines.append("- stdout_tail:")
        lines.append("```text")
        lines.append(str(preflight.get("restart_stdout_tail", "(no output)")))
        lines.append("```")
        lines.append("- stderr_tail:")
        lines.append("```text")
        lines.append(str(preflight.get("restart_stderr_tail", "(no output)")))
        lines.append("```")
    return "\n".join(lines).rstrip() + "\n"


def _append_preflight_audit(preflight: dict[str, object]) -> int:
    script = workspace_root() / "tools/orchestrator/scripts/orch_audit.py"
    if not script.exists():
        print("preflight audit skip: orch_audit.py not found")
        return 1
    completed = subprocess.run(
        [sys.executable, str(script)],
        input=_format_preflight_audit(preflight),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.returncode != 0 and completed.stderr.strip():
        print(completed.stderr.strip())
    return int(completed.returncode)


def _record_preflight_blocked(args: argparse.Namespace, preflight: dict[str, object]) -> None:
    root = workspace_root()
    runs_dir = root / "tools/orchestrator_runtime/runs"
    latest_path = runs_dir / "latest.json"
    now = _utc_now()
    run_id = _run_id_for_date(runs_dir, now)
    run_path = runs_dir / f"{run_id}.json"
    latest_prev = _read_json(latest_path)

    blocked_reason = str(preflight.get("blocked_reason", "")).strip() or "health_failed_after_restart"
    summary = f"preflight blocked: {blocked_reason}"
    detail = str(preflight.get("detail_final", "")).strip() or "health check failed after restart"
    top_errors = [f"{blocked_reason}: {detail}"]
    summaries_dir = root / "tools/orchestrator_runtime/artifacts/summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = summaries_dir / f"{run_id}.stdout.log"
    stderr_path = summaries_dir / f"{run_id}.stderr.log"
    meta_path = summaries_dir / f"{run_id}.meta.json"
    restart_meta_path = summaries_dir / f"{run_id}.preflight_restart.meta.json"
    stdout_path.write_text(
        "\n".join(
            [
                f"trace={preflight.get('trace', '')}",
                "restart_stdout_tail:",
                str(preflight.get("restart_stdout_tail", "(no output)")),
                "health_stdout_tail:",
                str(preflight.get("health_final_stdout_tail", "(no output)")),
                "",
            ]
        ),
        encoding="utf-8",
    )
    stderr_path.write_text(
        "\n".join(
            [
                f"{blocked_reason}: {detail}",
                "restart_stderr_tail:",
                str(preflight.get("restart_stderr_tail", "(no output)")),
                "health_stderr_tail:",
                str(preflight.get("health_final_stderr_tail", "(no output)")),
                "",
            ]
        ),
        encoding="utf-8",
    )
    ended = _utc_now()
    duration_ms = int(max(0, (ended - now).total_seconds() * 1000))
    _write_json(
        meta_path,
        {
            "command": "make orch-run-next-local (preflight)",
            "exit_code": 2,
            "started_at": _utc_iso(now),
            "ended_at": _utc_iso(ended),
            "duration_ms": duration_ms,
            "stdout_path": _to_rel_path(stdout_path),
            "stderr_path": _to_rel_path(stderr_path),
            "blocked_reason": blocked_reason,
            "detail": detail,
        },
    )
    _write_json(
        restart_meta_path,
        {
            "command": str(preflight.get("restart_command", "make orch-restart")),
            "exit_code": int(preflight.get("restart_rc", 1)),
            "duration_ms": int(preflight.get("restart_duration_ms", 0)),
            "stdout_tail": str(preflight.get("restart_stdout_tail", "(no output)")),
            "stderr_tail": str(preflight.get("restart_stderr_tail", "(no output)")),
            "health_initial_detail": str(preflight.get("detail_initial", "")),
            "health_final_detail": str(preflight.get("detail_final", "")),
        },
    )

    run_data: dict[str, object] = {}
    if latest_prev:
        run_data.update(latest_prev)
    run_data.update(
        {
            "run_id": run_id,
            "event_id": f"orch-run-next-local-preflight-{_timestamp_for_filename(now)}",
            "received_at": _utc_iso(now),
            "source": "cursor",
            "intent": "status_update",
            "summary": summary,
            "status": "blocked",
            "top_errors": top_errors,
            "next_prompt_path": DEFAULT_NEXT_PROMPT,
            "report_status": "blocked",
            "report_path": DEFAULT_REPORT_LATEST,
            "report_error": f"{blocked_reason}: {detail}",
        }
    )

    evidence_paths = run_data.get("evidence_paths")
    evidence_list = [str(item) for item in evidence_paths] if isinstance(evidence_paths, list) else []
    evidence_list.extend(
        [
            _to_rel_path(run_path),
            DEFAULT_SERVER_LOG,
            _to_rel_path(stdout_path),
            _to_rel_path(stderr_path),
            _to_rel_path(meta_path),
            _to_rel_path(restart_meta_path),
        ]
    )
    deduped: list[str] = []
    seen = set()
    for item in evidence_list:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item.strip())
    run_data["evidence_paths"] = deduped

    _ensure_contract_fields(run_data)
    _write_json(run_path, run_data)
    _write_json(latest_path, run_data)
    _append_preflight_audit(preflight)
    task_orch_report(args)


def _powershell_executable() -> str | None:
    candidates = [
        shutil.which("pwsh"),
        shutil.which("powershell"),
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _run(cmd: list[str]) -> int:
    return subprocess.call(cmd)


def _run_python(script_rel_path: str, args: list[str] | None = None) -> int:
    script = workspace_root() / script_rel_path
    return _run([sys.executable, str(script), *(args or [])])


def task_orch_start(args: argparse.Namespace) -> int:
    print(f"🔄 AI Orchestrator サーバ起動中（127.0.0.1:{args.port}）...")
    return _run_python("tools/orchestrator/server.py")


def task_orch_start_bg(args: argparse.Namespace) -> int:
    print("🔄 AI Orchestrator サーバをバックグラウンドで起動中...")
    return _run_ps_script(
        "tools/orchestrator/scripts/run.ps1",
        ["-BindHost", "127.0.0.1", "-Port", str(args.port), "-TimeoutSeconds", "15"],
    )


def _run_ps_script(script_rel_path: str, ps_args: list[str]) -> int:
    exe = _powershell_executable()
    if not exe:
        print("PowerShell not found")
        return 1
    script = workspace_root() / script_rel_path
    return _run([exe, "-ExecutionPolicy", "Bypass", "-File", str(script), *ps_args])


def _tail_text(text: str, max_lines: int = 200) -> str:
    lines = [line for line in str(text).splitlines()]
    if not lines:
        return "(no output)"
    visible = [line for line in lines if line.strip()]
    if not visible:
        return "(no output)"
    return "\n".join(visible[-max_lines:])


def _run_ps_script_capture(script_rel_path: str, ps_args: list[str]) -> dict[str, object]:
    exe = _powershell_executable()
    if not exe:
        return {
            "rc": 1,
            "stdout": "",
            "stderr": "PowerShell not found",
            "command": f"<missing-powershell> -File {script_rel_path}",
            "duration_ms": 0,
            "exception": "",
        }
    script = workspace_root() / script_rel_path
    cmd = [exe, "-ExecutionPolicy", "Bypass", "-File", str(script), *ps_args]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        duration_ms = int(max(0.0, (time.monotonic() - started) * 1000))
        return {
            "rc": int(completed.returncode),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "command": " ".join(cmd),
            "duration_ms": duration_ms,
            "exception": "",
        }
    except Exception as exc:  # noqa: BLE001
        duration_ms = int(max(0.0, (time.monotonic() - started) * 1000))
        return {
            "rc": 1,
            "stdout": "",
            "stderr": "",
            "command": " ".join(cmd),
            "duration_ms": duration_ms,
            "exception": str(exc),
        }


def task_orch_stop(args: argparse.Namespace) -> int:
    return _run_ps_script("tools/orchestrator/scripts/stop.ps1", ["-Port", str(args.port)])


def task_orch_restart(args: argparse.Namespace) -> int:
    return _run_ps_script(
        "tools/orchestrator/scripts/restart.ps1",
        ["-Port", str(args.port), "-TimeoutSeconds", "15"],
    )


def _check_health(port: int, timeout_seconds: int = 3) -> tuple[bool, str]:
    try:
        with request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status != 200:
                return False, f"status={response.status} body={body}"
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return False, f"invalid_json body={body}"
            if isinstance(payload, dict) and str(payload.get("status", "")).strip().lower() == "ok":
                return True, body
            return False, f"unexpected_payload body={body}"
    except URLError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _latest_run_id() -> str:
    payload = _read_json(workspace_root() / "tools/orchestrator_runtime/runs/latest.json")
    return str(payload.get("run_id", "")).strip()


def _post_signal(
    *,
    port: int,
    signal: str,
    origin_run_id: str = "",
    origin_event: str = "",
) -> int:
    signal_text = str(signal).strip() or "pulse"
    run_id_text = str(origin_run_id).strip()
    event_text = str(origin_event).strip()

    summary = f"make orch-signal ({signal_text})"
    if run_id_text:
        summary += f" origin_run_id={run_id_text}"

    payload: dict[str, object] = {
        "event_id": "codex-signal",
        "status": "ok",
        "command": "make orch-signal",
        "summary": summary,
        "signal": signal_text,
        "source": "codex-cli",
    }
    if run_id_text:
        payload["origin_run_id"] = run_id_text
    if event_text:
        payload["origin_event"] = event_text

    req = request.Request(
        f"http://127.0.0.1:{port}/webhook",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            print(response.read().decode("utf-8", errors="replace"))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"signal post failed ({signal_text}): {exc}")
        return 1


def _ensure_server_for_run_next(args: argparse.Namespace) -> tuple[bool, dict[str, object]]:
    def _health_tails(ok: bool, detail: str) -> tuple[str, str]:
        text = _tail_text(detail)
        if ok:
            return text, "(no output)"
        return "(no output)", text

    attempts: list[dict[str, object]] = []
    ok_initial, detail_initial = _check_health(args.port, timeout_seconds=3)
    initial_stdout_tail, initial_stderr_tail = _health_tails(ok_initial, detail_initial)
    attempts.append({"step": "health_initial", "ok": ok_initial, "detail": detail_initial})
    preflight = {
        "initial_health": "ok" if ok_initial else "failed",
        "restart": "skipped",
        "final_health": "ok" if ok_initial else "failed",
        "trace": "health_ok(no_restart)" if ok_initial else "",
        "detail_initial": detail_initial,
        "detail_final": detail_initial,
        "health_initial_stdout_tail": initial_stdout_tail,
        "health_initial_stderr_tail": initial_stderr_tail,
        "health_final_stdout_tail": initial_stdout_tail,
        "health_final_stderr_tail": initial_stderr_tail,
        "attempts": attempts,
    }
    if ok_initial:
        return True, preflight

    print("⚠️ preflight: orch-health failed. attempting orch-restart...")
    restart_result = _run_ps_script_capture(
        "tools/orchestrator/scripts/restart.ps1",
        ["-Port", str(args.port), "-TimeoutSeconds", "15"],
    )
    restart_rc = int(restart_result.get("rc", 1))
    preflight["restart"] = "executed" if restart_rc == 0 else f"failed(rc={restart_rc})"
    preflight["restart_command"] = str(restart_result.get("command", "")).strip()
    preflight["restart_rc"] = restart_rc
    preflight["restart_duration_ms"] = int(restart_result.get("duration_ms", 0))
    preflight["restart_stdout_tail"] = _tail_text(str(restart_result.get("stdout", "")))
    preflight["restart_stderr_tail"] = _tail_text(str(restart_result.get("stderr", "")))
    preflight["restart_exception"] = str(restart_result.get("exception", "")).strip()
    if restart_rc == 0:
        stdout_text = str(restart_result.get("stdout", ""))
        pid_match = re.search(r"PID\s*=?\s*(\d+)", stdout_text, re.IGNORECASE)
        if pid_match:
            preflight["restart_ok_info"] = f"restart ok (pid={pid_match.group(1)}, port={args.port})"
        else:
            preflight["restart_ok_info"] = f"restart ok (port={args.port})"
    attempts.append(
        {
            "step": "restart",
            "ok": restart_rc == 0,
            "detail": (
                str(preflight.get("restart_ok_info", "restart command completed"))
                if restart_rc == 0
                else f"restart rc={restart_rc}"
            ),
        }
    )

    ok_final = False
    detail_final = detail_initial
    final_stdout_tail = "(no output)"
    final_stderr_tail = _tail_text(detail_initial)
    deadline = time.monotonic() + 15.0
    index = 0
    while time.monotonic() < deadline:
        index += 1
        ok_check, detail_check = _check_health(args.port, timeout_seconds=3)
        check_stdout_tail, check_stderr_tail = _health_tails(ok_check, detail_check)
        attempts.append({"step": f"health_recheck_{index}", "ok": ok_check, "detail": detail_check})
        if ok_check:
            ok_final = True
            detail_final = detail_check
            final_stdout_tail = check_stdout_tail
            final_stderr_tail = check_stderr_tail
            break
        detail_final = detail_check
        final_stdout_tail = check_stdout_tail
        final_stderr_tail = check_stderr_tail
        time.sleep(0.5)

    preflight["final_health"] = "ok" if ok_final else "failed"
    preflight["detail_final"] = detail_final
    preflight["health_final_stdout_tail"] = final_stdout_tail
    preflight["health_final_stderr_tail"] = final_stderr_tail
    preflight["trace"] = (
        f"health_failed->restart_{'ok' if restart_rc == 0 else 'failed'}->health_{'ok' if ok_final else 'failed'}"
    )
    if ok_final:
        return True, preflight

    preflight["blocked_reason"] = "health_failed_after_restart"
    return False, preflight


def task_orch_health(args: argparse.Namespace) -> int:
    print("🩺 AI Orchestrator health 確認中...")
    ok, detail = _check_health(args.port)
    if ok:
        print(detail)
        return 0
    print(detail)
    return 2


def task_orch_post(args: argparse.Namespace) -> int:
    print("📤 AI Orchestrator にテスト POST 送信中...")
    payload = {"event_id": "make-post", "status": "ok", "summary": "make orch-post"}
    req = request.Request(
        f"http://127.0.0.1:{args.port}/webhook",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=10) as response:
        print(response.read().decode("utf-8", errors="replace"))
    return 0


def task_orch_signal(args: argparse.Namespace) -> int:
    signal = str(args.signal or "").strip() or "pulse"
    print(f"📶 AI Orchestrator に signal 送信中... ({signal})")
    origin_run_id = _latest_run_id()
    return _post_signal(
        port=args.port,
        signal=signal,
        origin_run_id=origin_run_id,
        origin_event="manual",
    )


def task_orch_report(_: argparse.Namespace) -> int:
    root = workspace_root()
    report_script = root / "tools/orchestrator/report.py"
    latest_run = _read_json(root / "tools/orchestrator_runtime/runs/latest.json")
    run_id = str(latest_run.get("run_id", "")).strip()
    if not run_id:
        return _run([sys.executable, str(report_script)])

    summaries_dir = root / "tools/orchestrator_runtime/artifacts/summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = summaries_dir / f"{run_id}.report.stdout.log"
    stderr_path = summaries_dir / f"{run_id}.report.stderr.log"
    meta_path = summaries_dir / f"{run_id}.report.meta.json"

    stdout_rel = _to_rel_path(stdout_path)
    stderr_rel = _to_rel_path(stderr_path)
    meta_rel = _to_rel_path(meta_path)
    started = _utc_now()
    started_at = _utc_iso(started)

    stdout_path.write_text("(no output)\n", encoding="utf-8")
    stderr_path.write_text("(no output)\n", encoding="utf-8")
    _write_json(
        meta_path,
        {
            "command": "make orch-report",
            "exit_code": 0,
            "started_at": started_at,
            "ended_at": started_at,
            "duration_ms": 0,
            "stdout_path": stdout_rel,
            "stderr_path": stderr_rel,
        },
    )
    _append_evidence_for_run(run_id, [meta_rel, stdout_rel, stderr_rel])

    first = subprocess.run(
        [sys.executable, str(report_script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    final = first
    second = None
    if first.returncode == 0:
        second = subprocess.run(
            [sys.executable, str(report_script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        final = second

    stdout_parts = [_normalize_captured_output(first.stdout)]
    stderr_parts = [_normalize_captured_output(first.stderr)]
    if second is not None:
        stdout_parts.extend(["[pass2]", _normalize_captured_output(second.stdout)])
        stderr_parts.extend(["[pass2]", _normalize_captured_output(second.stderr)])

    stdout_text = "\n".join(stdout_parts).rstrip() + "\n"
    stderr_text = "\n".join(stderr_parts).rstrip() + "\n"
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")

    ended = _utc_now()
    duration_ms = int(max(0, (ended - started).total_seconds() * 1000))
    _write_json(
        meta_path,
        {
            "command": "make orch-report",
            "exit_code": int(final.returncode),
            "started_at": started_at,
            "ended_at": _utc_iso(ended),
            "duration_ms": duration_ms,
            "stdout_path": stdout_rel,
            "stderr_path": stderr_rel,
        },
    )
    _append_evidence_for_run(run_id, [meta_rel, stdout_rel, stderr_rel])

    if stdout_text.strip():
        print(stdout_text.strip())
    if final.returncode != 0 and stderr_text.strip():
        print(stderr_text.strip())
    return int(final.returncode)


def task_orch_audit(args: argparse.Namespace) -> int:
    script = workspace_root() / "tools/orchestrator/scripts/orch_audit.py"
    cmd = [sys.executable, str(script), "--file", str(args.audit_file or "")]
    return _run(cmd)


def task_orch_setup(_: argparse.Namespace) -> int:
    return _run_ps_script("tools/orchestrator/scripts/setup.ps1", [])


def task_orch_doctor(_: argparse.Namespace) -> int:
    print("🔬 環境チェック...")
    print(sys.version)
    print(f"powershell: {'OK' if shutil.which('powershell') else 'not found'}")
    print(f"pwsh: {'OK' if shutil.which('pwsh') else 'not found'}")
    pw = _powershell_executable()
    print("PowerShell: OK" if pw else "PowerShell: not available (orch-setup には PowerShell が必要)")
    print("Run: make orch-start-bg && make orch-health && make orch-post")
    return 0


def task_orch_run_next(_: argparse.Namespace) -> int:
    print("BLOCKED: Do NOT run orch-run-next from Codex/Cursor. Use real terminal: make orch-run-next-local")
    return 2


def task_orch_run_next_local(args: argparse.Namespace) -> int:
    ready, preflight = _ensure_server_for_run_next(args)
    print(f"preflight: {preflight.get('trace', '')}")
    origin_run_id = _latest_run_id()
    exit_code = 2
    try:
        if not ready:
            print("BLOCKED: preflight failed (health check still failing after restart).")
            print(preflight.get("detail_final", ""))
            _record_preflight_blocked(args, preflight)
            return 2

        print("📶 auto signal: busy")
        _post_signal(
            port=args.port,
            signal="busy",
            origin_run_id=origin_run_id,
            origin_event="orch-run-next-local",
        )

        exit_code = _run_python(
            "tools/orchestrator/scripts/run_next_local.py",
            [
                "--codex-timeout-seconds",
                str(args.codex_timeout),
                "--preflight-json",
                json.dumps(preflight, ensure_ascii=False),
            ],
        )
        _append_preflight_audit(preflight)
        task_orch_report(args)
        return exit_code
    finally:
        final_origin_run_id = _latest_run_id() or origin_run_id
        print("📶 auto signal: idle_ready")
        _post_signal(
            port=args.port,
            signal="idle_ready",
            origin_run_id=final_origin_run_id,
            origin_event="orch-run-next-local",
        )


def task_orch_loop_local(args: argparse.Namespace) -> int:
    return _run_python(
        "tools/orchestrator/scripts/run_next_local.py",
        [
            "--loop",
            "--max-iterations",
            str(args.loop_n),
            "--interval-seconds",
            str(args.loop_interval),
            "--codex-timeout-seconds",
            str(args.codex_timeout),
        ],
    )


def _as_bool_text(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _runner_daemon_args(args: argparse.Namespace, *, once: bool) -> list[str]:
    daemon_args = [
        "--interval-sec",
        str(args.runner_interval_sec),
        "--cooldown-sec",
        str(args.runner_cooldown_sec),
        "--max-cycles",
        str(args.runner_max_cycles),
    ]
    if once:
        daemon_args.append("--once")
    if _as_bool_text(args.runner_observe_only):
        daemon_args.append("--observe-only")
    else:
        daemon_args.append("--no-observe-only")
    if _as_bool_text(args.runner_emit_requires_human_signal):
        daemon_args.append("--emit-requires-human-signal")
    return daemon_args


def task_orch_runner_start(args: argparse.Namespace) -> int:
    return _run_python(
        "tools/orchestrator/runner_daemon.py",
        _runner_daemon_args(args, once=False),
    )


def task_orch_runner_once(args: argparse.Namespace) -> int:
    return _run_python(
        "tools/orchestrator/runner_daemon.py",
        _runner_daemon_args(args, once=True),
    )


def task_orch_runner_log(args: argparse.Namespace) -> int:
    log_path = workspace_root() / DEFAULT_RUNNER_DAEMON_LOG
    if not log_path.exists():
        print(f"runner log not found: {DEFAULT_RUNNER_DAEMON_LOG}")
        return 0
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:  # noqa: BLE001
        print(f"failed to read runner log: {exc}")
        return 1
    tail_n = max(1, int(args.runner_log_tail))
    tail = lines[-tail_n:] if lines else []
    if not tail:
        print("(empty)")
        return 0
    print("\n".join(tail))
    return 0


TASK_HANDLERS = {
    "orch-start": task_orch_start,
    "orch-start-bg": task_orch_start_bg,
    "orch-stop": task_orch_stop,
    "orch-restart": task_orch_restart,
    "orch-health": task_orch_health,
    "orch-post": task_orch_post,
    "orch-signal": task_orch_signal,
    "orch-report": task_orch_report,
    "orch-audit": task_orch_audit,
    "orch-setup": task_orch_setup,
    "orch-doctor": task_orch_doctor,
    "orch-run-next": task_orch_run_next,
    "orch-run-next-local": task_orch_run_next_local,
    "orch-loop-local": task_orch_loop_local,
    "orch-runner-start": task_orch_runner_start,
    "orch-runner-once": task_orch_runner_once,
    "orch-runner-log": task_orch_runner_log,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Thin Makefile task delegator for orchestrator targets.")
    parser.add_argument("--task", required=True, choices=sorted(TASK_HANDLERS))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ORCH_PORT", "8765")))
    parser.add_argument(
        "--codex-timeout", type=int, default=int(os.environ.get("ORCH_CODEX_TIMEOUT", "600"))
    )
    parser.add_argument("--loop-n", type=int, default=int(os.environ.get("ORCH_LOOP_N", "3")))
    parser.add_argument(
        "--loop-interval",
        type=float,
        default=float(os.environ.get("ORCH_LOOP_INTERVAL", "1")),
    )
    parser.add_argument(
        "--runner-interval-sec",
        type=int,
        default=int(os.environ.get("ORCH_RUNNER_INTERVAL_SEC", "600")),
    )
    parser.add_argument(
        "--runner-cooldown-sec",
        type=int,
        default=int(os.environ.get("ORCH_RUNNER_COOLDOWN_SEC", "120")),
    )
    parser.add_argument(
        "--runner-max-cycles",
        type=int,
        default=int(os.environ.get("ORCH_RUNNER_MAX_CYCLES", "50")),
    )
    parser.add_argument(
        "--runner-log-tail",
        type=int,
        default=int(os.environ.get("ORCH_RUNNER_LOG_TAIL", "80")),
    )
    parser.add_argument(
        "--runner-observe-only",
        default=os.environ.get("ORCH_RUNNER_OBSERVE_ONLY", "1"),
    )
    parser.add_argument(
        "--runner-emit-requires-human-signal",
        default=os.environ.get("ORCH_RUNNER_EMIT_REQUIRES_HUMAN_SIGNAL", "0"),
    )
    parser.add_argument("--audit-file", default=os.environ.get("AUDIT_FILE", ""))
    parser.add_argument("--signal", default=os.environ.get("SIGNAL", "pulse"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    handler = TASK_HANDLERS[args.task]
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
