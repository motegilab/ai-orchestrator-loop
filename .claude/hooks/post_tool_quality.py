#!/usr/bin/env python3
"""PostToolUse Hook: post_tool_quality.py - 品質チェックと監査ログ記録"""
import json, sys, py_compile
from datetime import datetime, timezone
from pathlib import Path

RUNTIME = Path("runtime")
AUDIT_LOG = RUNTIME / "artifacts" / "audit_log.jsonl"
POLICY_FILE = Path("policy") / "policy.json"


def load_policy():
    try:
        return json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def append_audit(event, result):
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": datetime.now(timezone.utc).isoformat(),
                 "tool_name": event.get("tool_name"),
                 "file_path": event.get("tool_input", {}).get("file_path", ""),
                 "result": result}
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[post_tool_quality] audit失敗: {e}", file=sys.stderr)


def check_report_fields(file_path, policy):
    """REPORT_LATEST.md に必須フィールドが揃っているか確認"""
    required = policy.get("self_repair_loop", {}).get("report_fields_required", [])
    if not required:
        return {"check": "report_fields", "ok": True, "msg": "policy未定義のためスキップ"}
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return {"check": "report_fields", "ok": True, "msg": "ファイル読み取り不可"}

    missing = [f for f in required if f"## {f}" not in content]
    if missing:
        msg = f"REPORT必須フィールドが不足: {missing}"
        print(f"[post_tool_quality] ⚠️ {msg}", file=sys.stderr)
        return {"check": "report_fields", "ok": False, "missing": missing}
    return {"check": "report_fields", "ok": True}


def check_claude_md_lines(file_path):
    """CLAUDE.md が200行以内か確認"""
    try:
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        if len(lines) > 200:
            msg = f"CLAUDE.md が {len(lines)} 行。200行制限を超過"
            print(f"[post_tool_quality] ⚠️ {msg}", file=sys.stderr)
            return {"check": "claude_md_lines", "ok": False, "lines": len(lines)}
        return {"check": "claude_md_lines", "ok": True, "lines": len(lines)}
    except Exception:
        return {"check": "claude_md_lines", "ok": True, "msg": "読み取り不可"}


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        event = {}

    tool_input = event.get("tool_input", {})
    file_path = tool_input.get("file_path", tool_input.get("path", ""))
    result = {"ok": True, "checks": []}
    policy = load_policy()

    if file_path:
        p = Path(file_path)

        # Python 構文チェック
        if p.suffix == ".py" and p.exists():
            try:
                py_compile.compile(file_path, doraise=True)
                result["checks"].append({"check": "python_syntax", "ok": True})
            except py_compile.PyCompileError as e:
                result["ok"] = False
                result["checks"].append({"check": "python_syntax", "ok": False, "msg": str(e)})
                print(f"[post_tool_quality] ⚠️ 構文エラー: {file_path}: {e}", file=sys.stderr)

        # REPORT_LATEST.md 必須フィールドチェック
        if p.name == "REPORT_LATEST.md" and p.exists():
            chk = check_report_fields(file_path, policy)
            result["checks"].append(chk)
            if not chk["ok"]:
                result["ok"] = False

        # CLAUDE.md 200行制限チェック
        if p.name == "CLAUDE.md" and p.exists():
            chk = check_claude_md_lines(file_path)
            result["checks"].append(chk)
            if not chk["ok"]:
                result["ok"] = False

    append_audit(event, result)
    sys.exit(0)


if __name__ == "__main__":
    main()
