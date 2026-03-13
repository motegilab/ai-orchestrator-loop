include Makefile

ORCH_LOOP_N ?= 3
ORCH_LOOP_INTERVAL ?= 1
ORCH_CODEX_TIMEOUT ?= 600
ORCH_PORT ?= 8765
ORCH_TASK_RUNNER := python tools/orchestrator/scripts/make_tasks.py

ORCH_TARGETS := orch-start orch-start-bg orch-stop orch-restart orch-health orch-post orch-signal orch-report orch-audit orch-setup orch-doctor orch-run-next orch-run-next-local orch-loop-local orch-runner-start orch-runner-once orch-runner-log

.PHONY: $(ORCH_TARGETS)

$(ORCH_TARGETS):
	@$(ORCH_TASK_RUNNER) --task $@ --port $(ORCH_PORT) --codex-timeout $(ORCH_CODEX_TIMEOUT) --loop-n $(ORCH_LOOP_N) --loop-interval $(ORCH_LOOP_INTERVAL) --audit-file "$(AUDIT_FILE)" --signal "$(SIGNAL)"

.PHONY: orch-loop-run
orch-loop-run:
	@python tools/orchestrator/scripts/loop_run.py $(ORCH_LOOP_RUN_ARGS)
