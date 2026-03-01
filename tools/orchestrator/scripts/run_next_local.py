from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib import error, request


WEBHOOK_URL = "http://127.0.0.1:8765/webhook"
SSOT_CHECK_PATTERN = re.compile(r"^\ufeff?\s*(?:#+\s*)?SSOT CHECK\b", re.IGNORECASE)
SSOT_CHECK_REQUIRED_PATTERN = re.compile(r"^\s*##\s*SSOT CHECK（必須）\s*$", re.IGNORECASE)


@dataclass
class RunResult:
    status: str
    message: str
    exit_code: int
    stdout_text: str
    stderr_text: str
    extra: Dict[str, Any]


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(ts: Optional[datetime] = None) -> str:
    current = ts or utc_now()
    return current.strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_compact(ts: Optional[datetime] = None) -> str:
    current = ts or utc_now()
    return current.strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def save_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relative_to_workspace(path: Path) -> str:
    root = workspace_root().resolve()
    target = path.resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return target.as_posix()


def check_ssot_gate(prompt_text: str) -> bool:
    text = str(prompt_text or "").lstrip("\ufeff")
    if SSOT_CHECK_PATTERN.match(text):
        return True
    for line in text.splitlines()[:40]:
        if SSOT_CHECK_PATTERN.match(line) or SSOT_CHECK_REQUIRED_PATTERN.match(line):
            return True
    return False


def maybe_remove_stale_lock(lock_path: Path, lock_stale_seconds: int) -> bool:
    if not lock_path.exists():
        return False
    age = time.time() - lock_path.stat().st_mtime
    if age <= lock_stale_seconds:
        return False
    lock_path.unlink(missing_ok=True)
    return True


def acquire_lock(lock_path: Path) -> Tuple[bool, str]:
    ensure_dir(lock_path.parent)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False, "lock file exists"

    payload = {
        "pid": os.getpid(),
        "created_at": utc_iso(),
    }
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return True, "lock acquired"


def release_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


def run_codex(prompt_text: str, timeout_seconds: int) -> RunResult:
    codex = shutil.which("codex")
    if not codex:
        return RunResult(
            status="blocked",
            message="codex CLI not found",
            exit_code=2,
            stdout_text="",
            stderr_text="codex CLI not found in PATH",
            extra={"codex_invoked": False},
        )

    cmd = [codex, "exec", prompt_text, "--full-auto"]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return RunResult(
            status="failed",
            message=f"codex exec timed out after {timeout_seconds} seconds",
            exit_code=1,
            stdout_text=(exc.stdout or ""),
            stderr_text=(exc.stderr or ""),
            extra={"codex_invoked": True, "timed_out": True, "command": cmd},
        )
    except Exception as exc:  # noqa: BLE001
        return RunResult(
            status="failed",
            message=f"codex exec error: {exc}",
            exit_code=1,
            stdout_text="",
            stderr_text=str(exc),
            extra={"codex_invoked": True, "command": cmd},
        )

    status = "success" if completed.returncode == 0 else "failed"
    message = (
        "codex exec completed successfully"
        if completed.returncode == 0
        else f"codex exec failed with exit code {completed.returncode}"
    )
    return RunResult(
        status=status,
        message=message,
        exit_code=0 if completed.returncode == 0 else 1,
        stdout_text=completed.stdout,
        stderr_text=completed.stderr,
        extra={
            "codex_invoked": True,
            "command": cmd,
            "codex_exit_code": completed.returncode,
        },
    )


