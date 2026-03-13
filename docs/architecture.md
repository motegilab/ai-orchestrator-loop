# Architecture — AI Orchestrator Loop (Claude-First v1)

## Overview

This repository is a **template** for running Claude Code CLI as a self-driven development loop.
The loop is controlled entirely by Claude Code's Hook system — no external servers, no Webhooks.

## Dependency Direction

```
SSOT.md + CLAUDE.md          ← Design constraints (read-only in auto-loop)
    ↓
policy/*.json                ← Machine-readable policy (scope, thresholds, notifications)
    ↓
tasks/milestones.json        ← Task intent (milestone > wave > task)
    ↓
.claude/hooks/*.py           ← Loop control (SessionStart, PreToolUse, PostToolUse, Stop)
    ↓
.claude/skills/*/SKILL.md   ← Reusable workflow steps (observe/patch/verify/release)
    ↓
runtime/                     ← Evidence artifacts (git-excluded)
```

No reverse dependency from `runtime/` back into `policy/` or `SSOT.md` is allowed.

## Loop Lifecycle

```
make loop-start
    │
    ▼
[SessionStart Hook] on_session_start.py
    - Reads runtime/runs/latest.json
    - Reads runtime/reports/REPORT_LATEST.md
    - Reads runtime/logs/next_session.md
    - Outputs additionalContext → auto-injected into Claude's session
    │
    ▼
[UserPromptSubmit Hook] ssot_gate.py --mode=prompt
    - Checks SSOT.md sha256 integrity
    - Blocks if hash mismatch
    │
    ▼
[Claude works] Observe → Patch → Verify
    │
    ├─ [PreToolUse Hook] ssot_gate.py
    │       - Blocks writes to SSOT.md, policy/ssot_integrity.json, .git/
    │
    └─ [PostToolUse Hook] post_tool_quality.py
            - Records all Write/Edit calls to runtime/artifacts/audit_log.jsonl
    │
    ▼
[Stop Hook] on_stop.py
    - Generates runtime/runs/YYYY-MM-DD_runNNN.json
    - Updates runtime/runs/latest.json
    - Generates runtime/reports/REPORT_LATEST.md
    - Generates runtime/logs/next_session.md (used by next SessionStart)
```

## File Layout

| Path | Git | Purpose |
|------|-----|---------|
| `SSOT.md` | Yes | Design source of truth (auto-write blocked) |
| `CLAUDE.md` | Yes | Claude's project memory (max 200 lines) |
| `Makefile` | Yes | Entry points: loop-start / loop-stop / loop-status / setup |
| `.claude/hooks/` | Yes | Hook scripts (Python, stdlib only) |
| `.claude/skills/` | Yes | Reusable Skills (SKILL.md per skill) |
| `.claude/settings.json` | Yes | Hook registration |
| `policy/` | Yes | Machine-readable policy |
| `tasks/milestones.json` | Yes | Task tracking |
| `docs/` | Yes | Human-readable docs |
| `tools/` | Yes | Helper scripts |
| `runtime/` | No | All generated artifacts (.gitignore) |

## Allowed Directories for Claude Writes

Defined in `policy/policy.json` → `scope_guard.allowed_write_prefixes`:
- `runtime/` — all generated artifacts
- `tasks/` — milestone updates
- `docs/` — documentation updates
- `tools/` — script updates
- `src/` — source code

## Multi-Project Expansion

This repo is a **template repository**. To start a new project:

```bash
gh repo create my-project --template <this-repo>
cd my-project
# Edit CLAUDE.md and SSOT.md for the new project
make setup
make loop-start
```

See [docs/mapping/orchestrator-loop-mapping.md](mapping/orchestrator-loop-mapping.md) for concept mapping.
