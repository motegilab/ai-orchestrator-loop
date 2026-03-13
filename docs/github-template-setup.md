# GitHub Template リポジトリ設定手順

このリポジトリを GitHub Template Repository として公開するための手順。

---

## Step 1: GitHubにプッシュ

```bash
# GitHubで空のリポジトリを作成（README なし）してから:
git remote add origin https://github.com/motegilab/ai-orchestrator-loop-claude.git
git branch -M main
git push -u origin main
```

## Step 2: Template Repository として設定（GitHub UI）

1. GitHub リポジトリページを開く
2. **Settings** タブをクリック
3. **General** セクションの最上部
4. "**Template repository**" にチェックを入れる
5. Save

これで `Use this template` ボタンがリポジトリページに表示される。

---

## Step 3: 使い方（ユーザー向け）

### GitHub UI から使う

1. リポジトリページの `Use this template` ボタンをクリック
2. 新リポジトリ名を入力して作成
3. クローンして `make setup` → `make loop-start`

### gh CLI から使う

```bash
gh repo create my-new-project \
  --template motegilab/ai-orchestrator-loop-claude \
  --private \
  --clone

cd my-new-project
make setup
make loop-start
```

---

## Step 4: 新PJ初期化（テンプレート適用後）

テンプレートを使って新PJを作成したら、`docs/ssot-creation-prompt.md` のプロンプトを使って
Claude に SSOT.md / CLAUDE.md を新PJ用に書き換えてもらう。

```bash
# ループ起動後、以下のプロンプトを使う:
# → docs/ssot-creation-prompt.md の「プロンプト本文」を参照
make loop-start
```

---

## チェックリスト（公開前）

- [x] `git remote add origin` 設定済み
- [x] `git push -u origin main` 実行済み
- [x] GitHub Settings → Template repository にチェック
- [x] README.md の `YOUR_ORG` を実際のGitHub組織名/ユーザー名に修正（motegilab）
- [x] legacy/ が .gitignore で除外されている（`git ls-files legacy/` が空であること）
- [x] runtime/ が .gitignore で除外されている（`git ls-files runtime/` が空であること）
- [x] secrets やトークンが含まれていないこと（`git grep` のヒットはドキュメントの説明文のみ）

---

## README の YOUR_ORG 修正

[README.md](../README.md) は **motegilab** / **ai-orchestrator-loop-claude** に合わせて修正済み。

```md
# 現在の記載
git clone https://github.com/motegilab/ai-orchestrator-loop-claude.git
gh repo create my-new-project --template motegilab/ai-orchestrator-loop-claude
```
