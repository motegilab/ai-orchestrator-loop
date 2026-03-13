#!/usr/bin/env python
"""
loop_start.py — cross-platform entry point for 'make loop-start'
Works on Windows (cmd/PowerShell/Git Bash) and macOS/Linux.

Usage:
  python tools/scripts/loop_start.py          # same window (default)
  python tools/scripts/loop_start.py --detach # new terminal window (Windows)
"""
import os
import subprocess
import sys
from pathlib import Path

DETACH = "--detach" in sys.argv

REPO_ROOT = Path(__file__).parent.parent.parent
RUNTIME_DIR = REPO_ROOT / "runtime"
NEXT_SESSION = RUNTIME_DIR / "logs" / "next_session.md"
FIRST_PROMPT = REPO_ROOT / "docs" / "FIRST_PROMPT.md"

# Ensure runtime directories exist
for d in [
    RUNTIME_DIR / "runs",
    RUNTIME_DIR / "reports",
    RUNTIME_DIR / "logs",
    RUNTIME_DIR / "artifacts" / "audits",
    RUNTIME_DIR / "artifacts" / "diffs",
]:
    d.mkdir(parents=True, exist_ok=True)

# Pick the prompt
if NEXT_SESSION.exists():
    print("[loop-start] 前回のセッションコンテキストを読み込み中...")
    prompt = NEXT_SESSION.read_text(encoding="utf-8")
elif FIRST_PROMPT.exists():
    print("[loop-start] 初回起動 — FIRST_PROMPT.md を使用します")
    prompt = FIRST_PROMPT.read_text(encoding="utf-8")
else:
    prompt = (
        "SSOT.md と CLAUDE.md を読んで、"
        "tasks/milestones.json の次のタスクを実行してください。"
    )

# Build claude command
# --add-dir: share global skills if ~/.claude/skills exists
home_skills = Path.home() / ".claude" / "skills"
cmd = ["claude"]
if home_skills.exists():
    cmd += ["--add-dir", str(home_skills)]
cmd += [
    "--allowedTools", "Read,Write,Edit,MultiEdit,Bash,Task",
    "-p", prompt,
]

print("[loop-start] claude CLI を起動します...")

if DETACH and sys.platform == "win32":
    # Windows: open a new terminal window
    # Use Windows Terminal if available, fall back to cmd.exe
    wt = subprocess.run(["where", "wt"], capture_output=True)
    if wt.returncode == 0:
        # Windows Terminal
        subprocess.Popen(
            ["wt", "--", "cmd", "/k"] + cmd,
            cwd=str(REPO_ROOT),
            creationflags=0x00000010,  # CREATE_NEW_CONSOLE
        )
    else:
        # Fallback: cmd.exe in new window
        subprocess.Popen(
            ["cmd", "/k"] + cmd,
            cwd=str(REPO_ROOT),
            creationflags=0x00000010,  # CREATE_NEW_CONSOLE
        )
    print("[loop-start] 新しいウィンドウでセッションを開始しました。")
    sys.exit(0)
else:
    # Same window (default — required for Hook stdin/stdout to work correctly)
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    sys.exit(result.returncode)
