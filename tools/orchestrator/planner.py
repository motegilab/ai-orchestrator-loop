from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from .ssot import OrchestratorConfig
except ImportError:
    from ssot import OrchestratorConfig  # type: ignore

DEFAULT_SSOT_REL_PATH = Path("rules/SSOT_AI_Orchestrator_Loop.md")
DEFAULT_POLICY_REL_PATH = Path("policy/policy.json")
MIN_KEY_RULES = 3
MAX_KEY_RULES = 8
KEY_RULE_PATTERNS = [
    re.compile(r"\bmust\b", re.I),
    re.compile(r"\brule\b", re.I),
    re.compile(r"\brequired\b", re.I),
    re.compile(r"禁止"),
    re.compile(r"必須"),
    re.compile(r"ルール"),
    re.compile(r"厳守"),
]
DEFAULT_SCOPE_ALLOWED_READ_PREFIXES = [
    "rules/",
    "tools/orchestrator/",
    "tools/orchestrator_runtime/",
    "policy/",
    "ASSISTANT.md",
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
DEFAULT_COMMAND_GUARD_ALLOWED_COMMANDS = [
    "make",
    "type",
    "python",
    "powershell",
    "pwsh",
]
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


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _string_list(value: Any, default: List[str]) -> List[str]:
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if normalized:
            return normalized
    return list(default)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _deep_merge_dict(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(existing, value)
        else:
            merged[key] = value
    return merged


def _load_policy_snapshot(config: Optional[OrchestratorConfig]) -> Dict[str, Any]:
    if not config:
        return {}
    policy_path = (config.workspace_root / DEFAULT_POLICY_REL_PATH).resolve()
    payload = _read_json(policy_path)
    if isinstance(payload, dict):
        return payload
    return {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _resolve_path_from_workspace(path_text: str, config: Optional[OrchestratorConfig]) -> Optional[Path]:
    text = str(path_text or "").strip().strip("\"'")
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path.resolve()
    if config:
        return (config.workspace_root / path).resolve()
    return path.resolve()


def _to_workspace_rel(path: Path, config: Optional[OrchestratorConfig]) -> str:
    if config:
        try:
            return path.resolve().relative_to(config.workspace_root.resolve()).as_posix()
        except Exception:
            pass
    return path.as_posix()


def _extract_ask_focus(report_text: str) -> Tuple[str, str]:
    ask = ""
    focus = ""
    for raw in report_text.splitlines():
        line = raw.strip()
        if line.startswith("- ASK:"):
            ask = line[len("- ASK:") :].strip()
        elif line.startswith("- FOCUS:"):
            focus = line[len("- FOCUS:") :].strip()
    return ask, focus


def _extract_report_status(report_text: str) -> str:
    for raw in report_text.splitlines():
        line = raw.strip()
        if not line.startswith("- report_status:"):
            continue
        value = line.split(":", 1)[1].strip().strip("`")
        return value.lower()
    return ""


def _top_errors_from_runs(
    current_run: Dict[str, Any], latest_run: Dict[str, Any]
) -> List[str]:
    top_errors_raw = current_run.get("top_errors")
    if not isinstance(top_errors_raw, list):
        top_errors_raw = latest_run.get("top_errors")
    if not isinstance(top_errors_raw, list):
        return []
    return [str(item).strip() for item in top_errors_raw if str(item).strip()]


def _blocked_decision_from_policy(top_error: str, decision_policy: Dict[str, Any]) -> str:
    needle_source = top_error.lower()
    rules_raw = decision_policy.get("if_run_status_blocked")
    if not isinstance(rules_raw, list):
        return ""
    for item in rules_raw:
        if not isinstance(item, dict):
            continue
        needle = str(item.get("when_top_error_contains", "")).strip().lower()
        decision = str(item.get("decision", "")).strip()
        if needle and decision and needle in needle_source:
            return decision
    return ""


def _focus_path_from_error(top_error: str) -> str:
    if not top_error:
        return ""
    pattern = re.compile(r"([A-Za-z0-9_./\\-]+\.(?:py|md|json|ya?ml|txt|log|ps1|bat|sh))")
    match = pattern.search(top_error)
    if not match:
        return ""
    return match.group(1).replace("\\", "/")


def _derive_ecp1_ask_focus(
    *,
    current_run: Dict[str, Any],
    latest_run: Dict[str, Any],
    report_latest_text: str,
    decision_policy: Dict[str, Any],
) -> Tuple[str, str]:
    run_status = str(latest_run.get("status", current_run.get("status", ""))).strip().lower()
    report_status = str(latest_run.get("report_status", "")).strip().lower()
    if not report_status:
        report_status = _extract_report_status(report_latest_text)

    top_errors = _top_errors_from_runs(current_run, latest_run)
    top_error = top_errors[0] if top_errors else ""

    if run_status == "blocked":
        ask = top_error or "blocked"
        mapped_fix = _blocked_decision_from_policy(top_error, decision_policy)
        if mapped_fix:
            ask = f"{ask} 最小修正: {mapped_fix}"
        return ask, _focus_path_from_error(top_error)

    if run_status == "success" and report_status == "success" and not top_errors:
        return "No action needed.", ""

    if top_error:
        return top_error, _focus_path_from_error(top_error)

    if run_status == "success":
        return "No action needed.", ""
    if run_status == "failed":
        return "Run failed. Reproduce the latest error and apply one-cause-one-fix.", ""
    return "Status unclear. Re-check latest evidence and apply one minimal fix.", ""


def _derive_one_fix(ask: str, focus: str, current_run: Dict[str, Any]) -> str:
    ask_text = str(ask).strip()
    focus_text = str(focus).strip()
    if "最小修正:" in ask_text:
        return ask_text.split("最小修正:", 1)[1].strip() or ask_text
    if ask_text and "pass" not in ask_text.lower():
        return ask_text
    if focus_text:
        return focus_text
    summary = str(current_run.get("summary", "")).strip()
    if summary:
        return f"summary「{summary[:120]}」に対して one-cause-one-fix の最小差分を実施する。"
    return "one-cause-one-fix の最小差分を実施する。"


def _apply_decision_policy(
    *,
    base_decision: str,
    ask: str,
    current_run: Dict[str, Any],
    latest_run: Dict[str, Any],
    decision_policy: Dict[str, Any],
) -> Tuple[str, str]:
    if not _as_bool(decision_policy.get("enabled")):
        return base_decision, "decision_policy.enabled=false; fallback to ASK/FOCUS."

    run_status = str(latest_run.get("status", current_run.get("status", ""))).strip().lower()
    top_errors_raw = current_run.get("top_errors")
    if not isinstance(top_errors_raw, list):
        top_errors_raw = latest_run.get("top_errors")
    top_errors = (
        [str(item) for item in top_errors_raw]
        if isinstance(top_errors_raw, list)
        else []
    )
    joined_errors = " | ".join(top_errors).lower()
    ask_text = str(ask).strip().lower()

    if run_status == "blocked":
        rules_raw = decision_policy.get("if_run_status_blocked")
        if isinstance(rules_raw, list):
            for item in rules_raw:
                if not isinstance(item, dict):
                    continue
                needle = str(item.get("when_top_error_contains", "")).strip().lower()
                decision = str(item.get("decision", "")).strip()
                if needle and decision and needle in joined_errors:
                    return (
                        decision,
                        f"matched blocked rule: when_top_error_contains='{needle}'",
                    )
        if "scope_guard" in joined_errors and "docs/" in joined_errors:
            return (
                "scope_guard_false_positive_reduction",
                "matched blocked rule: scope_guard docs path => scope-only fix.",
            )

    if run_status == "success" and "no action needed" in ask_text:
        return (
            "no_op",
            "matched rule: ask_no_action_overrides_priority (run_status='success').",
        )

    default_decision = str(decision_policy.get("default_decision", "")).strip()
    priorities_raw = decision_policy.get("priorities")
    priorities = (
        [str(item).strip() for item in priorities_raw if str(item).strip()]
        if isinstance(priorities_raw, list)
        else []
    )
    if priorities:
        return (
            priorities[0],
            f"run_status='{run_status or 'unknown'}' selected priorities[0].",
        )
    if default_decision:
        return (
            default_decision,
            f"run_status='{run_status or 'unknown'}' fallback default_decision.",
        )
    return (
        base_decision,
        f"run_status='{run_status or 'unknown'}' fallback ASK/FOCUS.",
    )


def _event_specific_verify_commands(
    *, current_run: Dict[str, Any], latest_run: Dict[str, Any]
) -> List[str]:
    run = latest_run if isinstance(latest_run, dict) else current_run
    event_id = str(run.get("event_id", current_run.get("event_id", ""))).strip().lower()
    summary = " ".join(
        str(run.get("summary", current_run.get("summary", ""))).split()
    ).strip().lower()

    if event_id == "make-post" or summary.startswith("make orch-post"):
        return ["make orch-post"]
    if event_id in {"make-report", "manual_report"} or summary.startswith("make orch-report"):
        return ["make orch-report"]
    return ["make orch-post", "make orch-report"]


def _normalize_rule_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith("#"):
        return ""

    normalized = re.sub(r"^[\-\*\u2022\d\.\)\(]+\s*", "", stripped)
    normalized = re.sub(r"^#{1,6}\s*", "", normalized)
    normalized = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", normalized)
    normalized = normalized.replace("**", "").replace("__", "").replace("`", "")
    normalized = re.sub(r"\s+", " ", normalized).strip(" -*\t")
    if not normalized:
        return ""
    return normalized[:220].strip()


def _extract_key_rules(raw_lines: List[str]) -> List[str]:
    picked: List[str] = []
    seen = set()

    def add_rule(text: str) -> None:
        normalized = _normalize_rule_line(text)
        if not normalized:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        picked.append(normalized)

    for line in raw_lines:
        normalized = _normalize_rule_line(line)
        if not normalized:
            continue
        if any(pat.search(normalized) for pat in KEY_RULE_PATTERNS):
            add_rule(normalized)
        if len(picked) >= MAX_KEY_RULES:
            break

    if len(picked) < MIN_KEY_RULES:
        for line in raw_lines:
            normalized = _normalize_rule_line(line)
            if not normalized:
                continue
            add_rule(normalized)
            if len(picked) >= MIN_KEY_RULES:
                break

    return picked[:MAX_KEY_RULES]


def _load_ssot_key_rules(ssot_path: Path) -> Optional[List[str]]:
    """SSOT を読み、key_rules(3-8) を返す。読めない場合は None。"""
    if not ssot_path.exists():
        return None
    try:
        text = ssot_path.read_text(encoding="utf-8")
    except Exception:
        return None
    raw_lines = [s.rstrip() for s in text.splitlines()]
    if not raw_lines:
        return None

    key_rules = _extract_key_rules(raw_lines)
    if len(key_rules) < MIN_KEY_RULES:
        return None
    return key_rules


def _resolve_ssot_path(config: Optional[OrchestratorConfig]) -> Optional[Path]:
    if config and getattr(config, "ssot_path", None):
        return config.ssot_path
    if config:
        return (config.workspace_root / DEFAULT_SSOT_REL_PATH).resolve()
    return DEFAULT_SSOT_REL_PATH.resolve()


def _scope_line(current_run: Dict[str, Any]) -> str:
    intent = str(current_run.get("intent", "status_update"))
    summary = str(current_run.get("summary", "")).strip()
    if summary:
        return (
            f"intent `{intent}` と summary「{summary[:120]}」に直接関係する最小差分のみ実施し、"
            "SSOT外の変更は行わない。"
        )
    return f"intent `{intent}` に直接関係する最小差分のみ実施し、SSOT外の変更は行わない。"


def _scope_policy_from_latest(
    latest_run: Dict[str, Any], config: Optional[OrchestratorConfig]
) -> Dict[str, Any]:
    policy = latest_run.get("policy")
    policy_map = policy if isinstance(policy, dict) else {}
    scope = policy_map.get("scope")
    scope_map = scope if isinstance(scope, dict) else {}

    repo_root_text = str(scope_map.get("repo_root", "")).strip()
    if not repo_root_text and config:
        repo_root_text = str(config.workspace_root)

    return {
        "repo_root": repo_root_text or "N/A",
        "allowed_read_prefixes": _string_list(
            scope_map.get("allowed_read_prefixes"), DEFAULT_SCOPE_ALLOWED_READ_PREFIXES
        ),
        "deny_read_prefixes": _string_list(
            scope_map.get("deny_read_prefixes"), DEFAULT_SCOPE_DENY_READ_PREFIXES
        ),
        "deny_read_globs": _string_list(
            scope_map.get("deny_read_globs"), DEFAULT_SCOPE_DENY_READ_GLOBS
        ),
        "must_read_first": _string_list(
            scope_map.get("must_read_first"), DEFAULT_SCOPE_MUST_READ_FIRST
        ),
    }


def _self_repair_prompt_body(
    *,
    current_run: Dict[str, Any],
    previous_run: Optional[Dict[str, Any]],
    latest_run: Dict[str, Any],
    report_latest_rel: str,
    run_report_rel: str,
    report_latest_text: str,
    run_report_text: str,
    must_read_first: List[str],
    max_iters: int,
    must_report_each_iter: bool,
    required_fields: List[str],
    scope_line: str,
    decision_policy: Dict[str, Any],
) -> str:
    ask, focus = _derive_ecp1_ask_focus(
        current_run=current_run,
        latest_run=latest_run,
        report_latest_text=report_latest_text,
        decision_policy=decision_policy,
    )
    one_fix, one_fix_why = _apply_decision_policy(
        base_decision=_derive_one_fix(ask, focus, current_run),
        ask=ask,
        current_run=current_run,
        latest_run=latest_run,
        decision_policy=decision_policy,
    )
    run_id = str(latest_run.get("run_id", current_run.get("run_id", "-")))
    report_status = str(latest_run.get("report_status", "-"))
    run_status = str(latest_run.get("status", current_run.get("status", "-")))

    fields = required_fields if required_fields else [
        "hypothesis_one_cause",
        "one_fix",
        "files_changed",
        "verify_commands",
        "exit_codes",
        "stdout_stderr_tail",
        "evidence_paths",
        "decision",
    ]

    lines: List[str] = []
    verify_commands = _event_specific_verify_commands(
        current_run=current_run,
        latest_run=latest_run,
    )
    lines.append("## Anti-Lost Must Read First")
    for index, path_text in enumerate(must_read_first, start=1):
        lines.append(f"{index}) `{path_text}`")
    lines.append("")
    lines.append("## ECP-1 Situation")
    lines.append(f"- run_id: `{run_id}`")
    lines.append(f"- run_status: `{run_status}`")
    lines.append(f"- report_status: `{report_status}`")
    lines.append(f"- current summary: {current_run.get('summary', '-')}")
    if previous_run:
        lines.append(
            "- previous run: "
            f"`{previous_run.get('run_id', '-')}` ({previous_run.get('status', '-')}) "
            f"- {previous_run.get('summary', '-')}"
        )
    lines.append(f"- ASK: {ask or 'No action needed.'}")
    if focus:
        lines.append(f"- FOCUS: {focus}")
    lines.append("")
    lines.append("## ECP-2 Decision")
    lines.append(f"- ONE FIX: {one_fix}")
    lines.append(f"- WHY: {one_fix_why}")
    lines.append("")
    lines.append("## ECP-3 Constraints")
    lines.append("- SSOT first: `rules/SSOT_AI_Orchestrator_Loop.md`")
    lines.append(f"- scope: {scope_line}")
    lines.append("- allowed files: `tools/orchestrator/**`, `tools/orchestrator_runtime/**`, `rules/**`, `Makefile`, `GNUmakefile`, `config*.yaml`")
    lines.append(f"- MAX_ITERS={max_iters}")
    lines.append(f"- must_report_each_iter={str(bool(must_report_each_iter)).lower()}")
    lines.append("- required_report_fields:")
    for field_name in fields:
        lines.append(f"- {field_name}")
    lines.append("")
    lines.append("## ECP-4 Codex Prompt")
    lines.append(f"MAX_ITERS={max_iters}")
    lines.append("For i in 1..MAX_ITERS:")
    lines.append("1) OBSERVE: read the three must-read-first files.")
    lines.append("2) PLAN: define exactly one cause.")
    lines.append("3) PATCH: apply one minimal fix only.")
    lines.append("4) VERIFY: run deterministic checks and capture outputs.")
    lines.append("5) REPORT: include hypothesis, one_fix, files_changed, verify_commands, exit_codes, stdout_stderr_tail, evidence_paths, decision.")
    lines.append("6) DECIDE: stop on success; otherwise iterate until MAX_ITERS.")
    lines.append("")
    lines.append("## VERIFY")
    for command in verify_commands:
        lines.append(f"- `{command}`")
    lines.append("- Confirm this prompt still includes MAX_ITERS/must_report_each_iter/required_report_fields/must-read-first.")
    lines.append("")
    return "\n".join(lines)


def generate_next_prompt(
    current_run: Dict[str, Any],
    previous_run: Optional[Dict[str, Any]] = None,
    config: Optional[OrchestratorConfig] = None,
) -> Tuple[str, bool]:
    """next_prompt.md 本文を生成する。blocked のときは (blocked用本文, True)。"""
    status = str(current_run.get("status", "unknown")).lower()
    failed = status == "failed"
    blocked = status == "blocked"

    ssot_path = _resolve_ssot_path(config)
    scope_line = _scope_line(current_run)
    loaded = _load_ssot_key_rules(ssot_path) if ssot_path else None
    if loaded is None:
        blocked_lines = [
            "ASSISTANT.md rules apply",
            "",
            "SSOT CHECK",
            "",
            "## SSOT CHECK（必須）",
            f"- ssot_path: `{ssot_path}`",
            "- key_rules:",
            "- SSOT 読み込み失敗のため抽出できませんでした。",
            f"- scope: {scope_line}",
            "",
            "## BLOCKED",
            "- status: blocked",
            "- reason: SSOT file could not be read or parsed.",
            "- 解除手順: `config.yaml` の `ssot_path` を正しいファイルに設定し、Webhook を再送して再生成する。",
        ]
        return ("\n".join(blocked_lines), True)

    latest_run = _read_json(config.latest_run_path) if config else None
    if latest_run is None:
        latest_run = current_run
    latest_policy = latest_run.get("policy")
    latest_policy_map = latest_policy if isinstance(latest_policy, dict) else {}
    repo_policy = _load_policy_snapshot(config)
    if repo_policy:
        latest_policy_map = _deep_merge_dict(latest_policy_map, repo_policy)
    latest_run["policy"] = latest_policy_map

    scope_policy = _scope_policy_from_latest(latest_run, config)
    must_read_first_raw = latest_policy_map.get("must_read_first")
    if not isinstance(must_read_first_raw, list):
        must_read_first_raw = scope_policy.get("must_read_first")
    must_read_first = (
        [str(item).strip() for item in must_read_first_raw if str(item).strip()]
        if isinstance(must_read_first_raw, list)
        else list(DEFAULT_SCOPE_MUST_READ_FIRST)
    )
    if not must_read_first:
        must_read_first = list(DEFAULT_SCOPE_MUST_READ_FIRST)

    ssot_check_map = (
        latest_policy_map.get("ssot_check")
        if isinstance(latest_policy_map.get("ssot_check"), dict)
        else {}
    )
    command_guard_map = (
        latest_policy_map.get("command_guard")
        if isinstance(latest_policy_map.get("command_guard"), dict)
        else {}
    )
    noise_control_map = (
        latest_policy_map.get("noise_control")
        if isinstance(latest_policy_map.get("noise_control"), dict)
        else {}
    )
    path_normalization_map = (
        latest_policy_map.get("path_normalization")
        if isinstance(latest_policy_map.get("path_normalization"), dict)
        else {}
    )
    enforcement_map = (
        latest_policy_map.get("enforcement")
        if isinstance(latest_policy_map.get("enforcement"), dict)
        else {}
    )
    decision_policy_map = (
        latest_policy_map.get("decision_policy")
        if isinstance(latest_policy_map.get("decision_policy"), dict)
        else dict(DEFAULT_DECISION_POLICY)
    )

    paths = latest_run.get("paths")
    paths_map = paths if isinstance(paths, dict) else {}
    report_latest_rel = str(paths_map.get("report_latest", "tools/orchestrator_runtime/reports/REPORT_LATEST.md")).strip()
    run_report_rel = str(paths_map.get("run_report", "")).strip()
    if not run_report_rel:
        run_id = str(latest_run.get("run_id", current_run.get("run_id", ""))).strip()
        run_report_rel = f"tools/orchestrator_runtime/reports/{run_id}.md" if run_id else "tools/orchestrator_runtime/reports/<run_id>.md"

    report_latest_path = _resolve_path_from_workspace(report_latest_rel, config)
    run_report_path = _resolve_path_from_workspace(run_report_rel, config)
    report_latest_text = _read_text(report_latest_path) if report_latest_path else ""
    run_report_text = _read_text(run_report_path) if run_report_path else ""

    policy = latest_run.get("policy")
    policy_map = policy if isinstance(policy, dict) else {}
    self_repair = policy_map.get("self_repair_loop")
    self_repair_map = self_repair if isinstance(self_repair, dict) else {}
    self_repair_enabled = _as_bool(self_repair_map.get("enabled"))

    if self_repair_enabled:
        max_iters_raw = self_repair_map.get("max_iters", 3)
        try:
            max_iters = int(max_iters_raw)
        except (TypeError, ValueError):
            max_iters = 3
        if max_iters < 1:
            max_iters = 1

        must_report_each_iter = _as_bool(self_repair_map.get("must_report_each_iter"))
        required_fields_raw = self_repair_map.get("report_fields_required")
        required_fields = (
            [str(item).strip() for item in required_fields_raw if str(item).strip()]
            if isinstance(required_fields_raw, list)
            else []
        )
        body = _self_repair_prompt_body(
            current_run=current_run,
            previous_run=previous_run,
            latest_run=latest_run,
            report_latest_rel=report_latest_rel,
            run_report_rel=run_report_rel,
            report_latest_text=report_latest_text,
            run_report_text=run_report_text,
            must_read_first=must_read_first,
            max_iters=max_iters,
            must_report_each_iter=must_report_each_iter,
            required_fields=required_fields,
            scope_line=scope_line,
            decision_policy=decision_policy_map,
        )
    else:
        lines: List[str] = []
        lines.append("## DONE")
        lines.append(f"- Current run: `{current_run.get('run_id', '-')}`")
        lines.append(f"- Event: `{current_run.get('event_id', '-')}` from `{current_run.get('source', 'cursor')}`")
        lines.append(f"- Intent/Status: `{current_run.get('intent', '-')}` / `{current_run.get('status', '-')}`")
        lines.append(f"- Summary: {current_run.get('summary', '-')}")
        if previous_run:
            lines.append(
                "- Previous run: "
                f"`{previous_run.get('run_id', '-')}` "
                f"({previous_run.get('status', '-')}) "
                f"- {previous_run.get('summary', '-')}"
            )
        lines.append("")

        lines.append("## NEXT")
        if failed:
            lines.append("- Reproduce the failure from the newest evidence first.")
            lines.append("- Narrow to one root cause before writing any fix.")
            lines.append("- Apply one focused patch and avoid large refactors.")
        elif blocked:
            lines.append("- Identify the exact blocker and required input.")
            lines.append("- Prepare a minimal unblock step and retry the flow.")
            lines.append("- Keep changes local to the current task scope.")
        else:
            lines.append("- Continue from the completed step with minimal scope.")
            lines.append("- Keep audit artifacts updated for the next webhook.")
            lines.append("- Prefer deterministic commands for reproducible runs.")
        lines.append("")

        lines.append("## FAIL")
        if failed:
            top_errors = current_run.get("top_errors") or []
            if not isinstance(top_errors, list) or not top_errors:
                lines.append("- Failure detected, but no explicit error message was captured.")
            else:
                for error in top_errors[:5]:
                    lines.append(f"- {error}")
        else:
            lines.append("- No failure in this run.")
        lines.append("")

        lines.append("## FIX")
        lines.append("- Keep the fix as a minimal diff.")
        lines.append("- Do not change SSOT docs in v1 flow.")
        lines.append("- Use one-cause-one-fix and keep unrelated code untouched.")
        lines.append("")

        lines.append("## VERIFY")
        lines.append("- Candidate checks: `make smoke`, `make probe`, `make verify`")
        lines.append("- API check: `curl -X GET http://127.0.0.1:8765/health`")
        lines.append("- Webhook check: resend one payload and confirm latest artifacts update.")
        lines.append("")

        body = "\n".join(lines)

    ssot_lines = [
        "ASSISTANT.md rules apply",
        "",
        "SSOT CHECK",
        "",
        "## SSOT CHECK（必須）",
        f"- ssot_path: `{ssot_path}`",
        "- key_rules:",
    ]
    for rule in loaded[:MAX_KEY_RULES]:
        ssot_lines.append(f"- {rule}")
    ssot_lines.append(f"- scope: {scope_line}")

    allowed_read_prefixes = scope_policy.get("allowed_read_prefixes")
    deny_read_prefixes = scope_policy.get("deny_read_prefixes")
    deny_read_globs = scope_policy.get("deny_read_globs")
    must_read_first = scope_policy.get("must_read_first")

    ssot_lines.extend(["", "## HARD SCOPE"])
    ssot_lines.append(f"- repo_root: `{scope_policy.get('repo_root', 'N/A')}`")
    ssot_lines.append("- allowed_read_prefixes:")
    for item in (
        allowed_read_prefixes if isinstance(allowed_read_prefixes, list) else DEFAULT_SCOPE_ALLOWED_READ_PREFIXES
    ):
        ssot_lines.append(f"- {item}")
    ssot_lines.append("- deny_read_prefixes:")
    for item in (
        deny_read_prefixes if isinstance(deny_read_prefixes, list) else DEFAULT_SCOPE_DENY_READ_PREFIXES
    ):
        ssot_lines.append(f"- {item}")
    ssot_lines.append("- deny_read_globs:")
    for item in (
        deny_read_globs if isinstance(deny_read_globs, list) else DEFAULT_SCOPE_DENY_READ_GLOBS
    ):
        ssot_lines.append(f"- {item}")
    ssot_lines.append("- must_read_first:")
    for item in must_read_first if isinstance(must_read_first, list) else DEFAULT_SCOPE_MUST_READ_FIRST:
        ssot_lines.append(f"- {item}")
    ssot_lines.append("- ssot_check:")
    ssot_lines.append(
        f"- enabled={str(bool(ssot_check_map.get('enabled', True))).lower()} "
        f"ssot_path={ssot_check_map.get('ssot_path', 'rules/SSOT_AI_Orchestrator_Loop.md')} "
        f"allow_additional_ssot_files={str(bool(ssot_check_map.get('allow_additional_ssot_files', False))).lower()}"
    )
    command_guard_allowed = _string_list(
        command_guard_map.get("allowed_commands"), DEFAULT_COMMAND_GUARD_ALLOWED_COMMANDS
    )
    ssot_lines.append("- command_guard:")
    ssot_lines.append(
        f"- enabled={str(bool(command_guard_map.get('enabled', True))).lower()} "
        f"read_targets_must_match_scope={str(bool(command_guard_map.get('read_targets_must_match_scope', True))).lower()} "
        f"on_violation={command_guard_map.get('on_violation', 'abort')}"
    )
    ssot_lines.append("- allowed_commands:")
    for item in command_guard_allowed:
        ssot_lines.append(f"- {item}")
    ssot_lines.append(
        "- violation_message: "
        f"{command_guard_map.get('violation_message', 'COMMAND_GUARD: target path violates policy.scope (denylist or outside allowed prefixes).')}"
    )
    ssot_lines.append("- path_normalization:")
    ssot_lines.append(
        f"- enabled={str(bool(path_normalization_map.get('enabled', True))).lower()} "
        f"normalize_slashes={str(bool(path_normalization_map.get('normalize_slashes', True))).lower()} "
        f"lowercase_for_matching={str(bool(path_normalization_map.get('lowercase_for_matching', True))).lower()}"
    )
    path_norm_fields = _string_list(
        path_normalization_map.get("record_fields"), ["raw_path", "normalized_path"]
    )
    ssot_lines.append("- path_normalization.record_fields:")
    for item in path_norm_fields:
        ssot_lines.append(f"- {item}")
    ssot_lines.append("- enforcement:")
    ssot_lines.append(
        f"- abort_on_scope_violation={str(bool(enforcement_map.get('abort_on_scope_violation', True))).lower()} "
        f"abort_prompt_generation_on_scope_violation={str(bool(enforcement_map.get('abort_prompt_generation_on_scope_violation', True))).lower()} "
        f"record_in_report={str(bool(enforcement_map.get('record_in_report', True))).lower()}"
    )
    ssot_lines.append("- noise_control:")
    ssot_lines.append(
        f"- enabled={str(bool(noise_control_map.get('enabled', True))).lower()} "
        f"stderr_on_scope_violation={noise_control_map.get('stderr_on_scope_violation', 'suppress')}"
    )
    report_scope_targets = _string_list(
        noise_control_map.get("report_scope_violation_in"),
        ["REPORT_LATEST.md", "runs/<run_id>.json"],
    )
    ssot_lines.append("- report_scope_violation_in:")
    for item in report_scope_targets:
        ssot_lines.append(f"- {item}")
    ssot_lines.append("- decision_policy:")
    ssot_lines.append(
        f"- enabled={str(bool(decision_policy_map.get('enabled', True))).lower()} "
        f"default_decision={decision_policy_map.get('default_decision', DEFAULT_DECISION_POLICY['default_decision'])}"
    )
    priorities = _string_list(
        decision_policy_map.get("priorities"),
        DEFAULT_DECISION_POLICY["priorities"],
    )
    ssot_lines.append("- decision_policy.priorities:")
    for item in priorities:
        ssot_lines.append(f"- {item}")

    scope_violation = current_run.get("scope_violation")
    if not isinstance(scope_violation, dict):
        latest_scope_violation = latest_run.get("scope_violation")
        scope_violation = latest_scope_violation if isinstance(latest_scope_violation, dict) else None
    if isinstance(scope_violation, dict):
        ssot_lines.extend(["", "## SCOPE VIOLATION"])
        if scope_violation.get("raw_path") is not None:
            ssot_lines.append(f"- raw_path: `{scope_violation.get('raw_path', 'N/A')}`")
        if scope_violation.get("normalized_path") is not None:
            ssot_lines.append(
                f"- normalized_path: `{scope_violation.get('normalized_path', 'N/A')}`"
            )
        ssot_lines.append(f"- violated_path: `{scope_violation.get('violated_path', 'N/A')}`")
        ssot_lines.append(f"- matched_rule: `{scope_violation.get('matched_rule', 'N/A')}`")
        ssot_lines.append(f"- blocked_action: `{scope_violation.get('blocked_action', 'N/A')}`")
        ssot_lines.append(
            f"- next_allowed_actions: `{scope_violation.get('next_allowed_actions', 'N/A')}`"
        )

    ssot_lines.extend(["", body])
    return ("\n".join(ssot_lines), False)
