#!/usr/bin/env python
"""
Stop Hook: on_stop.py
役割（legacyの planner.py + report生成を統合）:
  1. audit_log.jsonl から実際の変更ファイルを抽出
  2. REPORT_LATEST.md を検査（Claudeが書いたか / テンプレートのままか）
  3. milestones.json から次の pending タスクを特定
  4. next_session.md を生成（具体的なアクション指示入り）= ループの燃料
  5. runs/YYYY-MM-DD_runNNN.json と latest.json を保存

next_session.md はメタ指示（「○○を読んで確認する」）ではなく
具体的な実行指示（「T1を実行してreportを書く」）を書く。
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── パス定義 ──────────────────────────────────────────────────────────
REPO_ROOT     = Path(__file__).parent.parent.parent
RUNTIME       = REPO_ROOT / "runtime"
RUNS_DIR      = RUNTIME / "runs"
REPORTS_DIR   = RUNTIME / "reports"
LOGS_DIR      = RUNTIME / "logs"
ARTIFACTS     = RUNTIME / "artifacts"
AUDIT_LOG     = ARTIFACTS / "audit_log.jsonl"
MILESTONES    = REPO_ROOT / "tasks" / "milestones.json"
LATEST_RUN    = RUNS_DIR / "latest.json"
LATEST_REPORT = REPORTS_DIR / "REPORT_LATEST.md"
NEXT_SESSION  = LOGS_DIR / "next_session.md"

# Claudeが report Skill を実行せずに終了したと判定するマーカー
PLACEHOLDER_MARKERS = [
    "Claudeが作業中に更新する",
    "実施した修正",
    "変更ファイル",
]


def get_run_id():
    today = datetime.now().strftime("%Y-%m-%d")
    existing = [
        f for f in RUNS_DIR.glob(f"{today}_run*.json")
        if f.name != "latest.json"
    ] if RUNS_DIR.exists() else []
    return f"{today}_run{len(existing)+1:03d}"


def is_report_template(path):
    """REPORT_LATEST.md がまだテンプレートのままか判定"""
    if not path.exists():
        return True
    content = path.read_text(encoding="utf-8")
    return any(m in content for m in PLACEHOLDER_MARKERS)


def read_audit_entries():
    """audit_log.jsonl から現セッションのエントリのみを返す。
    session_start マーカーを境界として、最後のマーカー以降のエントリのみ集計する。
    """
    if not AUDIT_LOG.exists():
        return []
    entries = []
    for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("type") == "session_start":
                entries = []  # セッション境界でリセット → 現セッション分のみ残る
            else:
                entries.append(entry)
        except json.JSONDecodeError:
            pass
    return entries


def get_changed_files(audit_entries):
    return [
        e.get("file_path", "?")
        for e in audit_entries
        if e.get("tool_name") in ("Write", "Edit", "MultiEdit")
    ]


def get_next_task():
    """milestones.json から次の pending タスクを返す"""
    if not MILESTONES.exists():
        return None
    try:
        data = json.loads(MILESTONES.read_text(encoding="utf-8"))
    except Exception:
        return None
    for ms in data.get("milestones", []):
        if ms.get("status") in ("pending", "in_progress"):
            for wave in ms.get("waves", []):
                for task in wave.get("tasks", []):
                    if task.get("status") == "pending":
                        return {
                            "milestone_title": ms["title"],
                            "wave_title": wave["title"],
                            "task_id": task["id"],
                            "task_title": task["title"],
                            "checkpoint": task.get("checkpoint", False),
                        }
    return None


def get_just_completed_milestone():
    """全タスクが done だがマイルストーン自体が未完了（pending/in_progress）のものを返す。
    マイルストーンの最後のタスクが done になった瞬間に検出される。
    """
    if not MILESTONES.exists():
        return None
    try:
        data = json.loads(MILESTONES.read_text(encoding="utf-8"))
    except Exception:
        return None
    for ms in data.get("milestones", []):
        if ms.get("status") in ("pending", "in_progress"):
            all_tasks = [
                task
                for wave in ms.get("waves", [])
                for task in wave.get("tasks", [])
            ]
            if all_tasks and all(t.get("status") == "done" for t in all_tasks):
                return {
                    "milestone_id": ms["id"],
                    "milestone_title": ms["title"],
                    "task_count": len(all_tasks),
                }
    return None


def handle_report(run_id, ts, audit_entries):
    """
    REPORT_LATEST.md を検査し、テンプレートのままなら自動生成する。
    戻り値: "written_by_claude" | "auto_generated" | "incomplete"
    """
    if not is_report_template(LATEST_REPORT):
        return "written_by_claude"

    changed = get_changed_files(audit_entries)
    changed_md = "\n".join(f"- {f}" for f in changed) if changed else "- (変更なし)"
    source = "auto_generated" if changed else "incomplete"

    report = f"""# REPORT_LATEST.md
run_id: {run_id}
generated_at: {ts}
status: {source}
generated_by: on_stop.py (Claude が report Skill を使わずセッションを終了)

