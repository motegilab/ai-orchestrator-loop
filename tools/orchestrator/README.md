# AI Orchestrator Loop v1 (Phase1-2)

This module runs a local webhook receiver that:

1. Saves raw webhook payloads
2. Normalizes payloads into audit run logs
3. Generates `next_prompt.md`

v1 scope ends at prompt generation. It does not launch Codex/Cursor CLI.

## Directory Layout

```
tools/
├── orchestrator/
│   ├── README.md
│   ├── server.py
│   ├── normalize.py
│   ├── planner.py
│   ├── log.py
│   ├── ssot.py
│   ├── config.example.yaml
│   └── scripts/
│       ├── run.ps1
│       ├── health.ps1
│       ├── post_event.ps1
│       └── setup.ps1
│   └── prompts/
│       └── run_next.txt
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

`tools/orchestrator_runtime/**` must stay out of git.

## Configuration

Copy `tools/orchestrator/config.example.yaml` to `tools/orchestrator/config.yaml` and edit values.

Supported keys:

- `host` (default `127.0.0.1`)
- `port` (default `8765`)
- `workspace_root` (default repository root)
- `runtime_root` (default `<workspace_root>/tools/orchestrator_runtime`)
- `source` (default `cursor`)

The YAML parser is intentionally simple and supports top-level `key: value` entries.

## Run

From workspace root:

```bash
python tools/orchestrator/server.py
```

Expected startup endpoint:

- `GET /health`
- `POST /webhook`

## Test Procedure (Required)

1. Start server:

```bash
python tools/orchestrator/server.py
```

2. In another terminal, call health:

```bash
curl -X GET http://127.0.0.1:8765/health
```

3. Post a sample webhook:

```bash
curl -X POST http://127.0.0.1:8765/webhook \
  -H "Content-Type: application/json" \
  -d "{\"event_id\":\"evt-001\",\"status\":\"failed\",\"summary\":\"Build failed\",\"errors\":[\"module import error\"]}"
```

4. Verify outputs:

- Raw payload exists in `tools/orchestrator_runtime/artifacts/webhooks/`
- `tools/orchestrator_runtime/runs/latest.json` exists and includes normalized fields
- `tools/orchestrator_runtime/logs/next_prompt.md` exists and contains `DONE/NEXT/FAIL/FIX/VERIFY`

## PowerShell (Hooks ローカル運用)

Windows + PowerShell (`pwsh`) での最短手順です。

1. 起動:

```powershell
pwsh -ExecutionPolicy Bypass -File tools/orchestrator/scripts/run.ps1
```

2. 手動ヘルス:

```powershell
pwsh -ExecutionPolicy Bypass -File tools/orchestrator/scripts/health.ps1
```

3. 手動POSTテスト:

```powershell
pwsh -ExecutionPolicy Bypass -File tools/orchestrator/scripts/post_event.ps1 -Message "hello"
```

4. 生成物の場所:

- `tools/orchestrator_runtime/runs/latest.json`
- `tools/orchestrator_runtime/logs/next_prompt.md`

5. Cursor Hooks 設定例:

- `Settings > Plugins > Hooks` を開く
- 任意の Hook（例: `On Task Completed` / `On Error`）に以下を登録

```powershell
pwsh -ExecutionPolicy Bypass -File tools/orchestrator/scripts/post_event.ps1 -HookName "<hook>" -Message "<something>"
```

## make 入口（推奨）

| ターゲット | 動作 | 要件 |
|------------|------|------|
| make orch-start | サーバ起動（フォアグラウンド） | Python |
| make orch-start-bg | サーバ起動（バックグラウンド） | Python |
| make orch-health | health 確認 | Python、サーバ起動済み |
| make orch-post | テスト POST 送信 | Python、サーバ起動済み |
| make orch-setup | Hooks 環境設定一括 | PowerShell |
| make orch-doctor | 環境チェック | Python |
| make orch-run-next | ブロック済み（Codex/Cursor から実行不可） | - |
| make orch-run-next-local | 実機ターミナル専用。next_prompt.md の NEXT を Codex CLI で実行 | Codex CLI |

orch-health, orch-post は Python のみで動作（PowerShell 不要、cmd.exe 対応）。  
orch-run-next は意図的に exit 2 でブロック。実機では orch-run-next-local を使う。

## 環境設定（手動無し）

1回だけ以下を実行します。

```bash
make orch-setup
```

または（PowerShell 直接）:

```powershell
powershell -ExecutionPolicy Bypass -File tools/orchestrator/scripts/setup.ps1
```

これで以下が自動実行されます。

- `.cursor/hooks.json` の生成/マージ（Hooks 自動登録）
- `tools/orchestrator_runtime/` の必要ディレクトリ作成
- サーバ起動と health 確認
- `post_event.ps1` の初回 POST 送信と `runs/latest.json` / `logs/next_prompt.md` 更新確認

Settings > Hooks での手動画面操作は不要です。

## Hooks 接続テスト

1. Cursor の `Settings > Plugins > Hooks` を開く。
2. 任意の Hook（例: `afterFileEdit`）に次を登録する。  
   `powershell -ExecutionPolicy Bypass -File tools/orchestrator/scripts/post_event.ps1 -HookName afterFileEdit -Message file_edited`
3. 1回エージェント実行後、`tools/orchestrator_runtime/logs/next_prompt.md` の更新時刻が新しくなっていることを確認する。

## 運用ループ

### 1. サーバ起動

```bash
python tools/orchestrator/server.py
```

サーバは既定で `127.0.0.1:8765` を listen します。

### 2. Cursor Background Agent の Webhook URL 設定

- Webhook URL は `http://localhost:8765/webhook` を設定します。
- 同一マシン上で Cursor Agent と Orchestrator が動く場合はこの設定で受信できます。

### 3. localhost 到達性の注意（本番運用）

- Cursor 側実行環境から `localhost:8765` に届かない構成があります。
- その場合は `ngrok` などのトンネルでローカルサーバを一時公開し、公開 URL を Webhook に設定します。
- 例: `ngrok http 8765` で発行された HTTPS URL + `/webhook`

### 4. 半自動ループの流れ

1. Cursor から Webhook 受信
2. `next_prompt.md` 生成
3. 人手で `next_prompt.md` を Codex に貼る
4. Codex がタスク実行
5. 完了時に Cursor Webhook が再送され、次の `next_prompt.md` が生成される
6. 以後ループ

## Notes

- Handler order is fixed: save payload -> normalize+run log -> generate next prompt
- Error handling is fail-soft: it attempts to keep `runs/latest.json` and `next_prompt.md` available
