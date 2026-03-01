NS_ID: NS_AI_ORCHESTRATOR_LOOP_SSOT_FIRST
ROLE: Orchestrator と Codex の SSOT-First 強制ルール。必ず読んでから実行する。

# SSOT-First 強制ルール（最重要）

参照: [I stopped writing E2E tests manually — I manage an AI agent instead](https://engineering.instawork.com/i-stopped-writing-e2e-tests-manually-i-manage-an-ai-agent-instead-e6acb44019e2)  
思想: 「テストを書く」より「エージェントを管理する」＝運用の設計勝負。SSOT を読まずに動かない。

---

## 層A: Orchestrator 側（機械の強制）

- `config.yaml` で `ssot_path` を必須指定する（例: `rules/SSOT_AI_Orchestrator_Loop.md`）。ワークスペースルートからの相対パス。
- `planner.py` は毎回 `ssot_path` を読み込み、`next_prompt.md` の**冒頭**に以下を必ず出力する。

### SSOT CHECK（必須）

1. **SSOT からの抜粋** — 今回の作業に関係する箇所を最大 15 行
2. **SSOT の禁止事項** — "MUST NOT" / "禁止" を箇条書きで抽出
3. **今回の作業のスコープ** — SSOT に照らした範囲宣言
4. **SSOT に反しうる点** — 1 つでもあれば `status=blocked` にし、提案だけ書いて実行相当の指示を出さない

- **SSOT が読めない場合**（空・パス不正・ファイルなし）:
  - run ログの `status` を `blocked` にする
  - `next_prompt.md` に「SSOT が読めないので停止」と明記する
  - **解除手順（1行）を同じ next_prompt.md に書く**  
    例: 「解除手順: config.yaml の ssot_path を正す → make orch-post で再生成」

---

## 層B: Codex への命令（人間のルール）

- Codex は **「SSOT を読んだ事実（引用または要約）」を出力してから** 作業開始する。
- **SSOT に反する変更は禁止**。反しそうなら提案に止め、実行しない。
- next_prompt.md の **SSOT CHECK** を無視しない。冒頭の抜粋・禁止事項・スコープを守る。

---

## 禁止事項（SSOT から抽出する例）

- CLI 自動投入は禁止（v1）
- ネット権限ゼロ前提
- SSOT 文書は基本変更しない
- make orch-run-next は Codex/Cursor から実行しない（ブロック済み）
