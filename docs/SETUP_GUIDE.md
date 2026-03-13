# 人間がやるセットアップガイド

> これだけやれば環境が整う。所要時間: 約30分。

---

## 事前に決めておくこと（チェックリスト）

- [ ] **GitHubアカウント** — 組織アカウントかパーソナルか決める
- [ ] **リポジトリ名** — 例: `ai-orchestrator-loop` または `claude-orch`
- [ ] **ローカル作業ディレクトリ** — 例: `~/Projects/` または `D:\Projects\`
- [ ] **Claude Codeのサブスクリプション** — Max以上推奨（Hooksはループが多いとトークン消費大）
- [ ] **最初にやらせるPJのテーマ** — テンプレートに記載するため

---

## STEP 1: ローカル環境の準備

### 1-1. Claude Code CLI インストール

```bash
npm install -g @anthropic-ai/claude-code
claude --version
# v2.0以上であることを確認
```

### 1-2. Gitの確認

```bash
git --version
gh --version   # GitHub CLI（推奨・なければ後でインストール）
```

### 1-3. Pythonの確認

```bash
python3 --version
# 3.9以上であることを確認
```

---

## STEP 2: GitHubリポジトリ作成

### 方法A: GitHub CLI（推奨）

```bash
# このリポジトリをテンプレートとして新規作成
gh repo create ai-orchestrator-loop \
  --private \
  --clone \
  --description "Claude-first AI Orchestrator Loop"
cd ai-orchestrator-loop
```

### 方法B: GitHub Web UI

1. GitHub.com → New repository
2. "Template repository" にチェックを入れる（後で他PJの元にするため）
3. 作成後に `git clone` する

---

## STEP 3: ファイルをリポジトリに配置

このZIPの中身をそのままリポジトリにコピーする：

```
ai-orchestrator-loop/
├── SSOT.md
├── CLAUDE.md
├── README.md
├── Makefile
├── .gitignore
├── .claude/
│   ├── settings.json
│   ├── hooks/
│   └── skills/
├── policy/
├── tasks/
└── docs/
```

---

## STEP 4: SSOTのHash初期化（必須）

```bash
cd ai-orchestrator-loop
python .claude/hooks/ssot_gate.py --update-hash
# ✅ Hash updated と表示されればOK
```

---

## STEP 5: Gitにコミット

```bash
git add .
git commit -m "初期セットアップ: Claude-first AI Orchestrator Loop v1.0"
git push origin main
```

---

## STEP 6: Google Drive連携（任意）

runtime/ フォルダをGoogle Driveと同期したい場合：

1. Google Drive for Desktop をインストール
2. runtime/ を `~/Google Drive/My Drive/ai-orch-runtime/` にシンボリックリンク：
   ```bash
   # Mac/Linux
   ln -s ~/Library/CloudStorage/GoogleDrive-xxx/My\ Drive/ai-orch-runtime/ runtime
   
   # Windows（管理者PowerShellで）
   mklink /D runtime "G:\マイドライブ\ai-orch-runtime"
   ```
3. .gitignore の `runtime/**` はそのまま残す（Driveは別管理）

---

## STEP 7: 初回ループ起動

```bash
make loop-start
```

Claude Codeが起動し、docs/FIRST_PROMPT.md の内容に従って
自動的にGOチェックリストを実行します。

---

## グローバルSkillsの設定（推奨）

全PJで共通のSkillsをグローバルに配置する：

```bash
# ~/.claude/skills/ に各Skillをコピー
mkdir -p ~/.claude/skills
cp -r .claude/skills/observe ~/.claude/skills/
cp -r .claude/skills/patch ~/.claude/skills/
cp -r .claude/skills/verify ~/.claude/skills/
cp -r .claude/skills/report ~/.claude/skills/
```

---

## 新PJへの適用方法

```bash
# 1. このリポジトリをテンプレートに設定（初回のみ）
gh repo edit ai-orchestrator-loop --template

# 2. 新PJを作成
gh repo create my-new-project --template motegilab/ai-orchestrator-loop-claude --clone
cd my-new-project

# 3. PJ固有設定を書き換える
#    CLAUDE.md の「== PJ固有設定 ==」セクション
#    SSOT.md の §8 の内容

# 4. Hash更新
python .claude/hooks/ssot_gate.py --update-hash

# 5. スタート
make loop-start
```

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| `claude: command not found` | `npm install -g @anthropic-ai/claude-code` を再実行 |
| `python: command not found` | `python3` に置き換えるか、エイリアスを設定する |
| Hook が動かない | `.claude/settings.json` の構文を確認。`/hooks` でClaude Code内から確認できる |
| SSOT gate が常にブロック | `python .claude/hooks/ssot_gate.py --update-hash` を再実行 |
| runtime/ が git に入ってしまう | `.gitignore` に `runtime/**` があるか確認 |
