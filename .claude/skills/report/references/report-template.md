# REPORT_LATEST.md テンプレート

> このファイルをそのまま Write ツールで `runtime/reports/REPORT_LATEST.md` に書き込む。
> `()` 内を必ず実際の内容で埋めること。PLACEHOLDER_MARKERS を残すと on_stop.py が上書きする。

```
# REPORT_LATEST.md
run_id: current_session
generated_at: (今日の日付 YYYY-MM-DD)
status: written_by_claude
generated_by: report Skill

## hypothesis_one_cause
(今回対処した問題の根本原因を1文で)

## one_fix
(適用した修正を1行で)

## files_changed
- (変更したファイルのパス)

## verify_commands
```
(検証に使ったコマンド)
```

## exit_codes
- (コマンド名: exit=0/1/2)

## evidence_paths
- runtime/artifacts/audit_log.jsonl
- docs/go-checklist.md（該当する場合）

## decision
written_by_claude

## DONE
(完了したこと箇条書き)

## NEXT
(次タスクのID と タイトル)

## FAIL
(失敗したことがあれば。なければ「なし」)
```

## PLACEHOLDER_MARKERS（残すと on_stop.py が上書きする）

- `Claudeが作業中に更新する`
- `実施した修正`
- `変更ファイル`
