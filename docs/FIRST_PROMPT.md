# 初回セッション用プロンプト

> このファイルを `make loop-start` 前にコピーして使う、または
> 初回のClaudeへのプロンプトとしてそのまま貼り付ける。

---

## 【初回プロンプト】環境セットアップ確認

```
あなたはこのリポジトリのAI Orchestrator（Claude-first版）です。

まず以下を順番に実行してください：

1. SSOT.md を読んで設計原則と絶対ルールを把握する
2. CLAUDE.md を読んでワークフローを把握する
3. tasks/milestones.json を読んで現在のタスク状況を把握する
4. policy/ssot_integrity.json を確認する

次に、SSOT.md §8 の GOチェックリストを1項目ずつ確認してください。
クリアできていない項目があれば、その理由と対処方法を教えてください。

最後に、確認結果をレポートフォーマット（SSOT.md §7）に従って
runtime/reports/REPORT_LATEST.md に書いてください。
```

---

## 【新PJ適用時プロンプト】PJ設定確認

```
新プロジェクト「[PJ名]」の環境をセットアップしています。

1. SSOT.md の §0（設計原則）と §1（絶対ルール）を読む
2. CLAUDE.md の「PJ固有設定」セクションが正しく記述されているか確認する
3. tasks/milestones.json を読んでM1（Phase1）の最初のタスクを特定する
4. GOチェックリスト（SSOT.md §8）のT1.1.x を順番に実行する

問題があれば1原因1修正の原則で対処し、
runtime/reports/REPORT_LATEST.md にレポートを書いてください。
```

---

## 【通常ループ時プロンプト】（make loop-start が自動使用）

```
※ このプロンプトはStop Hook が runtime/logs/next_session.md として自動生成します。
※ 通常は make loop-start を叩くだけで自動的に使われます。
```
