NS_ID: NS_AI_ORCHESTRATOR_LOOP_SSOT
ROLE: AI Orchestrator Loop の設計・実装の SSOT。v1 Phase1-2 はこの仕様で確定。PROMPT_1_GO版 とセットで Codex に投げる。

# SSOT: AI Orchestrator Loop

最終更新: 2026-02-18
バージョン: 2.0（GO版準拠）

---

## 0. 設計原則

- **汎用性**: 特定の親リポジトリに依存しない。任意の Cursor ワークスペース（Unity / GAS / NSS 等）で動く
- **v1 の範囲**: Phase1-2 のみ。CLI 自動投入は禁止（例外: `make orch-run-next-local` のみ許可）。next_prompt.md 出力まででループ成立
- **役割分担**: コード実装は Cursor 内の Codex CLI。ネット権限ゼロ前提
- **哲学**: Human Tool（arxiv 2602.12953）— AI がワークフロー主導
- **SSOT-First**: 必ず SSOT を読んでから実行する。詳細は `rules/SSOT_FIRST_Orchestrator.md`

---

## 1. v1 絶対ルール

- **CLI 自動投入（Codex/Cursor 起動）は禁止**。next_prompt.md 出力まで。
- ネット権限ゼロ（外部 API / 検索なし）
- 1 回の Webhook 処理は「保存・要約・次プロンプト生成」だけ。大規模改修しない
- 監査ログが真実。SSOT 文書は基本変更しない

### 1.1 例外（v1 実行入口）

- 許可される実行入口は `make orch-run-next-local` のみ
- `SSOT CHECK` gate を必須とし、`blocked` はループ停止
- 自動ループ中に SSOT 文書を編集しない（SSOT 更新は手動のみ）
- 監査生成物 `runs/latest.json` と `REPORT_LATEST.md` を保持・更新する
- 修正スコープは最小差分（1 原因 1 修正）を厳守する
- タイムアウト時は `failed` と evidence を記録し、成功扱いにしない

## External Runner Interface (Phase1-2: observe-only)

- Canonical state file は `tools/orchestrator_runtime/state/loop_state.json` とする
- 外部 runner（OpenClaw/NanoClaw）は v1 では observe-only + notify-only
- v1 で許可される runner 動作:
  - `loop_state.json` と `tools/orchestrator_runtime/reports/REPORT_LATEST.md` の read
  - 状態通知（signal/webhook）まで
- v1 禁止事項:
  - **NO auto Codex start**
  - Codex 実行・編集コマンドの自動投入
- Phase2 gating:
  - auto-start は SSOT amendment で明示的に有効化されるまで禁止
- Required evidence:
  - runner の判断は毎回 `loop_state.json` と `REPORT_LATEST.md` の両方を根拠にする
- Security:
  - runner は分離実行を必須とする
  - command allowlist を持つ場合、entrypoint は単一に固定する

---

## 2. 配置ポリシー（v1 決め打ち）

| 用途 | パス | Git |
|------|------|-----|
| 実装本体 | `tools/orchestrator/` | 管理する |
| 実行生成物 | `tools/orchestrator_runtime/` | **全除外** |

- 将来 `~/.ai-orchestrator/` に丸ごと移せる構造にする
- `tools/orchestrator_runtime/**` は `.gitignore` で丸ごと除外

### 2.1 固定ディレクトリ

```
tools/
├── orchestrator/
│   ├── README.md
│   ├── server.py
│   ├── normalize.py
│   ├── planner.py
│   ├── log.py
│   ├── ssot.py
│   └── config.example.yaml
└── orchestrator_runtime/
    ├── runs/
    │   ├── latest.json
    │   └── YYYY-MM-DD_runNNN.json
    ├── artifacts/
    │   ├── webhooks/
    │   ├── summaries/
    │   └── diffs/
    ├── unity_logs/
    ├── gas_logs/
    └── logs/
        └── next_prompt.md
```

### 2.2 ファイル置き場（v1固定）

- `rules/`：SSOT / 憲法ドキュメントのみ（設計の正本）
- `tools/orchestrator/`：実装コードのみ
- `tools/orchestrator_runtime/`：実行生成物のみ（git 管理外）
- `docs/`：任意の補助ドキュメント
- 上記以外に置かれたファイルは **stray** とみなし、清掃対象とする

### 2.3 清掃（Cleanroom）手順

- **監査（定期）**: stray ファイルを列挙する（削除しない）
- **適用（手動）**: stray を `tools/orchestrator_runtime/artifacts/cleanup/YYYY-MM-DD/` へ移動  
  （削除は人間承認後のみ実施）
- 清掃は自動ループ内で実行しない。必ず手動運用で実施する

---

## 3. .gitignore（必須）

```
tools/orchestrator_runtime/**
```

---

## 4. サーバ要件

- `127.0.0.1:8765` で起動（設定で変更可）
- `POST /webhook`：payload 受信
- `GET /health`：200 OK

### 4.1 Webhook 受信時の必須動作（順番固定）

1. payload をそのまま保存  
   → `tools/orchestrator_runtime/artifacts/webhooks/<timestamp>_<shortid>.json`
2. payload を正規化して run ログ作成  
   → `tools/orchestrator_runtime/runs/YYYY-MM-DD_runNNN.json`  
   → `tools/orchestrator_runtime/runs/latest.json` を更新
3. planner で next_prompt.md を生成・保存（毎回上書き）  
   → `tools/orchestrator_runtime/logs/next_prompt.md`
4. report を生成・保存（毎回上書き）  
   → `tools/orchestrator_runtime/reports/REPORT_LATEST.md`

### 4.2 report 生成の信頼性ルール（必須）

