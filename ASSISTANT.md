# ASSISTANT CONSTITUTION PACK

この文書は、AI Orchestrator Loop の実行時に人間とLLMが同じ前提で動くための運用憲法です。
SSOT、機械ポリシー、監査レポートの三層を揃え、モデル差異によるドリフトを抑えます。

## 1. Purpose

- 目的:
- SSOT と実装の整合を保ったまま、反復修正を安全に回す
- 生成物を claim→evidence で監査可能にする
- 複数モデル/複数チャットでも同じ判断基準を維持する

## 2. Scope

- 対象:
- `tools/orchestrator/**`
- `tools/orchestrator_runtime/**`（生成物）
- `rules/**`（憲法/SSOT）
- `policy/policy.json`
- `ASSISTANT.md`
- `Makefile` / `GNUmakefile`（入口）

## 3. Non-Goals

- v1 の自動大改修は行わない
- SSOT を自動で書き換えない
- 「雰囲気で成功扱い」はしない

## 4. Source Of Truth Hierarchy

- 優先順位:
1. `rules/SSOT_AI_Orchestrator_Loop.md`
2. `policy/policy.json`
3. `tools/orchestrator_runtime/runs/latest.json`
4. `tools/orchestrator_runtime/reports/REPORT_LATEST.md`
- 競合時は上位を正とする

## 5. Anti-Lost Protocol (Must Read First)

- 開始時に必ず読む:
1. `rules/SSOT_AI_Orchestrator_Loop.md`
2. `rules/SSOT_FIRST_Orchestrator.md`
3. `tools/orchestrator_runtime/runs/latest.json`
4. `tools/orchestrator_runtime/reports/REPORT_LATEST.md`
- 上記が欠ける場合は推測で進めず、`blocked` として記録する

## 6. Execution Constraints

- one-cause / one-fix:
- 原因を1つに固定して最小差分を当てる
- scope guard:
- 許可パス外の読み書きは禁止
- denylist に一致したら停止
- command guard:
- 許可コマンドのみ実行
- 読み取り対象が scope に一致しないコマンドは停止

## 7. Allowed / Denied Path Policy

- allowed prefixes:
- `rules/`
- `tools/orchestrator/`
- `tools/orchestrator_runtime/`
- `Makefile`
- `GNUmakefile`
- denied prefixes:
- `9990_System/`
- `.git/`
- `node_modules/`
- denied globs:
- `**/AGENTS*.md`
- `**/*.secret`
- `**/*.key`

## 8. Self-Repair Loop Protocol

- `policy.self_repair_loop.max_iters` を上限として反復
- 1 iteration の固定手順:
1. OBSERVE
2. HYPOTHESIS
3. ONE_FIX
4. VERIFY
5. REPORT
- stop conditions:
- 検証がすべて PASS
- もしくは `MAX_ITERS` 到達
- もしくは policy/SSOT 違反で `blocked`

## 9. Verification Before Done

- VERIFY 宣言したコマンドは実行ログに必ず存在すること
- `summaries/<run_id>*.meta.json` に command/exit/timestamps を残すこと
- claim は evidence なしで成立させない

## 10. Reporting Protocol

- REPORT 必須セクション:
- `Report Integrity Gate`
- `Claim-Evidence Map`
- `Latest JSON Snapshot`
- `Negative Test Evidence`
- 次の状態を必ず明示:
- `run_status`
- `report_status`
- `report_error`

## 11. Claim → Evidence Rule

- 「実装した」「反映済み」「検証済み」は禁句ではないが、必ず証拠を添える
- 証拠は最低限:
- file path
- 実行コマンド
- マッチ行または抜粋

## 12. SSOT Amendment Protocol

- SSOT 改定は通常ループから分離し、手動の amendment として扱う
- 必須項目:
- `amendment_id`
- `reason`
- `acceptance`
- `evidence_paths`
- 改定後は必ず実行:
1. `make orch-post`
2. `make orch-report`

## 13. Runtime Audit Rules

- 監査生成物は常に保存:
- `runs/latest.json`
- `reports/REPORT_LATEST.md`
- `artifacts/summaries/<run_id>*.meta.json`
- 失敗時は `failed` / `blocked` を明示し、次アクションを1つに絞る

## 14. When Stuck Playbook

- やってはいけないこと:
- スコープ拡大
- 証拠なし主張
- silent retry の連発
- 取るべき行動:
1. 欠落証拠を特定
2. one-fix を1つ選択
3. `blocked` で停止し、次の1アクションを記録

## 15. Operational Checklist

- 開始前:
- [ ] Must Read First を読んだ
- [ ] 現在の `run_id` を確認した
- [ ] one-cause を1つに固定した
- 実施中:
- [ ] 変更範囲が allowlist 内
- [ ] VERIFY コマンドを実行した
- [ ] evidence_paths を更新した
- 終了時:
- [ ] REPORT の必須セクションが存在
- [ ] Claim-Evidence Map が PASS
- [ ] Integrity Gate が PASS

## 16. Integration Contract

- planner は `ASSISTANT.md rules apply` ヘッダを next_prompt に出す
- planner は policy の must_read_first を Anti-Lost セクションへ反映する
- server は `policy/policy.json` を読み、`runs/latest.json.policy` にスナップショットを写す
- report は `ASSISTANT.md` と `policy/policy.json` の存在証拠を Claim-Evidence Map に追加する

## 17. Notes

- この文書は CLAUDE.md 互換を目的としない
- 目的は「このリポジトリで再現可能な最小運用憲法」を固定すること
