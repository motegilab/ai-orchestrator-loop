#!/usr/bin/env python3
"""PreCompact Hook: コンテキスト圧縮前に重要情報を保全する

コンテキストが長くなると Claude Code が自動圧縮する。
このフックは圧縮前に実行され、失ってはならない情報を
additionalContext として注入することで圧縮後も継続できるようにする。
"""
import json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def read_section(text: str, heading: str) -> str:
    """SSOT.md から指定セクションを抽出する"""
    lines = text.splitlines()
    result = []
    in_section = False
    for line in lines:
        if line.strip().startswith(heading):
            in_section = True
            result.append(line)
            continue
        if in_section:
            if line.startswith("## ") and not line.strip().startswith(heading):
                break
            result.append(line)
    return "\n".join(result).strip()


def main():
    context_parts = []

    # ── 現在のタスク（latest.json から）────────────────────────────
    latest = REPO_ROOT / "runtime" / "runs" / "latest.json"
    if latest.exists():
        try:
            d = json.loads(latest.read_text(encoding="utf-8"))
            nt = d.get("next_task")
            if nt:
                context_parts.append(
                    f"【現在のタスク】{nt.get('task_id')} — {nt.get('task_title')}\n"
                    f"  マイルストーン: {nt.get('milestone_title')} > {nt.get('wave_title')}"
                )
            ms_done = d.get("milestone_completed")
            if ms_done:
                context_parts.append(
                    f"【マイルストーン完了】{ms_done.get('milestone_id')} — {ms_done.get('milestone_title')}\n"
                    f"  → milestone-review Skill を実行して MANUAL_CHECK HTML を生成してください"
                )
        except Exception:
            pass

    # ── SSOT.md の絶対ルール（§1）────────────────────────────────
    ssot = REPO_ROOT / "SSOT.md"
    if ssot.exists():
        try:
            text = ssot.read_text(encoding="utf-8")
            rules = read_section(text, "## §1")
            if rules:
                context_parts.append(f"【SSOT §1 絶対ルール（変更不可）】\n{rules}")
        except Exception:
            pass

    # ── ワークフロー指示（CLAUDE.md から）──────────────────────────
    context_parts.append(
        "【ワークフロー】Observe → Patch → Verify → Report の順で進めること。\n"
        "セッション終了前に必ず report Skill を実行すること。\n"
        "SSOT.md と policy/ssot_integrity.json は絶対に編集しないこと。"
    )

    if not context_parts:
        sys.exit(0)

    additional = "\n\n".join(context_parts)
    print(json.dumps({
        "hookSpecificOutput": {
            "additionalContext": f"=== コンテキスト圧縮前に保全された重要情報 ===\n\n{additional}"
        }
    }))


if __name__ == "__main__":
    main()
