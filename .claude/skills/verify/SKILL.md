---
name: verify
description: 変更後の検証を行うSkill。patch Skillの後、「確認して」「テストして」「動くか確認」と言われた時に自動invokeする。
allowed-tools: "Bash, Read"
metadata:
  version: 1.1.0
---

# Verify Skill

## MUST READ FIRST
1. patch Skillの出力（verify_commands）

## Steps
1. verify_commands を Bash で実行する（patch が指定したコマンドを優先）
2. patch が verify_commands を指定していない場合は `python tools/scripts/loop_status.py` を実行する
3. exit code を記録する（0=success, それ以外=fail）
4. stdout/stderr の重要部分を記録する（Bash ツールの出力をそのまま引用）
5. 成功/失敗を判定して report Skill に引き継ぐ

## デフォルト検証コマンド（patch が未指定の場合）
```
python tools/scripts/loop_status.py
python .claude/hooks/ssot_gate.py --update-hash
```

## Outputs
- verify_commands: 実行したコマンド一覧
- exit_codes: 各コマンドの終了コード
- stdout_tail: 標準出力（Bash ツール出力から引用）
- evidence_paths: ログファイルのパス

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| コマンドが存在しない | 環境差異 | `python tools/scripts/loop_status.py` を代替として使う |
| タイムアウト | 処理が長い | failed として記録。成功扱いにしない（§1絶対ルール） |
| `tail`/`head` が使えない（Windows） | コマンド未対応 | Bash ツールの出力をそのまま記録する |
