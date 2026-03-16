#!/usr/bin/env python3
"""
SessionStart Hook — 環境チェック + 前回コンテキストをClaudeに自動注入
stdout の内容が Claude の additionalContext になる

各セッション開始時に行うこと:
  1. 環境チェック
  2. audit_log.jsonl に session_start マーカーを書き込む（セッション境界）
  3. REPORT_LATEST.md をテンプレート状態にリセット（stale検出のため）
  4. 前回コンテキスト（latest.json + next_session.md）を stdout に出力
  5. Discord 開始通知
"""
import json, sys, os, urllib.request, subprocess
from datetime import datetime, timezone
from pathlib import Path


def check_upstream_updates(repo_root):
    """upstream/main に新しいコミットがあれば通知文を返す（失敗時は None）"""
    try:
        # ローカルが持っている upstream/main の SHA
        local = subprocess.run(
            ["git", "rev-parse", "upstream/main"],
            capture_output=True, text=True, timeout=3, cwd=repo_root
        )
        if local.returncode != 0:
            return None  # upstream remote 未設定

        # リモートの最新 SHA（ネットワークアクセス）
        remote = subprocess.run(
            ["git", "ls-remote", "upstream", "main"],
            capture_output=True, text=True, timeout=5, cwd=repo_root
        )
        if remote.returncode != 0 or not remote.stdout.strip():
            return None

        local_sha  = local.stdout.strip()
        remote_sha = remote.stdout.split()[0].strip()

        if local_sha == remote_sha:
            return None  # 最新

        return (
            f"🔔 テンプレート更新あり（upstream に新しいコミット）\n"
            f"   同期するには: git fetch upstream && Pattern A を実行\n"
            f"   詳細: docs/setup-guide.html の「テンプレートの更新を反映する」を参照\n"
        )
    except Exception:
        return None  # オフライン・タイムアウトは無視


def send_discord_start(repo_root, next_task_label):
    """Discord に ループ開始通知を送る（失敗しても warn-only）"""
    nf = repo_root / "notifications.json"
    if not nf.exists():
        return
    try:
        cfg = json.loads(nf.read_text(encoding="utf-8"))
    except Exception:
        return
    discord = cfg.get("discord", {})
    if not discord.get("enabled", False):
        return
    url = discord.get("webhook_url", "")
    if not url or "YOUR_TOKEN" in url:
        return

    payload = {
        "content": f"🔄 **AI Orchestrator** — ループ開始",
        "embeds": [{
            "color": 0x5865F2,
            "fields": [
                {"name": "タスク", "value": next_task_label, "inline": False},
                {"name": "開始時刻", "value": datetime.now().strftime("%H:%M:%S"), "inline": True},
            ],
        }],
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
            "User-Agent": "AI-Orchestrator/1.0",
        }, method="POST")
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        print(f"[session_start] WARNING: Discord開始通知失敗: {e}", file=sys.stderr)


def main():
    repo_root = Path(__file__).parent.parent.parent
    os.chdir(repo_root)
    lines = ["=== AI Orchestrator Loop — セッション開始 ===\n"]

    # 環境チェック
    missing = [f for f in ["SSOT.md","CLAUDE.md","policy/policy.json"] if not Path(f).exists()]
    if missing:
        lines.append(f"WARNING: 必須ファイルが見つかりません: {', '.join(missing)}\n")
    else:
        lines.append("✅ 環境チェック: OK\n")

    # ── セッション境界マーカーを audit_log.jsonl に書き込む ──────────────
    # これにより on_stop.py が「このセッションの変更のみ」を集計できる
    artifact_dir = Path("runtime/artifacts")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    audit_log = artifact_dir / "audit_log.jsonl"
    session_ts = datetime.now(timezone.utc).isoformat()
    marker = {"type": "session_start", "timestamp": session_ts}
    try:
        with open(audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(marker, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[session_start] WARNING: audit_log マーカー書き込み失敗: {e}", file=sys.stderr)

    # ── REPORT_LATEST.md をテンプレート状態にリセット ────────────────────
    # Claude が report Skill を使って書き直さない限り PLACEHOLDER_MARKERS が残る
    # → on_stop.py が「Claudeは書かなかった」と正しく判定できる
    reports_dir = Path("runtime/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "REPORT_LATEST.md"
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_template = f"""# REPORT_LATEST.md
run_id: current_session
generated_at: {ts_str}
status: pending
generated_by: (Claudeが作業中に更新する)

## hypothesis_one_cause
Claudeが作業中に更新する

## one_fix
実施した修正

## files_changed
変更ファイル

## verify_commands
```
make loop-status
```

## exit_codes
- (未記録)

## evidence_paths
- runtime/artifacts/audit_log.jsonl

## decision
(Claudeが作業中に更新する)

## DONE
(未記録)

## NEXT
(未記録)

## FAIL
なし
"""
    try:
        report_path.write_text(report_template, encoding="utf-8")
    except Exception as e:
        print(f"[session_start] WARNING: REPORT_LATEST.md リセット失敗: {e}", file=sys.stderr)

    # ── 前回ループの結果 ────────────────────────────────────────────────
    latest_json = Path("runtime/runs/latest.json")
    next_task_label = "タスク確認中"
    if latest_json.exists():
        try:
            d = json.loads(latest_json.read_text(encoding="utf-8"))
            lines.append(f"前回ループ: {d.get('run_id','?')} / status={d.get('status','?')}\n")
            lines.append(f"要約: {d.get('summary','?')}\n")
            nt = d.get("next_task")
            if nt:
                next_task_label = f"{nt['task_id']} — {nt['task_title']}"
            else:
                next_task_label = "全タスク完了"
        except Exception as e:
            lines.append(f"latest.json 読み込みエラー: {e}\n")
    else:
        lines.append("前回ループ: なし（初回起動）\n")
        next_task_label = "初回セットアップ"

    # ── 引き継ぎコンテキスト ────────────────────────────────────────────
    next_session = Path("runtime/logs/next_session.md")
    if next_session.exists():
        lines.append("\n--- 前回セッションからの引き継ぎ ---\n")
        lines.append(next_session.read_text(encoding="utf-8"))
        lines.append("--- 引き継ぎここまで ---\n")
    else:
        lines.append("\n初回起動: SSOT.mdとCLAUDE.mdを読んでから tasks/milestones.json のタスクを開始してください。\n")

    # ── upstream 更新チェック ────────────────────────────────────────────
    update_msg = check_upstream_updates(repo_root)
    if update_msg:
        lines.append(f"\n{update_msg}")

    print("".join(lines))

    # ── Discord 開始通知 ────────────────────────────────────────────────
    send_discord_start(repo_root, next_task_label)


if __name__ == "__main__":
    main()
