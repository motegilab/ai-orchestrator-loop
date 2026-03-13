#!/usr/bin/env python
"""
loop_status.py — cross-platform 'make loop-status'
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LATEST_JSON = REPO_ROOT / "runtime" / "runs" / "latest.json"
LATEST_REPORT = REPO_ROOT / "runtime" / "reports" / "REPORT_LATEST.md"

print("=== latest.json ===")
if LATEST_JSON.exists():
    try:
        d = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
        print(f"  run_id  : {d.get('run_id', '?')}")
        print(f"  status  : {d.get('status', '?')}")
        print(f"  summary : {d.get('summary', '?')}")
        print(f"  stopped : {d.get('stopped_at', '?')}")
    except Exception as e:
        print(f"  (読み込みエラー: {e})")
else:
    print("  (まだありません — make loop-start を先に実行してください)")

print()
print("=== REPORT_LATEST.md ===")
if LATEST_REPORT.exists():
    lines = LATEST_REPORT.read_text(encoding="utf-8").splitlines()
    for line in lines[:30]:
        print(" ", line)
    if len(lines) > 30:
        print(f"  ... ({len(lines) - 30} 行省略)")
else:
    print("  (まだありません)")
