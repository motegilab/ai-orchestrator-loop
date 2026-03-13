# 初期セットアップガイド

このガイドは、`ai-orchestrator-loop-claude` テンプレートを使って
新しいプロジェクトを立ち上げるための手順書です。

対象読者: このテンプレートを初めて使う開発者

---

## 前提条件

以下のツールが事前にインストールされている必要があります。

| ツール | 必要バージョン | インストール方法 |
|--------|--------------|----------------|
| Python | 3.9 以上 | https://python.org |
| Claude Code CLI | v2.0 以上 | `npm install -g @anthropic-ai/claude-code` |
| Git | 任意 | https://git-scm.com |
| make | 任意 | Windows: `choco install make` または Git Bash 付属 |

確認コマンド:

```bash
python --version
claude --version
git --version
make --version
```

---

## Step 1: テンプレートからリポジトリを作成する

### GitHub UI から使う場合

1. [ai-orchestrator-loop-claude](https://github.com/motegilab/ai-orchestrator-loop-claude) を開く
2. `Use this template` ボタンをクリック
3. 新しいリポジトリ名を入力して作成
4. 作成されたリポジトリをクローンする

```bash
git clone https://github.com/YOUR_ORG/YOUR_REPO.git
cd YOUR_REPO
```

### gh CLI から使う場合

```bash
gh repo create my-new-project \
  --template motegilab/ai-orchestrator-loop-claude \
  --private \
  --clone

cd my-new-project
```

---

## Step 2: 自動セットアップを実行する

`auto_setup.py` を実行すると、前提条件チェック・通知設定・環境確認をまとめて行えます。

```bash
python tools/scripts/auto_setup.py
```

スクリプトは以下の順番で処理します:

1. **前提条件チェック**: python / claude / make の存在を確認
2. **通知設定**: `notifications.json` を作成して Discord Webhook URL を設定（任意）
3. **環境セットアップ**: `make setup` を実行して SSOT ハッシュを登録
4. **GOチェックリスト確認**: 9 項目すべてが PASS かどうかを表示

確認のみ実行したい場合（変更なし）:

```bash
python tools/scripts/auto_setup.py --check
```

---

## Step 3: Discord 通知を設定する（任意）

ループの開始・完了を Discord に通知したい場合は `notifications.json` を設定します。

`auto_setup.py` 実行中に URL を入力するか、手動でファイルを編集します:

```bash
cp notifications.json.example notifications.json
# notifications.json を開いて webhook_url と enabled を設定する
```

`notifications.json` の例:

```json
{
  "discord": {
    "enabled": true,
    "webhook_url": "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN",
    "notify_on": ["stop"],
    "mention_role_id": ""
  }
}
```

> `notifications.json` は `.gitignore` で除外されているため、リポジトリには含まれません。

---

## Step 4: SSOT.md と CLAUDE.md をプロジェクト固有の内容に書き換える

テンプレートの `SSOT.md` と `CLAUDE.md` は汎用的な内容になっています。
これをあなたのプロジェクト固有の内容に書き換えます。

`docs/ssot-creation-prompt.md` に Claude に渡すプロンプトのひな型があります。

1. `docs/ssot-creation-prompt.md` を開く
2. `[...]` の部分をプロジェクト情報に書き換える
3. Claude に貼り付けて実行する

書き換え後、`make setup` を再実行してハッシュを更新します:

```bash
make setup
```

> `make setup` を実行しないと SSOT ゲートが古いハッシュでブロックします。

---

## Step 5: tasks/milestones.json を初期化する

`tasks/milestones.json` にプロジェクトのマイルストーンとタスクを定義します。

既存の内容を参考に、以下の構造でプロジェクト固有のタスクを記述します:

```json
{
  "milestones": [
    {
      "id": "M1",
      "title": "Phase 1: 初期セットアップ",
      "status": "pending",
      "waves": [
        {
          "id": "W1-1",
          "title": "環境構築",
          "tasks": [
            {
              "id": "T1",
              "title": "最初のタスク",
              "status": "pending"
            }
          ]
        }
      ]
    }
  ]
}
```

---

## Step 6: 最初のループを起動する

```bash
make loop-start
```

初回起動時は `docs/FIRST_PROMPT.md` の内容が Claude に渡されます。
2 回目以降は前回セッション終了時に自動生成された `runtime/logs/next_session.md` が使われます。

---

## ループで何が起きるか

`make loop-start` を実行すると、以下のサイクルが自動で動作します:

```
SessionStart Hook
  ↓ audit_log.jsonl にセッション境界マーカーを書き込む
  ↓ REPORT_LATEST.md をテンプレート状態にリセット
  ↓ next_session.md の内容を Claude に注入する

Claude セッション（Observe → Patch → Verify → Report）
  ↓ observe Skill: 問題・タスクを調査する
  ↓ patch Skill: 最小差分で修正する
  ↓ verify Skill: exit code と stdout を確認する
  ↓ report Skill: REPORT_LATEST.md に結果を記録する

Stop Hook (on_stop.py)
  ↓ REPORT_LATEST.md を検査（Claude が書いたか確認）
  ↓ milestones.json から次の pending タスクを特定
  ↓ next_session.md を生成（次ループへの指示）
  ↓ runtime/runs/YYYY-MM-DD_runNNN.json を保存
  ↓ Discord 通知を送信（設定している場合）
```

次回の `make loop-start` では、前回生成された `next_session.md` が
自動的に Claude のコンテキストに注入され、ループが継続します。

---

## 確認コマンド

```bash
make loop-status   # 現在の状態を確認する
make loop-start    # 次のループを開始する
make loop-stop     # ループを停止する
```

---

## トラブルシューティング

### `claude: command not found`

Claude Code CLI がインストールされていません:

```bash
npm install -g @anthropic-ai/claude-code
claude --version
```

### `make setup` が失敗する

Python スクリプトが直接実行できます:

```bash
python tools/scripts/setup.py
```

### Stop Hook が発火しない / run が作成されない

`make loop-start` は VSCode 拡張機能のターミナル **外** から実行してください。
VSCode の Claude Code セッション内からサブプロセスとして起動すると、
Stop Hook が正常に発火しない場合があります。

別のターミナル（PowerShell / Git Bash）から実行することを推奨します。

### SSOT.md を編集しようとしたらブロックされた

これは正常な動作です。`SSOT.md` と `policy/ssot_integrity.json` は
ループ中の自動編集が禁止されています。
変更が必要な場合は手動で編集してから `make setup` を再実行してください。

---

## 関連ドキュメント

- [SSOT.md](../SSOT.md) — 設計の正本
- [CLAUDE.md](../CLAUDE.md) — Claude へのワークフロー指示
- [docs/ssot-creation-prompt.md](ssot-creation-prompt.md) — 新PJ SSOT初期化プロンプト
- [docs/github-template-setup.md](github-template-setup.md) — GitHub Template 設定手順
- [docs/FIRST_PROMPT.md](FIRST_PROMPT.md) — 初回セッション用プロンプト
