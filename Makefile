.PHONY: check rules hooks clean-structure audit-structure health-check health-check-strict anti-spaghetti excel excel-minpaku excel-souko sync-souko sync-souko-red gas-push help

# デフォルトターゲット
help:
	@echo "📋 利用可能なコマンド:"
	@echo ""
	@echo "  make check          - プロジェクト構造整合性チェック"
	@echo "  make rules          - AGENTS 入口の整合性チェック"
	@echo "  make hooks          - Git hooks を .githooks に固定"
	@echo "  make clean-structure - ゴミファイル検出"
	@echo "  make audit-structure - 重複名/旧パス/Archive漏れの構造監査"
	@echo "  make health-check    - SSOT/0010_Stream の運用ヘルスチェック（警告は継続）"
	@echo "  make health-check-strict - SSOT/0010_Stream の運用ヘルスチェック（警告も失敗）"
	@echo "  make anti-spaghetti - スパゲッティ化防止（散らかったファイルを自動移動）"
	@echo "  make excel-minpaku  - 民泊Variable Ledger → Excel変換"
	@echo "  make excel-souko    - レンタル倉庫Variable Ledger → Excel変換"
	@echo "  make excel          - 全プロジェクトのExcel一括生成"
	@echo "  make sync-souko     - レンタル倉庫Excel編集 → Markdown反映"
	@echo "  make sync-souko-red - レンタル倉庫Excel編集 → Markdown反映（🔴赤いセルのみ）"
	@echo "  make gas-push       - ルール検証後に clasp push を実行"
	@echo "  make help           - このヘルプを表示"
	@echo ""

# 構造整合性チェック
check:
	@echo "🔍 構造整合性チェック実行中..."
	@python 9990_System/scripts/check_structure.py

# AGENTS 入口の整合性チェック
rules:
	@echo "🧭 AGENTS 入口の整合性チェック実行中..."
	@python 9990_System/scripts/check_agents_rules.py
	@echo "🧹 9990_System 直下 Markdown 配置チェック実行中..."
	@python 9990_System/scripts/check_9990_system_root_md.py
	@echo "🔗 旧パス参照チェック実行中..."
	@python 9990_System/scripts/check_legacy_paths.py

# Git hooks を .githooks に固定（A: 認知チェックをコミット前に強制）
hooks:
	@echo "🧷 Git hooks を .githooks に設定中..."
	@git config core.hooksPath .githooks
	@echo "✅ core.hooksPath = .githooks"

# ゴミファイル検出（移動は手動）
clean-structure:
	@echo "🧹 ゴミファイル検出中..."
	@python 9990_System/scripts/check_structure.py | grep "ゴミファイル" || echo "✅ ゴミファイルは見つかりませんでした"

# 構造監査（重複名 / 旧パス / Archive_legacy 漏れ）
audit-structure:
	@echo "🧪 構造監査（重複名/旧パス/Archive漏れ）実行中..."
	@python 9990_System/scripts/check_legacy_paths.py
	@python 9990_System/scripts/audit_structure.py

# 運用ヘルスチェック（SSOT / Daily Briefing）
health-check:
	@echo "🩺 運用ヘルスチェック実行中（SSOT / 0010_Stream）..."
	@python 9990_System/scripts/check_operational_health.py --window-days 14

# 運用ヘルスチェック（警告も失敗扱い）
health-check-strict:
	@echo "🩺 運用ヘルスチェック実行中（strict）..."
	@python 9990_System/scripts/check_operational_health.py --window-days 14 --strict

# スパゲッティ化防止（自動検出・移動）
anti-spaghetti:
	@echo "🍝 スパゲッティ化防止スクリプト実行中..."
	@python 9990_System/scripts/anti_spaghetti_guard.py

# 民泊Variable Ledger → Excel変換
excel-minpaku:
	@echo "📊 民泊Variable Ledger → Excel 変換中..."
	@cd "0040_Projects/民泊" && python execute_excel_generation.py

# レンタル倉庫Variable Ledger → Excel変換
excel-souko:
	@echo "📊 レンタル倉庫Variable Ledger → Excel 変換中..."
	@cd "0040_Projects/レンタル倉庫" && python execute_excel_generation.py

# 全プロジェクトのExcel一括生成
excel: excel-minpaku excel-souko
	@echo "✅ 全プロジェクトのExcel生成完了"

# レンタル倉庫Excel編集 → Markdown反映
sync-souko:
	@echo "🔄 レンタル倉庫Excel → Markdown 同期中..."
	@cd "0040_Projects/レンタル倉庫" && python sync_from_excel.py

# レンタル倉庫Excel編集 → Markdown反映（赤いセルのみ）
sync-souko-red:
	@echo "🔴 レンタル倉庫Excel → Markdown 同期中（赤いセルのみ）..."
	@cd "0040_Projects/レンタル倉庫" && python sync_from_excel.py --red --auto

# ルール検証 + GAS反映
gas-push:
	@echo "🚀 ルール検証を実行してから GAS に反映します..."
	@$(MAKE) rules
	@cd "9990_System/GAS_Project" && clasp push
