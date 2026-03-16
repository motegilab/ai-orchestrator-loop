#!/usr/bin/env python
"""
loop_run.py — 自動連続ループ実行スクリプト

Usage:
  python tools/scripts/loop_run.py              # 対話プロンプトで設定
  python tools/scripts/loop_run.py 3            # 最大3ループ（プロンプトなし）
  python tools/scripts/loop_run.py --dry-run    # 実行せず次タスクだけ表示
  python tools/scripts/loop_run.py --skip-check # SSOT チェックをスキップ
  python tools/scripts/loop_run.py --yes        # 全プロンプトに yes で回答（CI用）

ループは以下の条件で停止:
  - pending タスクがなくなった
  - 指定した max_loops に達した
  - on_stop.py が report_source=incomplete を連続で返した（無限ループ防止）
  - エラー終了（claude の returncode != 0）
  - チェックポイントタスクの手前に到達した
"""
import json
import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
RUNS_DIR  = REPO_ROOT / "runtime" / "runs"
LATEST    = RUNS_DIR / "latest.json"

# 連続 incomplete でのフェイルセーフ
MAX_CONSECUTIVE_INCOMPLETE = 2

# ─── 引数解析 ────────────────────────────────────────────────
args = sys.argv[1:]
DRY_RUN    = "--dry-run" in args
SKIP_CHECK = "--skip-check" in args
YES_ALL    = "--yes" in args
args = [a for a in args if not a.startswith("--")]
# 数値引数が渡されたら対話プロンプトをスキップ
_explicit_loops = int(args[0]) if args else None


def get_next_task():
    if not LATEST.exists():
        return None
    try:
        d = json.loads(LATEST.read_text(encoding="utf-8"))
        return d.get("next_task")
    except Exception:
        return None


def get_last_report_source():
    if not LATEST.exists():
        return None
    try:
        d = json.loads(LATEST.read_text(encoding="utf-8"))
        return d.get("report_source")
    except Exception:
        return None


def get_completed_milestone():
    """on_stop.py が検出したマイルストーン完了情報を返す"""
    if not LATEST.exists():
        return None
    try:
        d = json.loads(LATEST.read_text(encoding="utf-8"))
        return d.get("milestone_completed")
    except Exception:
        return None


def print_status(msg):
    print(f"[loop-run] {msg}", flush=True)


def ask(prompt, default=""):
    """入力を受け付ける。EOFError は default を返す。"""
    try:
        ans = input(prompt)
        return ans.strip() if ans.strip() else default
    except EOFError:
        return default


# ─── 対話プロンプト ──────────────────────────────────────────
# 引数なし・--dry-run なし・--yes なし のときだけ表示
INTERACTIVE = (_explicit_loops is None) and (not DRY_RUN) and (not YES_ALL)

if INTERACTIVE:
    print("=" * 48)
    print("  loop-run セットアップ")
    print("=" * 48)

    # 1. SSOT チェック
    ans_check = ask("SSOT チェックをやりますか? [Y/n]: ", default="y")
    SKIP_CHECK = ans_check.lower() == "n"

    # 2. ループ回数
    ans_loops = ask("ループ回数は最大何回にしますか? (Enter = 無制限): ", default="")
    if ans_loops.isdigit():
        max_loops = int(ans_loops)
    else:
        max_loops = 999

    print()

else:
    # 引数 or フラグで直接指定された場合
    max_loops = _explicit_loops if _explicit_loops is not None else 999


# ─── SSOT チェック ──────────────────────────────────────────
if not SKIP_CHECK and not DRY_RUN:
    check_result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "scripts" / "ssot_check.py")],
        cwd=str(REPO_ROOT),
    )
    if check_result.returncode == 2:
        print_status("SSOT に重大な問題があります。--skip-check で強制実行可。")
        sys.exit(1)
    elif check_result.returncode == 1:
        if YES_ALL:
            ans_warn = "y"
        else:
            ans_warn = ask("[loop-run] 警告がありますが続行しますか? [y/N]: ", default="n")
        if ans_warn.lower() != "y":
            print_status("中断しました。")
            sys.exit(0)

