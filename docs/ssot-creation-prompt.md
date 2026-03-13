# 新PJ用 SSOT作成プロンプト

このファイルは、このテンプレートリポジトリを新プロジェクトに適用する際に
Claude に渡すプロンプトのひな型です。

---

## 使い方

1. このリポジトリをクローンまたはテンプレートとして複製する
2. 下記プロンプトの `[...]` をPJ情報に書き換えて Claude に貼り付ける
3. Claude が SSOT.md と CLAUDE.md を新PJ用に書き換える
4. `make setup` → `make loop-start` でループ開始

---

## 【プロンプト本文】新PJ SSOT初期化

```
あなたはAI Orchestrator Loop テンプレートをセットアップするアシスタントです。

以下のPJ情報を元に、SSOT.md と CLAUDE.md を新PJ用に書き換えてください。

## PJ情報

- PJ名: [例: my-saas-api]
- 説明: [例: FastAPIベースのSaaS向けバックエンドAPI]
- 主な開発言語/フレーム: [例: Python 3.12 / FastAPI / PostgreSQL]
- 主要タスク（箇条書き）:
  - [例: DBスキーマ設計]
  - [例: 認証API実装]
  - [例: テスト自動化]
- チーム人数（Claudeが並走するか）: [例: 1人（Claude単独）]
- 禁止操作（プロジェクト固有）:
  - [例: 本番DBへの直接write]
  - [例: secrets/以下のファイル編集]

## 実行してほしいこと

### Step 1: 現状把握
1. 現在の SSOT.md を Read する
2. 現在の CLAUDE.md を Read する
3. tasks/milestones.json を Read する

### Step 2: SSOT.md の書き換え
以下のセクションをPJ固有内容に更新する（構造は変えない）:
- §0 設計原則: PJ名・説明を冒頭に追記
- §1 絶対ルール: PJ固有の禁止操作を追加
- §2 環境スタック: 言語/フレームワークを記載
- §8 GOチェックリスト: PJ固有のGOチェック項目を追加

⚠️ SSOT.md は通常ループ中は書き込み禁止。この初期化作業は手動セットアップフェーズとして実施。

### Step 3: CLAUDE.md の書き換え
- 「このリポジトリについて」セクションをPJ固有説明に変更
- 200行以内に収める

### Step 4: milestones.json の初期化
tasks/milestones.json をPJのフェーズ/タスクに合わせて書き換える。
以下のフォーマットを維持すること:
- M1: Phase 1（環境セットアップ）は必ず残す
- 各タスクに id, title, status: "pending" を設定

### Step 5: 初期化確認
- `make setup` を実行してハッシュを更新する
- GOチェックリスト §8 を1項目ずつ確認する
- runtime/reports/REPORT_LATEST.md に初期化レポートを書く

## 完了条件
- [ ] SSOT.md がPJ固有内容になっている
- [ ] CLAUDE.md がPJ固有内容になっており200行以内
- [ ] milestones.json にPJのタスクが入っている
- [ ] `make setup` が正常完了している
- [ ] REPORT_LATEST.md に decision: written_by_claude が記録されている
```

---

## カスタマイズのヒント

| セクション | 変更が必要な場合 |
|-----------|----------------|
| §1 絶対ルール | PJで触ってはいけないファイルがある場合に追加 |
| §2 環境スタック | 特定バージョンのNodeやDockerが必要な場合 |
| §8 GOチェック | テストや lint のパスをGO条件にしたい場合 |
| policy/policy.json | report_fields_required を変更したい場合 |

## 注意事項

- SSOT.md を一度 `make setup` でハッシュ登録したら、以降はループ中の自動編集不可
- 変更が必要になった場合は手動で編集し `make setup` を再実行する
- CLAUDE.md は 200行制限（PostToolUseフックで警告）