def post_event_with_fallback(
    *,
    post_script: Path,
    hook_name: str,
    message: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    payload_json = json.dumps(payload, ensure_ascii=False)
    post_result: Dict[str, Any] = {
        "ok": False,
        "transport": "",
        "detail": "",
    }

    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell and post_script.exists():
        cmd = [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(post_script),
            "-HookName",
            hook_name,
            "-Message",
            message,
            "-Json",
            payload_json,
        ]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode == 0:
            post_result["ok"] = True
            post_result["transport"] = "post_event.ps1"
            post_result["detail"] = completed.stdout.strip()
            return post_result
        post_result["detail"] = completed.stderr.strip() or completed.stdout.strip()

    req = request.Request(
        WEBHOOK_URL,
        data=payload_json.encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
            post_result["ok"] = response.status == 200
            post_result["transport"] = "direct_http"
            post_result["detail"] = body
            return post_result
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        post_result["transport"] = "direct_http"
        post_result["detail"] = f"http error {exc.code}: {body}"
    except Exception as exc:  # noqa: BLE001
        post_result["transport"] = "direct_http"
        post_result["detail"] = str(exc)
    return post_result


def write_summary_files(
    summary_dir: Path,
    timestamp: str,
    result: RunResult,
    post_result: Dict[str, Any],
    next_prompt_path: Path,
    lock_path: Path,
    iteration: int,
) -> Dict[str, str]:
    ensure_dir(summary_dir)
    base = summary_dir / f"{timestamp}_run_next_local_i{iteration:03d}"
    stdout_path = base.with_suffix(".stdout.log")
    stderr_path = base.with_suffix(".stderr.log")
    meta_path = base.with_suffix(".meta.json")

    save_text(stdout_path, result.stdout_text)
    save_text(stderr_path, result.stderr_text)
    save_json(
        meta_path,
        {
            "status": result.status,
            "message": result.message,
            "exit_code": result.exit_code,
            "timestamp": utc_iso(),
            "iteration": iteration,
            "next_prompt_path": relative_to_workspace(next_prompt_path),
            "lock_path": relative_to_workspace(lock_path),
            "post": post_result,
            "extra": result.extra,
        },
    )
    return {
        "stdout": relative_to_workspace(stdout_path),
        "stderr": relative_to_workspace(stderr_path),
        "meta": relative_to_workspace(meta_path),
    }


def parse_preflight_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text, "parse_error": "invalid_json"}
    if isinstance(parsed, dict):
        return parsed
    return {"raw": str(parsed), "parse_error": "unexpected_type"}


def make_payload(
    *,
    status: str,
    message: str,
    iteration: int,
    next_prompt_path: Path,
    summary_paths: Dict[str, str],
    extra: Dict[str, Any],
) -> Dict[str, Any]:
    event_id = f"orch-run-next-local-{utc_compact()}-i{iteration:03d}"
    intent = "status_update"
    if status == "success":
        intent = "task_completed"
    elif status == "failed":
        intent = "task_failed"

    payload: Dict[str, Any] = {
        "event_id": event_id,
        "source": "cursor",
        "intent": intent,
        "command": "make orch-run-next-local",
        "status": status,
        "summary": message,
        "hook_name": "orch-run-next-local",
        "timestamp": utc_iso(),
        "next_prompt_path": relative_to_workspace(next_prompt_path),
        "summary_paths": summary_paths,
        "raw": {"iteration": iteration, **extra},
    }
    return payload


def run_once(args: argparse.Namespace, iteration: int) -> RunResult:
    root = workspace_root()
    next_prompt_path = root / "tools" / "orchestrator_runtime" / "logs" / "next_prompt.md"
    lock_path = root / "tools" / "orchestrator_runtime" / "logs" / "run_next_local.lock"

    maybe_remove_stale_lock(lock_path, args.lock_stale_seconds)
    lock_ok, _ = acquire_lock(lock_path)
    if not lock_ok:
        return RunResult(
            status="blocked",
            message="run_next_local is already running (lock file exists)",
            exit_code=2,
            stdout_text="",
            stderr_text="Lock file exists. Aborting duplicate launch.",
            extra={},
        )

    try:
        if not next_prompt_path.exists():
            return RunResult(
                status="blocked",
                message="next_prompt.md not found",
                exit_code=2,
                stdout_text="",
                stderr_text=f"Missing file: {next_prompt_path}",
                extra={},
            )

        prompt_text = load_text(next_prompt_path)
        if not check_ssot_gate(prompt_text):
            return RunResult(
                status="blocked",
                message="SSOT CHECK gate failed (next_prompt.md header missing)",
                exit_code=2,
                stdout_text="",
                stderr_text="SSOT CHECK is required at the top of next_prompt.md.",
                extra={},
            )

        return run_codex(prompt_text=prompt_text, timeout_seconds=args.codex_timeout_seconds)
    finally:
        release_lock(lock_path)


def execute_once(args: argparse.Namespace, iteration: int) -> RunResult:
    root = workspace_root()
    next_prompt_path = root / "tools" / "orchestrator_runtime" / "logs" / "next_prompt.md"
    summary_dir = root / "tools" / "orchestrator_runtime" / "artifacts" / "summaries"
    lock_path = root / "tools" / "orchestrator_runtime" / "logs" / "run_next_local.lock"
    post_script = root / "tools" / "orchestrator" / "scripts" / "post_event.ps1"

    preflight_info = parse_preflight_json(args.preflight_json)
    result = run_once(args, iteration=iteration)
    if preflight_info:
        result.extra = {**result.extra, "preflight": preflight_info}
        trace = str(preflight_info.get("trace", "")).strip()
        if trace and "preflight:" not in result.message:
            result.message = f"{result.message} | preflight: {trace}"

    timestamp = utc_compact()
    summary_paths = write_summary_files(
        summary_dir,
        timestamp,
        result,
        {"ok": False, "transport": "pending", "detail": ""},
        next_prompt_path,
        lock_path,
        iteration,
    )
    payload = make_payload(
        status=result.status,
        message=result.message,
        iteration=iteration,
        next_prompt_path=next_prompt_path,
        summary_paths=summary_paths,
        extra=result.extra,
    )
    post_result = post_event_with_fallback(
        post_script=post_script,
        hook_name="run_next_local",
        message=result.message,
        payload=payload,
    )

    # refresh metadata with post result
    meta_path = root / summary_paths["meta"]
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        meta = {}
    meta["post"] = post_result
    save_json(meta_path, meta)

    if not post_result.get("ok"):
        result.stderr_text = (result.stderr_text + "\n" if result.stderr_text else "") + (
            f"POST failed: {post_result.get('detail', '')}"
        )
        result.exit_code = 1 if result.exit_code == 0 else result.exit_code

    print(
        f"[run_next_local] iteration={iteration} status={result.status} "
        f"message={result.message} post_ok={post_result.get('ok')}"
    )
    return result


def run_loop(args: argparse.Namespace) -> int:
    max_iterations = max(1, args.max_iterations)
    overall_exit = 0
    for iteration in range(1, max_iterations + 1):
        result = execute_once(args, iteration=iteration)
        if result.exit_code != 0 and overall_exit == 0:
            overall_exit = result.exit_code
        if result.status == "blocked":
            print("[run_next_local] blocked status detected, stopping loop.")
            break
        if iteration < max_iterations and args.interval_seconds > 0:
            time.sleep(args.interval_seconds)
    return overall_exit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run next_prompt locally via codex CLI.")
    parser.add_argument("--loop", action="store_true", help="Run in loop mode.")
    parser.add_argument("--max-iterations", type=int, default=3, help="Max loop iterations.")
    parser.add_argument("--interval-seconds", type=float, default=1.0, help="Sleep interval in loop.")
    parser.add_argument(
        "--codex-timeout-seconds",
        type=int,
        default=600,
        help="Timeout for one codex execution.",
    )
    parser.add_argument(
        "--lock-stale-seconds",
        type=int,
        default=7200,
        help="Treat lock as stale after this many seconds.",
    )
    parser.add_argument(
        "--preflight-json",
        default="",
        help="Optional JSON payload describing preflight health/restart checks.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.loop:
        return run_loop(args)
    result = execute_once(args, iteration=1)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
