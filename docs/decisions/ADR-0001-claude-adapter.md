# ADR-0001: Claude Code CLI as Primary Orchestration Engine

**Status**: Accepted
**Date**: 2026-03-05
**Supersedes**: Legacy Webhook + Codex architecture (v2.0, 2026-02-18)

## Context

The previous architecture (v2.0) used:
- A Python HTTP server (`server.py`) running on `localhost:8765`
- Cursor Webhook integration (`POST /webhook`)
- Codex CLI as the AI execution engine
- Manual copy-paste of `next_prompt.md` to start each loop

This required significant infrastructure and had a manual "seam" between each loop iteration.

## Decision

Replace the Webhook server + Codex architecture with **Claude Code CLI + Hook system**.

The Hook system provides native equivalents for every component of the old architecture:

| Old (Codex/Webhook) | New (Claude-First) |
|---------------------|-------------------|
| `server.py` POST /webhook | Stop Hook (`on_stop.py`) |
| Manual `next_prompt.md` paste | SessionStart Hook auto-injects context |
| `python ssot.py` in Makefile | PreToolUse Hook (`ssot_gate.py`) |
| `make orch-run-next-local` | `make loop-start` |
| 12 Makefile targets | 3 targets: loop-start / loop-stop / loop-status |

## Consequences

**Positive:**
- No server process to manage
- No manual copy-paste between loops
- Hook system provides 100% deterministic blocking (vs 70% via CLAUDE.md rules alone)
- Simpler setup: `git clone` + `make setup` + `make loop-start`
- Claude Code's `--add-dir ~/.claude/skills` enables global Skill sharing across projects

**Negative / Accepted tradeoffs:**
- Requires Claude Code CLI (Pro subscription or above)
- Loop continuation requires human to run `make loop-start` each time (intentional in v1)
- No built-in multi-project orchestration (planned for v2 via Subagents)

## v1 Constraints Lifted vs Maintained

| Constraint | Status |
|-----------|--------|
| CLI auto-invocation prohibited | **Lifted** — `make loop-start` invokes Claude directly |
| No external network calls from Hooks | **Maintained** |
| SSOT.md read-only in auto-loop | **Maintained** (PreToolUse Hook blocks) |
| 1 cause / 1 fix per loop | **Maintained** |
| `runtime/` excluded from Git | **Maintained** |

## Related

- [SSOT.md](../../SSOT.md)
- [docs/architecture.md](../architecture.md)
- [docs/mapping/orchestrator-loop-mapping.md](../mapping/orchestrator-loop-mapping.md)