# ─── 事前確認 ──────────────────────────────────────────────
next_task = get_next_task()
if next_task:
    label = f"{next_task['task_id']} — {next_task['task_title'][:60]}"
else:
    label = "（次タスクなし）"

loops_label = str(max_loops) if max_loops < 999 else "無制限"
print_status(f"開始。max_loops={loops_label}, 次タスク: {label}")

if DRY_RUN:
    print_status("--dry-run モード: 実行しません")
    sys.exit(0)

if not next_task:
    print_status("pending タスクがありません。終了します。")
    sys.exit(0)

# ─── ループ実行 ─────────────────────────────────────────────
consecutive_incomplete = 0

for i in range(1, max_loops + 1):
    next_task = get_next_task()
    if not next_task:
        print_status(f"全タスク完了。{i - 1} ループ実行しました。")
        break

    # チェックポイント確認（このタスクを実行する前に確認）
    if next_task.get("checkpoint"):
        print_status(f"チェックポイント: {next_task['task_id']} — {next_task['task_title'][:50]}")
        if YES_ALL:
            print_status("--yes フラグのためチェックポイントを通過します。")
        else:
            ans_cp = ask("[loop-run] このタスクを実行しますか? [y/N]: ", default="n")
            if ans_cp.lower() != "y":
                print_status("停止しました。確認後 make loop-run で再開してください。")
                sys.exit(0)

    task_label = f"{next_task['task_id']} — {next_task['task_title'][:50]}"
    print_status(f"ループ {i}/{loops_label}: {task_label}")

    # loop_start.py を起動（Stop Hook が正しく動くよう同プロセスで実行）
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "scripts" / "loop_start.py")],
        cwd=str(REPO_ROOT),
    )

    if result.returncode != 0:
        print_status(f"エラー終了 (returncode={result.returncode})。中断します。")
        sys.exit(result.returncode)

    # 結果確認
    report_source = get_last_report_source()
    print_status(f"ループ {i} 完了 — report_source={report_source}")

    if report_source == "incomplete":
        consecutive_incomplete += 1
        print_status(f"WARNING: report Skill が実行されませんでした ({consecutive_incomplete}/{MAX_CONSECUTIVE_INCOMPLETE})")
        if consecutive_incomplete >= MAX_CONSECUTIVE_INCOMPLETE:
            print_status("連続 incomplete 検出。無限ループを防止するため中断します。")
            sys.exit(1)
    else:
        consecutive_incomplete = 0

    # マイルストーン完了チェック
    completed_ms = get_completed_milestone()
    if completed_ms:
        ms_id    = completed_ms.get("milestone_id", "?")
        ms_title = completed_ms.get("milestone_title", "?")
        ms_count = completed_ms.get("task_count", "?")
        print_status("")
        print_status("*" * 60)
        print_status("*" + " " * 58 + "*")
        print_status(f"*   🎉  MILESTONE COMPLETE: [{ms_id}]" + " " * max(0, 22 - len(ms_id)) + "*")
        print_status(f"*   {ms_title[:52]:<52}  *")
        print_status(f"*   完了タスク数: {ms_count} タスク" + " " * max(0, 43 - len(str(ms_count))) + "*")
        print_status("*" + " " * 58 + "*")
        print_status("*" * 60)
        print_status("")
        print_status(">>> 次のアクション:")
        print_status(f"    1. Claude に「マイルストーンレビューを実行して」と伝える")
        print_status(f"    2. HTMLチェックリストが生成される:")
        print_status(f"       runtime/reports/MANUAL_CHECK_{ms_id}.html")
        print_status(f"    3. ブラウザで開いて全項目を確認する")
        print_status(f"    4. 確認完了後 make loop-run で次フェーズへ")
        print_status("")
        if not YES_ALL:
            ans_ms = ask("[loop-run] レビュー生成のためにループを停止しますか? [Y/n]: ", default="y")
            if ans_ms.lower() != "n":
                print_status("停止しました。上の手順に従って進めてください。")
                sys.exit(0)

print_status("loop_run 終了。")