## hypothesis_one_cause
(このセッションでは Claude が report Skill を実行しませんでした)

## one_fix
(未記録)

## files_changed
{changed_md}

## verify_commands
```
make loop-status
```

## exit_codes
- n/a

## evidence_paths
- runtime/artifacts/audit_log.jsonl
- runtime/runs/{run_id}.json

## decision
{source}

## NOTE
次回セッションでは必ずセッション終了前に report Skill を実行してください。
"""
    try:
        LATEST_REPORT.write_text(report, encoding="utf-8")
    except Exception as e:
        print(f"[on_stop] WARNING: REPORT書き込み失敗: {e}", file=sys.stderr)
    return source


def generate_next_session(run_id, ts, report_source, next_task, audit_entries, completed_milestone=None):
    """
    next_session.md を生成する。これがループの燃料。
    指示は「何を読むか」ではなく「何をするか」を明示する。
    """
    changed = get_changed_files(audit_entries)

    # 前回セッションのサマリ
    if changed:
        done_text = (
            f"前回セッション（{run_id}）で {len(changed)} 件のファイルを変更:\n"
            + "\n".join(f"  - {f}" for f in changed[:10])
        )
    else:
        done_text = f"前回セッション（{run_id}）では実際のファイル変更はありませんでした。"

    done_text += f"\n  report_source: {report_source}"

    # report から decision を抽出（## decision の直後の非空行を取得）
    report_decision = "不明"
    if LATEST_REPORT.exists():
        in_decision = False
        for line in LATEST_REPORT.read_text(encoding="utf-8").splitlines():
            if line.startswith("## decision"):
                in_decision = True
                continue
            if in_decision and line.strip():
                report_decision = line.strip()
                break

    # マイルストーン完了時は milestone-review Skill の実行を最優先指示
    if completed_milestone:
        ms_id    = completed_milestone["milestone_id"]
        ms_title = completed_milestone["milestone_title"]
        ms_count = completed_milestone["task_count"]
        next_action = f"""## 🎉 マイルストーン完了 — NEXT ACTION（必ずこれを先に実行）

**[{ms_id}] {ms_title}** の全 {ms_count} タスクが完了しました。

### 実行手順
1. **milestone-review Skill を実行して** `runtime/reports/MANUAL_CHECK_{ms_id}.html` を生成する
2. 生成した HTML をブラウザで開いてユーザーに確認を促す
3. milestones.json の `{ms_id}` の status を `"done"` に更新する
4. report Skill でこのセッションの結果を記録する

### ⚠️ 重要
- 次のマイルストーンのタスクは、人間が MANUAL_CHECK_{ms_id}.html を確認してからでないと開始しない
- milestone-review Skill を先に実行すること"""
    # 次タスクの具体的な実行指示
    elif next_task:
        next_action = f"""## NEXT ACTION（これを実行してください）

次のタスク: **{next_task['task_id']} — {next_task['task_title']}**
マイルストーン: {next_task['milestone_title']} > {next_task['wave_title']}

### 実行手順（この順番で行うこと）
1. observe Skill を使って現状を調査する
2. 必要な変更を patch Skill で最小差分で実施する（1原因1修正を厳守）
3. verify Skill で結果を確認する（exit コードと stdout を記録）
4. tasks/milestones.json の {next_task['task_id']} を "done" に更新する
5. **セッション終了前に必ず report Skill を実行して REPORT_LATEST.md に記録する**

### report Skill 実行後の確認
- runtime/reports/REPORT_LATEST.md に decision が記録されているか確認する
- "written_by_claude" 状態になっているか確認する"""
    else:
        next_action = """## NEXT ACTION（これを実行してください）

全ての pending タスクが完了しています。

1. SSOT.md を確認して次のフェーズが定義されているか確認する
2. tasks/milestones.json を確認して次のマイルストーンを追加する
3. report Skill でこのセッションの結果を記録する"""

    # FAIL / FIX（前回レポートから抽出）
    fail_text = "（前回セッションで記録された失敗なし）"
    fix_text = "（対処不要）"
    if LATEST_REPORT.exists():
        content = LATEST_REPORT.read_text(encoding="utf-8")
        if any(w in content for w in ["failed", "incomplete", "blocked"]):
            fail_text = "前回セッションのレポートを参照: runtime/reports/REPORT_LATEST.md"
            fix_text = "REPORT_LATEST.md の hypothesis_one_cause と one_fix を確認して 1原因1修正で対処する"

    content = f"""# Next Session Context
generated_at: {ts}
previous_run_id: {run_id}
report_source: {report_source}

## DONE
{done_text}

{next_action}

## FAIL
{fail_text}

## FIX
{fix_text}

## VERIFY
```
make loop-status
```

## CONTEXT
- 前回 run_id: {run_id}
- report_source: {report_source}
- 変更ファイル数: {len(changed)}
- 前回レポート decision: {report_decision}
- 次タスク: {next_task['task_id'] + ' — ' + next_task['task_title'] if next_task else "全完了"}

