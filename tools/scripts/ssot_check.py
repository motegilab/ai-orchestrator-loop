#!/usr/bin/env python
"""
ssot_check.py — SSOT 品質チェッカー

Usage:
  python tools/scripts/ssot_check.py        # 通常チェック
  python tools/scripts/ssot_check.py --json # JSON出力

Exit codes:
  0: 問題なし (OK)
  1: 警告あり (WARN)
  2: エラーあり (ERROR) → loop-run がブロックする
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent.parent
SSOT_MD    = REPO_ROOT / "SSOT.md"
MILESTONES = REPO_ROOT / "tasks" / "milestones.json"


def run_checks(ssot_path: Path, milestones_path: Path) -> list[tuple[str, str]]:
    """
    チェックを実行して (severity, message) のリストを返す。
    severity: "OK" | "WARN" | "ERROR"
    """
    issues: list[tuple[str, str]] = []

    def add(severity, message):
        issues.append((severity, message))

    # ─── SSOT.md チェック ────────────────────────────────────
    if not ssot_path.exists():
        add("ERROR", "SSOT.md が存在しません")
    else:
        text = ssot_path.read_text(encoding="utf-8")

        for key, label in [("§0", "§0 設計原則"), ("§1", "§1 絶対ルール"), ("§2", "§2 環境")]:
            if key in text:
                add("OK", f"{label}: 存在")
            else:
                add("ERROR", f"SSOT.md に必須セクション {label} が見つかりません")

        if "GOチェックリスト" in text or "go-checklist" in text or "チェックリスト" in text:
            add("OK", "GOチェックリストへの言及: 存在")
        else:
            add("WARN", "SSOT.md に GOチェックリストへの言及がありません")

        if "依存" in text or "import" in text:
            add("OK", "依存関係ルール: 言及あり")
        else:
            add("WARN", "SSOT.md にコンポーネント依存ルールが未定義です")

        if "コンポーネント" in text or "アーキテクチャ" in text:
            if ("interface" in text.lower() or "インターフェース" in text
                    or "def " in text or "class " in text):
                add("OK", "コンポーネントインターフェース契約: 存在")
            else:
                add("WARN", "アーキテクチャセクションがありますがインターフェース契約が未定義です")

    # ─── milestones.json チェック ────────────────────────────
    if not milestones_path.exists():
        add("ERROR", "tasks/milestones.json が存在しません")
    else:
        try:
            data = json.loads(milestones_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            add("ERROR", f"tasks/milestones.json が不正な JSON です: {e}")
            data = {}

        milestones = data.get("milestones", [])
        if not milestones:
            add("WARN", "milestones が空です")

        TBD_PAT    = re.compile(r"TBD|未定|TODO", re.IGNORECASE)
        VERIFY_PAT = re.compile(r"pytest|verify|確認|テスト|test", re.IGNORECASE)

        for ms in milestones:
            ms_id  = ms.get("id", "?")
            ms_title = ms.get("title", "")
            all_tasks = [t for w in ms.get("waves", []) for t in w.get("tasks", [])]

            has_verify = any(VERIFY_PAT.search(t.get("title", "")) for t in all_tasks)
            if not has_verify and all_tasks:
                add("WARN", f"{ms_id} に統合確認タスク（pytest/verify）がありません: {ms_title[:40]}")

            for task in all_tasks:
                t_id     = task.get("id", "?")
                t_title  = task.get("title", "")
                t_status = task.get("status", "")

                if t_status != "done" and TBD_PAT.search(t_title):
                    add("ERROR", f"{t_id} タイトルに未定義キーワードが含まれます: 「{t_title[:40]}」")

                if t_status == "pending" and len(t_title) < 20:
                    add("WARN", f"{t_id} タイトルが短すぎます（{len(t_title)}文字）: 「{t_title}」")

    return issues


def calc_result(issues: list[tuple[str, str]]) -> tuple[str, int, int]:
    """(verdict, score, exit_code) を返す"""
    errors = sum(1 for s, _ in issues if s == "ERROR")
    warns  = sum(1 for s, _ in issues if s == "WARN")
    oks    = sum(1 for s, _ in issues if s == "OK")
    score  = max(0, min(100, oks * 10 - warns * 5 - errors * 20))
    if errors:
        return "ERROR", score, 2
    if warns:
        return "WARN", score, 1
    return "OK", score, 0


# ─── CLI エントリポイント ────────────────────────────────────
if __name__ == "__main__":
    JSON_MODE = "--json" in sys.argv
    issues    = run_checks(SSOT_MD, MILESTONES)
    verdict, score, exit_code = calc_result(issues)

    if JSON_MODE:
        errors = [m for s, m in issues if s == "ERROR"]
        warns  = [m for s, m in issues if s == "WARN"]
        oks    = [m for s, m in issues if s == "OK"]
        print(json.dumps(
            {"verdict": verdict, "score": score,
             "errors": errors, "warns": warns, "oks": oks, "exit_code": exit_code},
            ensure_ascii=False, indent=2
        ))
    else:
        print("=== SSOT Quality Check ===")
        for severity, message in issues:
            icon = {"OK": "  OK  ", "WARN": " WARN ", "ERROR": "ERROR "}[severity]
            print(f"  {icon}  {message}")
        print()
        print(f"スコア: {score}/100")
        if verdict == "ERROR":
            print("判定: ERROR — SSOT に重大な問題があります。--skip-check で強制実行可。")
        elif verdict == "WARN":
            print("判定: WARN — 警告があります。")
        else:
            print("判定: OK — 問題ありません。")

    sys.exit(exit_code)
