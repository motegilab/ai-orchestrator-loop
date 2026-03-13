---
name: patch
description: 最小差分でファイルを修正するSkill。修正・実装依頼時、observe Skillの結果を受けて修正に入る時、「直して」「実装して」と言われた時に自動invokeする。
allowed-tools: "Read, Edit, Write, MultiEdit, Bash"
metadata:
  version: 1.1.0
---

# Patch Skill

## MUST READ FIRST
1. SSOT.md（§1 絶対ルール）
2. observe Skillの出力（hypothesis_one_cause）

## 鉄則
- 1修正 = 1原因 = 最小ファイル数（通常1〜2ファイル。それ以上はスコープオーバー）
- SSOT.md / policy/ssot_integrity.json / .claude/hooks/ssot_gate.py は触らない
- 編集前に必ず Read ツールでファイルを読む

## Steps
1. hypothesis_one_cause を確認する
2. 修正対象ファイルを特定する（Read で内容確認してから編集）
3. 最小差分で修正する（Edit または MultiEdit、新規ファイルは Write）
4. 変更内容を1行で記述する（one_fix）
5. verify Skill に引き継ぐ

## Outputs
- one_fix: 修正内容の1行説明
- files_changed: 変更したファイル一覧
- verify_commands: 検証に使うコマンド

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| 修正が大規模になりそう | スコープが広すぎる | スコープを縮小して最小限の修正に留める |
| 依存ファイルが多い | 修正が波及する | 最も根本のファイルのみ修正し、依存先は next_session に書く |
| SSOT gate にブロックされた | protected ファイルを対象にした | 対象ファイルを確認し、別アプローチを取る |
