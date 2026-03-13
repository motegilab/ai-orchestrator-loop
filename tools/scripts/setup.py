#!/usr/bin/env python
"""
setup.py — cross-platform 'make setup'
- Creates runtime directories
- Updates SSOT.md hash (idempotent)
- Checks that runtime/ is in .gitignore (without duplicating)
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
RUNTIME_DIR = REPO_ROOT / "runtime"
GITIGNORE = REPO_ROOT / ".gitignore"
SSOT_GATE = REPO_ROOT / ".claude" / "hooks" / "ssot_gate.py"

errors = []

# 1. Check required tools
print("[setup] ツール確認...")
for tool in ["python", "claude"]:
    result = subprocess.run(
        [tool, "--version"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        version = (result.stdout or result.stderr).strip().splitlines()[0]
        print(f"  OK  {tool}: {version}")
    else:
        errors.append(f"{tool} が見つかりません")
        print(f"  NG  {tool}: not found")

# 2. Create runtime directories
print("\n[setup] runtime/ ディレクトリを作成...")
for d in [
    RUNTIME_DIR / "runs",
    RUNTIME_DIR / "reports",
    RUNTIME_DIR / "logs",
    RUNTIME_DIR / "artifacts" / "audits",
    RUNTIME_DIR / "artifacts" / "diffs",
]:
    d.mkdir(parents=True, exist_ok=True)
    print(f"  OK  {d.relative_to(REPO_ROOT)}")

# 3. Ensure runtime/** is in .gitignore (idempotent — no duplicates)
print("\n[setup] .gitignore を確認...")
if GITIGNORE.exists():
    content = GITIGNORE.read_text(encoding="utf-8")
    if "runtime/" in content or "runtime/**" in content:
        print("  OK  runtime/ は既に .gitignore に含まれています")
    else:
        with open(GITIGNORE, "a", encoding="utf-8") as f:
            f.write("\nruntime/\n")
        print("  OK  runtime/ を .gitignore に追加しました")
else:
    errors.append(".gitignore が見つかりません")
    print("  NG  .gitignore not found")

# 4. Update SSOT hash
print("\n[setup] SSOT.md のハッシュを更新...")
if SSOT_GATE.exists():
    result = subprocess.run(
        [sys.executable, str(SSOT_GATE), "--update-hash"],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  OK  {result.stdout.strip()}")
    else:
        errors.append(f"hash update 失敗: {result.stderr.strip()}")
        print(f"  NG  {result.stderr.strip()}")
else:
    errors.append("ssot_gate.py が見つかりません")
    print("  NG  .claude/hooks/ssot_gate.py not found")

# Summary
print()
if errors:
    print("[setup] エラーがあります:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("[setup] 完了！  make loop-start でループを開始できます")
