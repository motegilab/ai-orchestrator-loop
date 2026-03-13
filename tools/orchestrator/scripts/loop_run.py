#!/usr/bin/env python
"""
loop_run.py — orch-run-next-local の対話式ループ実行

Usage:
  python tools/orchestrator/scripts/loop_run.py
  python tools/orchestrator/scripts/loop_run.py 3
  python tools/orchestrator/scripts/loop_run.py --dry-run
  python tools/orchestrator/scripts/loop_run.py --skip-check
  python tools/orchestrator/scripts/loop_run.py --yes
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LATEST_JSON = REPO_ROOT / "tools" / "orchestrator_runtime" / "runs" / "latest.json"
REPORT_LATEST = REPO_ROOT / "tools" / "orchestrator_runtime" / "reports" / "REPORT_LATEST.md"
DEFAULT_MAX_LOOPS = 999
DEFAULT_MAX_CONSECUTIVE_BLOCKED = 2


def print_status(message: str) -> None:
    print(f"[loop-run] {message}", flush=True)


def ask(prompt: str, default: str = "") -> str:
    try:
        answer = input(prompt)
        trimmed = answer.strip()
        return trimmed if trimmed else default
    except EOFError:
        return default


def read_latest_json() -> dict[str, object]:
    if not LATEST_JSON.exists():
        return {}
    try:
        payload = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def latest_ask_is_no_action() -> bool:
    if not REPORT_LATEST.exists():
        return False
    try:
        text = REPORT_LATEST.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    return "ASK: No action needed." in text


def run_cmd(command: list[str]) -> int:
    print_status(f"実行: {' '.join(command)}")
    completed = subprocess.run(command, cwd=str(REPO_ROOT))
    return int(completed.returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive loop runner for orch-run-next-local.")
    parser.add_argument("max_loops", nargs="?", type=int, help="最大ループ回数")
    parser.add_argument("--dry-run", action="store_true", help="実行せず計画だけ表示")
    parser.add_argument("--skip-check", action="store_true", help="事前SSOTチェックをスキップ")
    parser.add_argument("--yes", action="store_true", help="確認プロンプトを自動yes")
    parser.add_argument(
        "--max-consecutive-blocked",
        type=int,
        default=DEFAULT_MAX_CONSECUTIVE_BLOCKED,
        help=f"連続blockedで停止する閾値 (default: {DEFAULT_MAX_CONSECUTIVE_BLOCKED})",
    )
    return parser.parse_args()


def resolve_interactive_settings(args: argparse.Namespace) -> tuple[int, bool]:
    interactive = args.max_loops is None and not args.dry_run and not args.yes
    skip_check = bool(args.skip_check)
    max_loops = int(args.max_loops) if args.max_loops is not None else DEFAULT_MAX_LOOPS

    if not interactive:
        return max_loops, skip_check

    print("=" * 48)
    print("  loop-run セットアップ")
    print("=" * 48)

    ans_check = ask("SSOT チェックをやりますか? [Y/n]: ", default="y")
    skip_check = ans_check.lower() == "n"

    ans_loops = ask("ループ回数は最大何回にしますか? (Enter = 無制限): ", default="")
    if ans_loops.isdigit():
        max_loops = int(ans_loops)
    else:
        max_loops = DEFAULT_MAX_LOOPS

    print()
    return max_loops, skip_check


def ensure_precheck(skip_check: bool, yes_all: bool) -> int:
    if skip_check:
        print_status("SSOT チェックをスキップします。")
        return 0

    print_status("事前チェック: make orch-report")
    rc = run_cmd(["make", "orch-report"])
    if rc == 0:
        return 0

    if yes_all:
        print_status("事前チェック失敗だが --yes のため続行します。")
        return 0

    cont = ask("[loop-run] 事前チェックが失敗しました。続行しますか? [y/N]: ", default="n")
    if cont.lower() == "y":
        return 0
    print_status("中断しました。")
    return rc


def summarize_latest() -> tuple[str, str, str]:
    latest = read_latest_json()
    run_id = str(latest.get("run_id", "N/A"))
    status = str(latest.get("status", "N/A"))
    report_status = str(latest.get("report_status", "N/A"))
    return run_id, status, report_status


def main() -> int:
    args = parse_args()
    max_loops, skip_check = resolve_interactive_settings(args)

    if args.dry_run:
        run_id, status, report_status = summarize_latest()
        loops_label = str(max_loops) if max_loops < DEFAULT_MAX_LOOPS else "無制限"
        print_status(
            f"開始。max_loops={loops_label}, latest_run={run_id}, status={status}, report_status={report_status}"
        )
        print_status("--dry-run モード: 実行しません。")
        return 0

    rc = ensure_precheck(skip_check=skip_check, yes_all=bool(args.yes))
    if rc != 0:
        return rc

    run_id, status, report_status = summarize_latest()
    loops_label = str(max_loops) if max_loops < DEFAULT_MAX_LOOPS else "無制限"
    print_status(
        f"開始。max_loops={loops_label}, latest_run={run_id}, status={status}, report_status={report_status}"
    )

    consecutive_blocked = 0
    for i in range(1, max_loops + 1):
        print_status(f"ループ {i}/{loops_label} 開始")

        rc = run_cmd(["make", "orch-run-next-local"])
        if rc != 0:
            print_status(f"エラー終了 (returncode={rc})。中断します。")
            return rc

        report_rc = run_cmd(["make", "orch-report"])
        if report_rc != 0:
            print_status(f"report 更新失敗 (returncode={report_rc})。中断します。")
            return report_rc

        run_id, status, report_status = summarize_latest()
        print_status(f"ループ {i} 完了 — run_id={run_id}, status={status}, report_status={report_status}")

        if status.lower() == "blocked":
            consecutive_blocked += 1
            print_status(
                f"WARNING: blocked が連続しています ({consecutive_blocked}/{args.max_consecutive_blocked})"
            )
            if consecutive_blocked >= args.max_consecutive_blocked:
                print_status("連続 blocked 検出。無限ループ防止のため停止します。")
                return 1
        else:
            consecutive_blocked = 0

        if status.lower() == "success" and latest_ask_is_no_action():
            print_status("ASK=No action needed を検出。終了します。")
            return 0

    print_status("max_loops 到達で終了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
