# Loop System — 本開発フィードバックログ

発見日時: セットアップ〜ループ稼働テスト中（2026-03-13）
テスト文脈: CODEX版ループ開発をClaude版ループで回すことで、ループシステム自体の問題を発見

---

## ISSUE-001: checkpoint タスクで無限停止
**発見**: 2026-03-13
**重大度**: High（ループが前進しなくなる）

### 症状
`"checkpoint": true` のタスクに差し掛かると `loop_run.py` が毎回 `sys.exit(0)` で終了する。
`make loop-run` を再実行しても同じタスクで止まり続ける。

### 根本原因
```python
# loop_run.py L147-150（修正前）
if next_task.get("checkpoint"):
    print_status("このタスクの前で停止します。確認後 make loop-run で再開してください。")
    sys.exit(0)  # ← 確認後も同じ動作になる
```
「確認後に再開」とメッセージを出すが、再開しても同じ分岐に入る。

### 修正
確認プロンプト `[y/N]` を追加。`y` で実行継続、`--yes` フラグで全自動。

```python
if next_task.get("checkpoint"):
    ans_cp = ask("[loop-run] このタスクを実行しますか? [y/N]: ", default="n")
    if ans_cp.lower() != "y":
        sys.exit(0)
    # y の場合はそのまま実行へ
```

### 本開発への提案
- checkpoint は「手前で止まる」ではなく「確認後に実行」が自然な動作
- `make loop-run --yes` で全checkpoint通過できることをドキュメント化
- FIRST_PROMPT.md / onboarding-prompt.md に checkpoint 動作の説明を追記する

---

## ISSUE-002: Makefile 重複ターゲット警告
**発見**: 2026-03-13
**重大度**: Low（動作は問題なし、ノイズ）

### 症状
`make loop-run` 実行時に大量の warning が出力される:
```
Makefile:56: warning: overriding recipe for target 'loop-start'
Makefile:11: warning: ignoring old recipe for target 'loop-start'
...（全ターゲット分）
```

### 根本原因
Makefile と GNUmakefile が両方読み込まれており、同名ターゲットが重複定義されている。
（マージ時のアーティファクト）

### 本開発への提案
- Makefile の重複ターゲットを整理するか、`GNUmakefile` を `include` 構造に変える
- または GNUmakefile の v2 ターゲットだけを残し、v1 ターゲットを Makefile に一本化

---

_このファイルは CODEX版ループ開発テスト中に発見した問題を記録します。_
_新しい問題が見つかり次第追記します。_
