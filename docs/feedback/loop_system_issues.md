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

## ISSUE-003: latest.json の next_task スキーマがClaude版と不一致
**発見**: 2026-03-13
**重大度**: Medium（互換性・将来の統合に影響）

### 症状
CODEX版 `on_loop_end.py` が生成する `latest.json` の `next_task` フィールドがオブジェクト。
Claude版はフラットな文字列（task_id のみ）。

```json
// CODEX版
"next_task": { "task_id": "T13", "task_title": "...", "milestone_title": "..." }

// Claude版
"next_task": "T1"
```

### 判断メモ
M4 結合テスト（T15-T17）でループが自力で気づけるか観察する。
気づけなければ「ループの自己診断能力不足」としてフィードバック対象。

---

## ISSUE-004: milestone-review Skill がループから一度も呼ばれない
**発見**: 2026-03-16
**重大度**: High（設計済みの機能が完全に未発火）

### 症状
- `milestone-review` Skill は `.claude/skills/milestone-review/SKILL.md` に完全実装済み
- M1〜M4（計17タスク）を32ループ実行した結果、`MANUAL_CHECK_*.html` が一度も生成されなかった
- Skill の description に「`loop_run.py` が `milestone_completed` を検出した時に自動invoke」と明記されているが、
  `loop_run.py` には対応するコードが存在しない

### 根本原因の特定

`tools/scripts/loop_run.py` の実装ギャップ（コード証跡）:

```python
# loop_run.py L140-183（現状）
for i in range(1, max_loops + 1):
    next_task = get_next_task()
    if not next_task:
        print_status(f"全タスク完了。{i - 1} ループ実行しました。")
        break
    # ... タスク実行 ...
    report_source = get_last_report_source()
    # ← ここにマイルストーン境界検出が存在しない
```

不足している処理:
1. **マイルストーン完了検出**: あるタスク完了後、そのマイルストーンの全タスクが `done` になったかを確認する処理
2. **`milestone_completed` の `latest.json` への書き込み**: Skill の invoke トリガーとなるフィールドが一度も書かれていない
3. **Skill 呼び出しまたはユーザーへの通知**: milestone-review Skill を明示的に呼ぶか、Claudeへのコンテキストとして渡す処理

### 設計意図との乖離

| 設計意図（SKILL.md） | 実態（loop_run.py） |
|---|---|
| `milestone_completed` 検出時に自動invoke | `milestone_completed` フィールドなし |
| マイルストーン毎に HTML チェックリスト生成 | HTML 生成ゼロ |
| 各フェーズ完了後に手動確認を促す | フェーズ境界の概念なし |

### 必要な修正（本開発への提案）

**① `loop_run.py` にマイルストーン完了検出を追加する**

```python
# ループ完了後、マイルストーン境界チェック（追加すべき処理のイメージ）
def check_milestone_completed(milestones_path, just_completed_task_id):
    """直前に完了したタスクが属するマイルストーンの全タスクが done か確認"""
    data = json.loads(milestones_path.read_text())
    for m in data["milestones"]:
        tasks = [t for w in m.get("waves", []) for t in w["tasks"]]
        task_ids = [t["id"] for t in tasks]
        if just_completed_task_id in task_ids:
            all_done = all(t["status"] == "done" for t in tasks)
            if all_done:
                return {"milestone_id": m["id"], "milestone_title": m["title"]}
    return None
```

**② `latest.json` に `milestone_completed` フィールドを書き込む**

```python
# on_stop.py または loop_run.py の post 処理で追記
if milestone_completed:
    latest["milestone_completed"] = milestone_completed
    LATEST.write_text(json.dumps(latest, ensure_ascii=False, indent=2))
```

**③ Skill invoke のトリガーを確実にする**

選択肢A: `next_session.md` に `milestone_completed` 情報を含めて Claudeがセッション開始時に検出
選択肢B: `loop_run.py` から直接 `claude` CLI を `milestone-review` Skill 付きで呼ぶ
選択肢C: loop_run.py がマイルストーン完了を検出したらユーザーへのプロンプトを出してHtmlを生成させる

**推奨: 選択肢A** — on_stop.py / next_session.md 経由が既存アーキテクチャとの整合性が最高。

### ISSUE-003 との関連

ISSUE-003（`next_task` スキーマ差異）についてはM4でループが自力で気づかなかった。
→ 「自己診断能力の限界」として本ISSUEと合わせてフィードバック対象とする。
スキーマ差異の修正はCODEX版 `on_loop_end.py` 側で行うべき（Claude版との互換性確保）。

### 影響範囲

- Claude版ループ: `tools/scripts/loop_run.py` + `.claude/hooks/on_stop.py`
- CODEX版ループ: 修正後に同様の処理を `tools/codex_scripts/loop_run.py` + `on_loop_end.py` にも適用が必要

---

_このファイルは CODEX版ループ開発テスト中に発見した問題を記録します。_
_新しい問題が見つかり次第追記します。_
