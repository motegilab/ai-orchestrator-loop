---
name: report
description: セッション結果をレポートするSkill。作業終了時、Stopの直前、「レポートして」「まとめて」と言われた時に自動invokeする。
allowed-tools: "Write, Read"
metadata:
  version: 1.1.0
---

# Report Skill

## Must Read First

1. verify Skill の出力（exit_codes, stdout_tail）
2. 今回セッションで変更したファイル一覧

## ⚠️ on_stop.py との役割分担

| 担当 | 処理 |
|------|------|
| **Claude（このSkill）** | `runtime/reports/REPORT_LATEST.md` を書く |
| **on_stop.py（自動）** | `runtime/runs/latest.json` を生成する |
| **on_stop.py（自動）** | `runtime/logs/next_session.md` を生成する |

→ `latest.json` と `next_session.md` は Claude が書かなくてよい。

## Steps

1. 今回セッションの作業結果をまとめる
2. [レポートテンプレート](references/report-template.md) を Read で確認する
3. テンプレートの `()` を実際の内容で埋めて `runtime/reports/REPORT_LATEST.md` を Write で上書きする
4. PLACEHOLDER_MARKERS が含まれていないことを確認する（含まれると on_stop.py が上書きする）

## Outputs

- `runtime/reports/REPORT_LATEST.md`（Write ツールで書き込み済み）
- `## decision` が `written_by_claude` になっていること

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| on_stop.py がレポートを上書きした | PLACEHOLDER_MARKERS が残っていた | `()` 内を実際の内容で埋め直す |
| Write ツールが拒否された | runtime/ 外のパスを指定した | パスを `runtime/reports/REPORT_LATEST.md` に修正する |
| `decision` が `auto_generated` になった | report Skill を実行しなかった | 次ループ開始前に必ず report Skill を実行する |
