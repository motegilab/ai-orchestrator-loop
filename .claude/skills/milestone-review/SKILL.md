---
name: milestone-review
description: マイルストーン完了時に人間向けマニュアルチェックリストHTMLを生成するSkill。loop_run.pyが「milestone_completed」を検出した時、または「マイルストーンレビュー」「チェックリスト生成」と言われた時に自動invokeする。
allowed-tools: "Read, Write, Glob"
metadata:
  version: 1.0.0
---

# Milestone Review Skill

## 役割

マイルストーン完了時に、**人間が手動で確認すべき事項**をまとめた HTML チェックリストを生成する。
テンプレートではなく、実際の実装内容・SSOT・Reportを読んで **そのマイルストーン固有の確認項目** を動的に生成すること。

## Steps

### 1. コンテキスト収集（Read ツールで全部読む）

以下を順番に読む:

1. `tasks/milestones.json` — 完了したマイルストーンのタスク一覧を把握する
2. `SSOT.md` — §0 設計原則、§1 絶対ルール、§2 環境スタック、GOチェックリストを把握する
3. `runtime/reports/REPORT_LATEST.md` — 実際に何が変更されたかを把握する
4. `runtime/runs/latest.json` — `milestone_completed` の `milestone_id` を確認する
5. Glob で `runtime/reports/*.md` の最新3件を読んで実装内容の全体像を把握する

### 2. チェック項目を設計する（生成前に考える）

読んだ内容をもとに、以下のカテゴリで確認項目を設計する:

**A. 機能動作確認**
- このマイルストーンで実装した機能を実際に動かして確認する項目
- コマンド・操作手順が具体的であること（「pytest を実行する」ではなく `python -m pytest tests/xxx/ -v` のように）

**B. SSOT §1 絶対ルール準拠確認**
- プロジェクト固有のルール（SSOT.md §1 から抽出）が守られているか

**C. 品質確認**
- テストが通っているか
- エラーハンドリングはあるか
- ドキュメントは更新されているか（必要な場合）

**D. 次フェーズへの準備確認**
- 次のマイルストーンに進む前提条件が揃っているか

### 3. HTML を生成する

以下の仕様で `runtime/reports/MANUAL_CHECK_{milestone_id}.html` を Write で作成する。

**HTML 仕様:**
- 完全な自己完結 HTML（外部CSS不要）
- ダークテーマ（`#0f1117` 背景、`#e2e8f0` テキスト、`#7c8cff` アクセント）
- 印刷可能なチェックボックス付きリスト
- 全確認項目にチェックボックス（`<input type="checkbox">`）を付ける
- コマンドはコードブロックで表示（コピーしやすく）
- 最後に「全項目確認済み → make loop-run で次フェーズへ」ボタン

**HTML 構造:**
```
<header> タイトル + マイルストーン情報 + 生成日時
<section id="summary"> 実装サマリ（完了タスク一覧）
<section id="functional"> A. 機能動作確認（チェックボックス）
<section id="ssot"> B. SSOT 絶対ルール準拠確認（チェックボックス）
<section id="quality"> C. 品質確認（チェックボックス）
<section id="next"> D. 次フェーズへの準備確認（チェックボックス）
<footer> 全確認済みボタン + make loop-run コマンド
```

## Outputs

- `runtime/reports/MANUAL_CHECK_{milestone_id}.html`（Write で作成済み）
- パスをユーザーに伝える（ブラウザで開くよう案内する）

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| milestone_id がわからない | latest.json に `milestone_completed` がない | milestones.json の全done Mを探す |
| SSOT に GOチェックリストがない | プロジェクト固有設定未済み | §1 絶対ルールからチェック項目を抽出する |
| チェック項目が汎用的すぎる | コンテキスト読み込み不足 | REPORT ファイルを追加で読んで実装内容を把握する |
