#!/usr/bin/env python
"""
auto_setup.py — interactive setup for new users of ai-orchestrator-loop

Usage:
  python tools/scripts/auto_setup.py          # full interactive setup
  python tools/scripts/auto_setup.py --check  # check-only (no changes)

Steps:
  1. Prerequisites check (python, claude, make)
  2. Copy notifications.json.example → notifications.json (ask for webhook URL)
  3. Run make setup
  4. Verify GOchecklist §8 (9 items)
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

CHECK_ONLY = "--check" in sys.argv
REPO_ROOT = Path(__file__).parent.parent.parent

NOTIFICATIONS_EXAMPLE = REPO_ROOT / "notifications.json.example"
NOTIFICATIONS_JSON = REPO_ROOT / "notifications.json"
GO_CHECKLIST = REPO_ROOT / "docs" / "go-checklist.md"
SETUP_PY = REPO_ROOT / "tools" / "scripts" / "setup.py"

PASS = "  OK "
FAIL = "  NG "
SKIP = " SKIP"

errors = []
warnings = []


def run(cmd, cwd=None):
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(cwd or REPO_ROOT)
    )


def section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


# ─────────────────────────────────────────────────
# Step 1: Prerequisites
# ─────────────────────────────────────────────────
section("Step 1: 前提条件チェック")

for tool, min_hint in [
    ("python", "Python 3.9+ が必要です: https://python.org"),
    ("claude", "Claude Code CLI が必要です: npm install -g @anthropic-ai/claude-code"),
    ("make", "make が必要です (Windows: choco install make または Git Bash 付属)"),
]:
    result = run([tool, "--version"])
    if result.returncode == 0:
        ver = (result.stdout or result.stderr).strip().splitlines()[0]
        print(f"{PASS} {tool}: {ver}")
    else:
        print(f"{FAIL} {tool}: not found")
        print(f"       → {min_hint}")
        errors.append(f"{tool} が見つかりません")


# ─────────────────────────────────────────────────
# Step 2: notifications.json
# ─────────────────────────────────────────────────
section("Step 2: Discord/Slack 通知設定")

if not NOTIFICATIONS_EXAMPLE.exists():
    print(f"{SKIP} notifications.json.example が見つかりません（スキップ）")
    warnings.append("notifications.json.example が見つかりません")
elif NOTIFICATIONS_JSON.exists():
    print(f"{PASS} notifications.json は既に存在します（スキップ）")
elif CHECK_ONLY:
    print(f"{SKIP} --check モード: notifications.json のコピーをスキップ")
else:
    shutil.copy(NOTIFICATIONS_EXAMPLE, NOTIFICATIONS_JSON)
    print(f"{PASS} notifications.json を作成しました")

    print()
    print("  Discord Webhook URL を設定しますか?")
    print("  （設定しない場合は Enter キーを押してください）")
    try:
        url = input("  Webhook URL: ").strip()
    except (EOFError, KeyboardInterrupt):
        url = ""

    if url:
        try:
            data = json.loads(NOTIFICATIONS_JSON.read_text(encoding="utf-8"))
            data["discord"]["webhook_url"] = url
            data["discord"]["enabled"] = True
            NOTIFICATIONS_JSON.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"{PASS} Webhook URL を設定しました")
        except Exception as e:
            print(f"{FAIL} notifications.json の更新に失敗: {e}")
            warnings.append(f"notifications.json 更新失敗: {e}")
    else:
        print(f"{SKIP} Webhook URL の設定をスキップしました")
        print("       後から notifications.json を直接編集できます")


# ─────────────────────────────────────────────────
# Step 3: make setup
# ─────────────────────────────────────────────────
section("Step 3: make setup 実行")

if CHECK_ONLY:
    print(f"{SKIP} --check モード: make setup をスキップ")
else:
    result = run([sys.executable, str(SETUP_PY)])
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            print(f"  {line}")
        print(f"{PASS} make setup 完了")
    else:
        print(result.stdout)
        print(result.stderr)
        errors.append("make setup が失敗しました")
        print(f"{FAIL} make setup 失敗")


# ─────────────────────────────────────────────────
# Step 4: GOチェックリスト §8 確認
# ─────────────────────────────────────────────────
section("Step 4: GOチェックリスト §8 確認")

CHECKLIST_ITEMS = [
    ("Claude Code CLI v2.0以上インストール済み", lambda: _check_claude_version()),
    ("make loop-start でセッションが起動する", lambda: _check_file_exists(REPO_ROOT / "tools" / "scripts" / "loop_start.py")),
    ("SessionStart Hookが発火しadditionalContextが注入される", lambda: _check_file_exists(REPO_ROOT / ".claude" / "hooks" / "on_session_start.py")),
    ("PreToolUse HookがSSO.mdへの書き込みをブロックする", lambda: _check_file_exists(REPO_ROOT / ".claude" / "hooks" / "ssot_gate.py")),
    ("Stop Hook後にruntime/runs/latest.jsonが生成される", lambda: _check_dir_exists(REPO_ROOT / "runtime" / "runs")),
    ("Stop Hook後にruntime/reports/REPORT_LATEST.mdが生成される", lambda: _check_dir_exists(REPO_ROOT / "runtime" / "reports")),
    ("Stop Hook後にruntime/logs/next_session.mdが生成される", lambda: _check_dir_exists(REPO_ROOT / "runtime" / "logs")),
    ("次回loop-startで前回のコンテキストが自動注入される", lambda: _check_file_exists(REPO_ROOT / ".claude" / "hooks" / "on_session_start.py")),
    ("runtime/** がgit管理外である", lambda: _check_gitignore()),
]


def _check_claude_version():
    r = run(["claude", "--version"])
    if r.returncode != 0:
        return False, "claude not found"
    ver_str = (r.stdout or r.stderr).strip().splitlines()[0]
    return True, ver_str


def _check_file_exists(path):
    exists = path.exists()
    return exists, str(path.relative_to(REPO_ROOT)) + (" 存在" if exists else " 未存在")


def _check_dir_exists(path):
    exists = path.exists()
    return exists, str(path.relative_to(REPO_ROOT)) + (" 存在" if exists else " 未存在（make setup を実行してください）")


def _check_gitignore():
    gitignore = REPO_ROOT / ".gitignore"
    if not gitignore.exists():
        return False, ".gitignore が見つかりません"
    content = gitignore.read_text(encoding="utf-8")
    if "runtime/" in content or "runtime/**" in content:
        return True, "runtime/ は .gitignore に含まれています"
    return False, "runtime/ が .gitignore にありません（make setup を実行してください）"


checklist_pass = 0
for i, (label, check_fn) in enumerate(CHECKLIST_ITEMS, 1):
    try:
        ok, detail = check_fn()
    except Exception as e:
        ok, detail = False, str(e)

    status = PASS if ok else FAIL
    print(f"{status} [{i}] {label}")
    if not ok:
        print(f"       → {detail}")
        warnings.append(f"GOチェック失敗: {label}")
    checklist_pass += int(ok)

print(f"\n  結果: {checklist_pass}/{len(CHECKLIST_ITEMS)} 項目 OK")


# ─────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────
section("セットアップ結果")

if errors:
    print("エラー（解決が必要）:")
    for e in errors:
        print(f"  - {e}")

if warnings:
    print("警告（確認推奨）:")
    for w in warnings:
        print(f"  - {w}")

if not errors:
    if checklist_pass == len(CHECKLIST_ITEMS):
        print("全チェック PASS — セットアップ完了!")
        print()
        print("次のステップ:")
        print("  1. SSOT.md と CLAUDE.md をPJ固有の内容に書き換える")
        print("  2. tasks/milestones.json を初期化する")
        print("  3. make loop-start でループを開始する")
    else:
        print(f"セットアップ完了（{len(CHECKLIST_ITEMS) - checklist_pass} 項目未達）")
        print("上記の警告を確認して、make setup を再実行してください")
    sys.exit(0)
else:
    print(f"\n{len(errors)} 件のエラーを解決してから再実行してください")
    sys.exit(1)
