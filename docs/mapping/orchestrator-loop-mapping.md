# Orchestrator Loop Concept Mapping

Maps legacy (Codex/Webhook) concepts to the Claude-First implementation.

## Core Concept Mapping

| Legacy Concept | Legacy Location | Claude-First Equivalent |
|---------------|-----------------|------------------------|
| SSOT | `rules/SSOT_AI_Orchestrator_Loop.md` | `SSOT.md` (repo root) |
| SSOT-First Gate | `python ssot.py` in Makefile | PreToolUse Hook (`ssot_gate.py`) + UserPromptSubmit Hook |
| Webhook server | `tools/orchestrator/server.py` (localhost:8765) | Not needed — Hook system is event-driven |
| `next_prompt.md` generation | `tools/orchestrator/planner.py` | Stop Hook (`on_stop.py`) → `runtime/logs/next_session.md` |
| Context injection | Manual copy-paste into Codex | SessionStart Hook → `additionalContext` (automatic) |
| Run log | `orchestrator_runtime/runs/latest.json` | `runtime/runs/latest.json` |
| Report | `orchestrator_runtime/reports/REPORT_LATEST.md` | `runtime/reports/REPORT_LATEST.md` |
| Role prompts | `prompts/planner.md`, `builder.md`, `verifier.md` | `.claude/skills/observe/`, `patch/`, `verify/` + `tools/prompts/` |
| Makefile entry points (12) | `orch-start`, `orch-health`, `orch-post`, etc. | 4 targets: `loop-start`, `loop-stop`, `loop-status`, `setup` |
| scope_guard | `artifacts/diffs/*_scope_guard.txt` | `runtime/artifacts/audit_log.jsonl` (via PostToolUse Hook) |
| `milestones.json` | `tasks/milestones.json` | `tasks/milestones.json` (unchanged) |
| `ASSISTANT.md` | `ASSISTANT.md` (repo root) | Merged into `CLAUDE.md` |
| `policy/policy.json` | `policy/policy.json` | `policy/policy.json` (same, extended) |

## Runtime Artifact Mapping

| Legacy Path | New Path |
|-------------|----------|
| `tools/orchestrator_runtime/runs/` | `runtime/runs/` |
| `tools/orchestrator_runtime/reports/` | `runtime/reports/` |
| `tools/orchestrator_runtime/logs/next_prompt.md` | `runtime/logs/next_session.md` |
| `tools/orchestrator_runtime/artifacts/webhooks/` | Removed (no webhook server) |
| `tools/orchestrator_runtime/artifacts/summaries/` | `runtime/artifacts/` (general) |
| `tools/orchestrator_runtime/artifacts/diffs/` | `runtime/artifacts/diffs/` |
| `tools/orchestrator_runtime/artifacts/audits/` | `runtime/artifacts/audits/` |

## Hook → Legacy Component Mapping

```
SessionStart Hook   ←→  server.py startup + next_prompt.md read + context inject
UserPromptSubmit    ←→  ssot.py check (per prompt)
PreToolUse          ←→  scope_guard in ssot.py (per file write)
PostToolUse         ←→  artifacts/diffs + audit log
Stop Hook           ←→  planner.py (next_prompt) + report generation + run log update
```

## What Was Removed

- `tools/orchestrator/server.py` — Webhook HTTP server (replaced by Hooks)
- `tools/orchestrator/planner.py` — next_prompt.md generation (replaced by Stop Hook)
- `tools/orchestrator/normalize.py` — Webhook payload normalization (not needed)
- `tools/orchestrator/scripts/*.ps1` — Start/stop/restart server scripts (replaced by `make loop-start`)
- `ASSISTANT.md` — Merged into CLAUDE.md
- `rules/SSOT_FIRST_Orchestrator.md` — Merged into SSOT.md §1

## What Was Added (Claude-First Only)

- `.claude/settings.json` — Hook registration
- `.claude/hooks/on_session_start.py` — Auto context injection
- `.claude/hooks/on_stop.py` — Auto report + next_session.md generation
- `.claude/hooks/ssot_gate.py` — Deterministic SSOT integrity check
- `.claude/hooks/post_tool_quality.py` — Audit log per tool call
- `.claude/skills/*/SKILL.md` — Auto-invocable reusable workflow steps
- `policy/prompt_eval.json` — Prompt quality thresholds
- `policy/notifications.json` — Future notification config (Discord/Slack)