## RULES（必ず守ること）
- 1原因1修正。複数の問題を1セッションで直さない
- セッション終了前に必ず report Skill を実行すること
- SSOT.md と policy/ssot_integrity.json は絶対に編集しない
- runtime/ 以外にランタイム生成物を置かない
"""
    try:
        NEXT_SESSION.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"[on_stop] WARNING: next_session.md書き込み失敗: {e}", file=sys.stderr)


def load_notifications():
    """notifications.json を読む（なければ None）"""
    path = REPO_ROOT / "notifications.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def send_discord_notification(record):
    """Discord Webhook に run 結果を送信する（失敗しても warn-only）"""
    config = load_notifications()
    if not config:
        return
    discord = config.get("discord", {})
    if not discord.get("enabled", False):
        return
    webhook_url = discord.get("webhook_url", "")
    if not webhook_url or "YOUR_TOKEN" in webhook_url:
        return

    run_id = record.get("run_id", "?")
    status = record.get("status", "?")
    report_source = record.get("report_source", "?")
    changed = len(record.get("files_changed", []))
    next_task = record.get("next_task")
    next_label = next_task["task_id"] + " — " + next_task["task_title"] if next_task else "全タスク完了"

    has_next = next_task is not None
    status_icon = "✅" if status == "success" else "⚠️"
    loop_icon = "🔁 次ループへ" if has_next else "🎉 全タスク完了"
    mention = f"<@&{discord['mention_role_id']}> " if discord.get("mention_role_id") else ""

    payload = {
        "content": f"{mention}{status_icon} **AI Orchestrator** — `{run_id}` 完了　{loop_icon}",
        "embeds": [{
            "color": 0x57F287 if status == "success" else 0xFEE75C,
            "fields": [
                {"name": "status", "value": status, "inline": True},
                {"name": "report", "value": report_source, "inline": True},
                {"name": "変更ファイル数", "value": str(changed), "inline": True},
                {"name": "次タスク", "value": next_label, "inline": False},
            ],
        }],
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AI-Orchestrator/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                print(f"[on_stop] WARNING: Discord webhook HTTP {resp.status}", file=sys.stderr)
    except Exception as e:
        print(f"[on_stop] WARNING: Discord webhook送信失敗: {e}", file=sys.stderr)


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        event = {}

    # 無限ループ防止
    if event.get("stop_hook_active"):
        sys.exit(0)

    # ディレクトリ確保
    for d in [RUNS_DIR, REPORTS_DIR, LOGS_DIR, ARTIFACTS]:
        d.mkdir(parents=True, exist_ok=True)

    run_id = get_run_id()
    now_iso = datetime.now(timezone.utc).isoformat()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    audit_entries = read_audit_entries()
    changed_files = get_changed_files(audit_entries)

    # REPORT 検査 / 自動生成
    report_source = handle_report(run_id, ts, audit_entries)

    # 次タスクを milestones.json から取得
    next_task = get_next_task()

    # マイルストーン完了チェック
    completed_milestone = get_just_completed_milestone()

    # next_session.md 生成（ループの燃料）
    generate_next_session(run_id, ts, report_source, next_task, audit_entries, completed_milestone)

    # run レコード保存
    status = "success" if report_source == "written_by_claude" else report_source
    record = {
        "run_id": run_id,
        "session_id": event.get("session_id", "unknown"),
        "started_at": event.get("started_at", now_iso),
        "stopped_at": now_iso,
        "source": "claude-code-cli",
        "intent": "task_completed",
        "summary": f"report={report_source} / 変更{len(changed_files)}件 / next={next_task['task_id'] if next_task else 'none'}",
        "status": status,
        "top_errors": [],
        "files_changed": changed_files,
        "report_source": report_source,
        "evidence_paths": [str(LATEST_REPORT), str(NEXT_SESSION), str(AUDIT_LOG)],
        "report_status": "success",
        "report_path": str(LATEST_REPORT),
        "next_session_path": str(NEXT_SESSION),
        "next_task": next_task,
        "milestone_completed": completed_milestone,
    }
    try:
        run_path = RUNS_DIR / f"{run_id}.json"
        run_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        LATEST_RUN.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[on_stop] WARNING: run record書き込み失敗: {e}", file=sys.stderr)

    # REPORT_LATEST.md をアーカイブ（Claudeが書いた場合のみ保存）
    # auto_generated や stale なレポートは archive しない
    if report_source == "written_by_claude":
        try:
            if LATEST_REPORT.exists():
                import shutil
                shutil.copy2(LATEST_REPORT, REPORTS_DIR / f"{run_id}.md")
        except Exception as e:
            print(f"[on_stop] WARNING: report archive失敗: {e}", file=sys.stderr)

    # Discord 通知（notifications.json が設定されている場合のみ）
    send_discord_notification(record)

    label = next_task["task_id"] if next_task else "all-done"
    print(f"[on_stop] {run_id} / report={report_source} / changed={len(changed_files)} / next={label}", file=sys.stderr)


if __name__ == "__main__":
    main()
