# SSOT: Claude-First AI Orchestrator Loop

NS_ID: NS_AI_ORCHESTRATOR_LOOP_CLAUDE_SSOT
バージョン: 1.0（Claude-first / Hook-driven）
最終更新: 2026-03-05
前バージョン: SSOT v2.0（CODEX版, 2026-02-18）

---

## §0 設計原則

| 原則 | 内容 |
|------|------|
| Claude-First | Claude Code CLIが唯一の実行エンジン。Webhookサーバ不要 |
| Hook-Driven Loop | ループ制御はSessionStart/Stop/PreToolUse/PostToolUse Hookが担う |
| 汎用性 | 任意のPJワークスペースで動く。テンプレートリポジトリとして機能する |
| Files-as-Memory | 状態管理はファイル（JSON/MD）で完結 |
| SSOT-First | 必ずSSO.md を読んでから実行。UserPromptSubmit Hookで強制される |
| 1原因1修正 | 1ループで修正するのは1原因に起因する1修正のみ |
| 監査ログが真実 | runtime/runs/latest.json と REPORT_LATEST.md が唯一の真実 |
| Human Tool哲学 | AIがワークフロー主導。人間は make loop-start を叩くだけ |

---

## §1 絶対ルール（v1）

以下はPreToolUse Hookで確定的（100%）にブロックされる:

- SSOT.mdを自動ループ内で編集しない（SSOT更新は手動のみ）
- policy/ssot_integrity.jsonを自動ループ内で編集しない
- runtime/以外にランタイム生成物を置かない
- .git/以下への直接書き込みをしない
- 外部APIへのネットワーク接続をしない（v1スコープ）
- タイムアウト時を「成功」として記録しない（必ずfailedと記録）

### §1.1 許可される実行入口（v1）

| コマンド | 動作 |
|----------|------|
| `make loop-start` | Claude Code CLIを起動 |
| `make loop-status` | runtime状態を表示 |
| `make loop-stop` | セッションを終了 |

---

## §2 環境スタック

| レイヤ | ツール | 要件 |
|--------|--------|------|
| AI CLI | Claude Code CLI | v2.0以降 |
| Hook runtime | Python | 3.9以上。標準ライブラリのみ |
| 入口 | make | GNU Make 3.81以上 |

---

## §3 ループ仕様（Hook-Driven）

**コンポーネント依存関係**: on_session_start.py → Claude作業 → on_stop.py → runtime/ の順で依存する。

**1ループ**: make loop-start → SessionStart → Claude作業 → Stop → runtime更新

### §3.1 SessionStart Hook（on_session_start.py）
1. 環境チェック
2. runtime/runs/latest.json を読む
3. runtime/reports/REPORT_LATEST.md を読む
4. runtime/logs/next_session.md を読む
5. 要約をstdoutに出力 → Claude のadditionalContextに自動注入

### §3.2 Stop Hook（on_stop.py）
1. runs/YYYY-MM-DD_runNNN.json を生成
2. runs/latest.json を更新
3. reports/REPORT_LATEST.md を生成
4. logs/next_session.md を生成（次回SessionStartで使用）
⚠️ stop_hook_active フィールドを確認してexit 0すること（無限ループ防止）

### §3.3 PreToolUse Hook（ssot_gate.py）
- matcher: Write|Edit|MultiEdit
- SSOT.mdへの書き込み: 常にブロック（exit 2）
- ssot_integrity.jsonのhash不一致: exit 2

### §3.4 PostToolUse Hook（post_tool_quality.py）
- matcher: Write|Edit
- 全実行を runtime/artifacts/audit_log.jsonl に記録

---

## §3.5 インターフェース契約

| コンポーネント | 入力 | 出力 |
|---|---|---|
| on_session_start.py | なし | stdout（ClaudeのadditionalContext） |
| on_stop.py | なし | runtime/runs/latest.json, REPORT_LATEST.md, next_session.md |
| ssot_gate.py | ツール呼び出し情報 | exit 0（許可）/ exit 2（ブロック） |
| loop_run.py | N（ループ回数） | exit 0（正常）/ exit 1（異常） |

---

## §4 Hooks設定（.claude/settings.json）

```json
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "python .claude/hooks/on_session_start.py"}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python .claude/hooks/ssot_gate.py --mode=prompt"}]}],
    "PreToolUse": [{"matcher": "Write|Edit|MultiEdit", "hooks": [{"type": "command", "command": "python .claude/hooks/ssot_gate.py"}]}],
    "PostToolUse": [{"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "python .claude/hooks/post_tool_quality.py"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "python .claude/hooks/on_stop.py", "timeout": 60}]}]
  }
}
```

---

## §5 Skills仕様（自動invoke対応）

| Skill | トリガ | outputs |
|-------|--------|---------|
| observe | 問題調査依頼時 / REPORTにエラーがある時 | issue_candidates.md |
| patch | 修正・実装依頼時 | diff summary, files_changed |
| verify | patchの後 / 確認依頼時 | exit_codes, evidence_paths |
| report | 作業終了時 / Stop直前 | REPORT_LATEST.md, latest.json |

---

## §6 ファイル配置ポリシー

| 用途 | パス | Git |
|------|------|-----|
| 設計の正本 | SSOT.md | ✅（自動書き込み禁止） |
| AIへの指示 | CLAUDE.md | ✅（200行以内） |
| Hooks | .claude/hooks/ | ✅ |
| Skills | .claude/skills/ | ✅ |
| ポリシー | policy/ | ✅ |
| タスク記憶 | tasks/milestones.json | ✅ |
| 実行生成物 | runtime/ | ❌（.gitignore必須） |

---

## §7 next_session.md テンプレ（必須セクション）

- **DONE**: 今回セッション要約
- **NEXT**: 次にやること
- **FAIL**: 失敗時のみ。エラー抜粋
- **FIX**: 最小差分・1原因1修正
- **VERIFY**: 再検証コマンド
- **CONTEXT**: 次回セッションに必要な状態情報

---

## §8 GOチェックリスト（v1）

```
[ ] Claude Code CLI v2.0以上インストール済み
[ ] make loop-start でセッションが起動する
[ ] SessionStart Hookが発火しadditionalContextが注入される
[ ] PreToolUse HookがSSO.mdへの書き込みをブロックする
[ ] Stop Hook後にruntime/runs/latest.jsonが生成される
[ ] Stop Hook後にruntime/reports/REPORT_LATEST.mdが生成される
[ ] Stop Hook後にruntime/logs/next_session.mdが生成される
[ ] 次回loop-startで前回のコンテキストが自動注入される
[ ] runtime/** がgit管理外である
```