- report 生成は失敗しうるが、**失敗を無記録で終わらせてはならない**
- report 失敗時は `runs/latest.json` に以下を必ず記録する:
  - `report_status`（`success` / `failed`）
  - `report_path`（書けた場合のみ。未生成なら空または省略可）
  - `report_error`（短い要約）
- `REPORT_LATEST.md` が書けない場合は  
  `tools/orchestrator_runtime/reports/REPORT_FAILED.md` を生成し、以下を記載する:
  - `run_id`
  - error summary
  - next action（`restart server / rerun orch-report`）

---

## 5. 正規化フォーマット（runs/*.json 必須項目）

- `run_id`（日付+連番）
- `event_id`
- `received_at`
- `source`（cursor）
- `intent`（推定可: task_completed / task_failed / status_update 等）
- `summary`（短文）
- `status`（success / failed / blocked）
- `top_errors`（最大 5。失敗時のみ）
- `evidence_paths`（保存した payload やログのパス）
- `next_prompt_path`（next_prompt.md へのパス）

### 5.1 report 失敗時の追加フィールド

- `report_status`（`success` / `failed`）
- `report_path`（生成済みレポートがある場合）
- `report_error`（失敗時の短い要約）

### 5.2 外部監査テキストの取り込み

- 新しい artifact 種別:  
  `tools/orchestrator_runtime/artifacts/audits/<timestamp>_audit.md`
- 人間が貼り付けた手動監査/報告テキストは必ず上記へ保存する
- 保存した監査テキストのパスは `evidence_paths` に必ず追加する
- v1 の手動入口名（仕様のみ）: `make orch-audit`  
  （監査テキストを保存し、現在の `run_id` に紐付ける）

---

## 6. next_prompt.md テンプレ（必須）

常に以下のセクションを含める:

- **DONE**: ここまでやった（今回イベント＋直近 run 要約）
- **NEXT**: 次にやること（推奨手順）
- **FAIL**: ここで落ちた（失敗時のみ。エラー抜粋）
- **FIX**: 推論して直して（最小差分・禁止範囲・1 原因 1 修正）
- **VERIFY**: 再検証（例: make smoke / probe / verify など候補提示）

---

## 7. ワークスペース

- v1 は単一 workspace 固定
- `config.yaml` に `workspace_root` を持たせる。README に設定例を書く
- 将来の registry は設計だけ。実装は不要

---

## 8. テスト手順（README 必須）

1. サーバ起動
2. curl で POST
3. 以下を確認:
   - webhooks 保存
   - runs/latest.json 生成
   - logs/next_prompt.md 生成

---

## 9. 実装言語・例外

- Python（標準ライブラリ優先）
- 例外が起きても runs/latest.json と next_prompt.md の生成を極力落とさない（最低限エラーレポを残す）

---

## 10. Phase1-2 達成

- 上記がローカルで動作する
- README が揃っている
- `tools/orchestrator_runtime/**` が git に乗らない

---

## 11. GO チェックリスト

実装後、以下を確認:

- [ ] `tools/orchestrator_runtime/` が git 管理外
- [ ] `python tools/orchestrator/server.py` で起動できる
- [ ] `GET /health` が 200
- [ ] `POST /webhook` で webhooks 保存・runs/latest.json 更新・logs/next_prompt.md 生成
- [ ] next_prompt.md が DONE/NEXT/FAIL/FIX/VERIFY を必ず含む

---

## 12. 起動方法・入口（make）

- **ユーザーが叩くのは make だけ**。PowerShell は make の裏で使う（例: make orch-setup が内部で ps1 を呼ぶ）。入口を 1 個に固定する。
- 入口は **make** に統一する（cmd.exe / PowerShell 混在を避ける）。

| ターゲット | 動作 | 要件 |
|------------|------|------|
| make orch-start | サーバ起動（フォアグラウンド） | Python |
| make orch-start-bg | サーバ起動（バックグラウンド） | Python |
| make orch-health | health 確認 | Python、サーバ起動済み |
| make orch-post | テスト POST 送信 | Python、サーバ起動済み |
| make orch-setup | Hooks 環境設定一括 | PowerShell |
| make orch-doctor | 環境チェック | Python |
| make orch-run-next | ブロック済み（Codex/Cursor からは実行不可） | - |
| make orch-run-next-local | 実機ターミナル専用。next_prompt.md の NEXT を Codex CLI で実行 | Codex CLI |

- orch-health, orch-post は Python 標準ライブラリのみで実装（PowerShell 不要、cmd.exe で動作）
- orch-run-next は exit 2 でガード。実機では orch-run-next-local が run_next.txt を codex exec に渡す
- 詳細は `tools/orchestrator/README.md` 参照

**Codex に投げるもの**: `NEXT_ACTION.md`（Prompt Router）の MODE に応じた「Codex に貼るブロック」のみ。プロンプトファイルは増やさない。

---

## 13. 参照リンク

- [Human Tool (arxiv 2602.12953)](https://arxiv.org/html/2602.12953v1)
- [Cursor Webhook](https://cursor.com/ja/docs/cloud-agent/api/webhooks)

---

## 14. Files-as-Memory Scaffold（最小拡張）

- v1 の補助記憶として、以下の静的ファイルを許可する:
  - `tasks/milestones.json`（milestone > wave > task の進行記憶）
  - `prompts/planner.md`, `prompts/builder.md`, `prompts/verifier.md`（役割分離）
  - `docs/architecture.md`, `docs/quality.md`（構造/品質ポリシー）
- 原則は **files-as-memory**: 状態管理は上記ファイルと監査生成物の組み合わせで行う。
- この拡張は並列実行・worktree 導入を含まない（将来拡張は別 amendment）。
- 既存の SSOT/Policy/Report ループを優先し、矛盾時は SSOT を正とする。
