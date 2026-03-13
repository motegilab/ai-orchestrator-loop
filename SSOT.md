# SSOT: AI Orchestrator Loop（CODEX版）

NS_ID: NS_AI_ORCHESTRATOR_LOOP_CODEX_SSOT
バージョン: 2.0（CODEX-First / Runner-Driven）
最終更新: 2026-03-13
前バージョン: SSOT v1.0（Claude-First / Hook-Driven, 2026-03-05）

---

## §0 設計原則

| 原則 | 内容 |
|------|------|
| CODEX-First | OpenAI Codex CLI が唯一の実行エンジン。Hookなし |
| Runner-Driven Loop | Pythonランナーがループを外部制御 |
| Files-as-Memory | 状態管理はファイル（JSON/MD）で完結 |
| SSOT-First | 必ずSSoT.mdを読んでから実行。ランナーが強制 |
| 1原因1修正 | 1ループで修正するのは1原因に起因する1修正のみ |
| Prompt-as-Context | next_prompt.md でコンテキスト注入（hookの代替） |
| 監査ログが真実 | runtime/runs/latest.json と REPORT_LATEST.md が唯一の真実 |

---

## §1 絶対ルール

以下はランナーのスコープガードで強制される:

- SSOT.mdを自動ループ内で編集しない
- policy/ssot_integrity.jsonを自動ループ内で編集しない
- runtime/以外にランタイム生成物を置かない
- 1ループで複数原因を修正しない
- タイムアウト時を「成功」として記録しない

### §1.1 許可される実行入口

| コマンド | 動作 |
|----------|------|
| `make codex-loop-run` | ループ開始（自動連続） |
| `make codex-loop-status` | 状態確認 |
| `make codex-setup` | 初期化 |

---

## §2 環境スタック

| レイヤ | ツール | 要件 |
|--------|--------|------|
| AI CLI | OpenAI Codex CLI (`codex`) | v1.0以降（`@openai/codex`） |
| Runner | Python | 3.9以上。標準ライブラリのみ |
| 入口 | make | GNU Make 3.81以上 |

---

## §3 ループ仕様（Runner-Driven）

**1ループ**: ランナー起動 → prompt生成 → codex呼び出し → レポート保存 → 次タスクへ

### §3.1 ループフロー

```
make codex-loop-run
  ↓ tools/codex_scripts/loop_run.py
  ↓ tasks/milestones.json から次タスク取得
  ↓ runtime/runs/latest.json から前回結果読み込み
  ↓ runtime/prompts/next_prompt.md を生成（prompt_builder.py）
  ↓ codex --approval-mode full-auto < runtime/prompts/next_prompt.md
  ↓ stdout から report JSON を抽出（on_loop_end.py）
  ↓ runtime/ にレポートを保存
  ↓ 次タスクなし → 終了 / あり → ループ継続
```

### §3.2 next_prompt.md 構造

1. [CONTEXT] 前回結果 + 現在タスク
2. [SSOT RULES] §0-§1 抜粋（ルール強制）
3. [TASK] タスク詳細
4. [WORKFLOW] Observe → Patch → Verify → Report
5. [REPORT FORMAT] stdout末尾に必ず出力するJSONスキーマ

### §3.3 レポートJSON（stdout末尾に必須出力）

```json
{
  "decision": "success|incomplete|blocked",
  "hypothesis_one_cause": "...",
  "one_fix": "...",
  "files_changed": [],
  "verify_commands": [],
  "exit_codes": [0],
  "evidence_paths": []
}
```

### §3.4 ループ停止条件

- 次タスクが null（全タスク完了）
- 連続2回以上の incomplete
- decision = blocked

---

## §4 ファイル配置ポリシー

| 用途 | パス | Git |
|------|------|-----|
| 設計の正本 | SSOT.md | ✅（自動書き込み禁止） |
| CODEX指示 | AGENTS.md | ✅ |
| Runnerスクリプト | tools/codex_scripts/ | ✅ |
| ポリシー | policy/ | ✅ |
| タスク | tasks/milestones.json | ✅ |
| 実行生成物 | runtime/ | ❌（.gitignore必須） |
| 生成プロンプト | runtime/prompts/ | ❌ |

---

## §5 コンポーネント構成と依存関係

```
SSOT.md + AGENTS.md  ← 設計制約（自動ループ中は読み取り専用）
    ↓ 依存
policy/*.json        ← 機械可読ポリシー
    ↓ 依存
tasks/milestones.json ← タスク定義
    ↓ 依存
tools/codex_scripts/ ← ループ制御ロジック
  ├── loop_run.py      インターフェース: main(n_loops, yes_all) → exit_code
  ├── prompt_builder.py インターフェース: build(task, latest) → next_prompt.md
  ├── on_loop_end.py   インターフェース: parse_and_save(stdout) → latest.json
  ├── scope_guard.py   インターフェース: check(path) → allow/deny
  ├── loop_status.py   インターフェース: show() → stdout
  └── setup.py         インターフェース: setup() → exit_code
    ↓ 出力
runtime/             ← 実行生成物（git管理外）
```

## §6 スコープガード（scope_guard.py）

- 許可読み取り: SSOT.md, AGENTS.md, policy/, tasks/, docs/, runtime/, src/
- 書き込み禁止: SSOT.md, policy/ssot_integrity.json, .git/
- 生成物配置: runtime/ のみ

---

## §6 on_loop_end.py 仕様

1. stdoutからreport JSONを抽出
2. runs/YYYY-MM-DD_runNNN.json を生成
3. runs/latest.json を更新
4. reports/REPORT_LATEST.md を生成
5. logs/next_session.md を生成（次回ループで使用）

---

## §7 GOチェックリスト

```
[ ] codex --version で v1.0+ 動作確認
[ ] make codex-setup が exit 0 で完了する
[ ] AGENTS.md が存在する
[ ] tools/codex_scripts/ が存在する
[ ] tasks/milestones.json が valid JSON
[ ] make codex-loop-run N=1 で1ループ完走する
[ ] runtime/reports/REPORT_LATEST.md に decision が記録される
[ ] runtime/ が git管理外である
```
