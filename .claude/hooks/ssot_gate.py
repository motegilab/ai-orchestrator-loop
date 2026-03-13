#!/usr/bin/env python3
"""PreToolUse Hook: ssot_gate.py - SSOT整合性チェック"""
import hashlib, json, sys
from pathlib import Path

SSOT = Path("SSOT.md")
POLICY_DIR = Path("policy")
INTEGRITY_FILE = POLICY_DIR / "ssot_integrity.json"
PROTECTED_PATHS = ["SSOT.md", "policy/ssot_integrity.json", "policy/policy.json", ".claude/hooks/ssot_gate.py", ".git/"]

def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_integrity():
    try:
        return json.loads(INTEGRITY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": True, "files": {}}

def check_ssot_integrity():
    integrity = load_integrity()
    if not integrity.get("enabled", True):
        return True, "disabled"
    for filepath, expected in integrity.get("files", {}).items():
        if expected == "PLACEHOLDER_RUN_UPDATE_HASH_COMMAND":
            continue  # 初回セットアップ前はスキップ
        p = Path(filepath)
        if not p.exists():
            return False, f"SSOT-GATE: {filepath} が見つかりません"
        actual = sha256_file(p)
        if actual != expected:
            return False, f"SSOT-GATE: BLOCKED\n  {filepath} のhashが不一致。\n  手動更新: python .claude/hooks/ssot_gate.py --update-hash"
    return True, "ok"

def check_tool_input(event):
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    if tool_name in ("Write", "Edit", "MultiEdit"):
        file_path = tool_input.get("file_path", tool_input.get("path", ""))
        for protected in PROTECTED_PATHS:
            if file_path == protected or file_path.startswith(protected):
                return False, f"SSOT-GATE: BLOCKED\n  {file_path} への書き込みはSSO.md §1で禁止されています。"
    return True, "ok"

def update_hash():
    if not SSOT.exists():
        print(f"ERROR: {SSOT} が見つかりません", file=sys.stderr)
        sys.exit(1)
    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    integrity = load_integrity()
    integrity["enabled"] = True
    integrity.setdefault("files", {})
    integrity["files"][str(SSOT)] = sha256_file(SSOT)
    INTEGRITY_FILE.write_text(json.dumps(integrity, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Hash updated: SSOT.md = {integrity['files'][str(SSOT)][:16]}...")

def main():
    args = sys.argv[1:]
    mode = "tool"
    for arg in args:
        if arg == "--mode=prompt": mode = "prompt"
        elif arg == "--update-hash":
            update_hash()
            sys.exit(0)

    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        event = {}

    ok, reason = check_ssot_integrity()
    if not ok:
        print(reason, file=sys.stderr)
        sys.exit(2)

    if mode == "tool":
        ok, reason = check_tool_input(event)
        if not ok:
            print(reason, file=sys.stderr)
            sys.exit(2)

    sys.exit(0)

if __name__ == "__main__":
    main()
