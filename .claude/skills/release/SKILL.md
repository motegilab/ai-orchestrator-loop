---
name: release
description: >
  OSS公開前のリリース準備チェックSkill。
  "release", "publish", "OSS readiness check", "リリース", "公開チェック" で自動invokeされる。
allowed-tools: "Bash, Read, Glob, Grep"
metadata:
  version: 1.1.0
---

# Release Skill

## Purpose

Verify OSS readiness of this template repository before pushing to GitHub.
Checks safety, required files, template neutrality, and SSOT integrity.

## Must Read First

1. `SSOT.md` §1 (absolute rules)
2. `policy/ssot_integrity.json` (current hash)
3. [Release checklist](references/release-checklist.md)

## Steps

### 1. Safety Check
- Verify `runtime/` is not tracked by Git (`git status` — must not appear)
- Scan tracked files for secrets: `password`, `token`, `webhook`, `Bearer`
- Confirm `policy/notifications.json` has `"enabled": false`

### 2. Required Files Check
Verify all exist: `README.md`, `LICENSE`, `SECURITY.md`, `CLAUDE.md` (≤200 lines),
`SSOT.md`, `Makefile`, `.gitignore`, `.claude/settings.json`,
`policy/policy.json`, `policy/ssot_integrity.json`

### 3. Template Neutrality Check
- `CLAUDE.md` / `SSOT.md` must not contain project-specific names or hardcoded paths
- `tasks/milestones.json` must use template placeholder tasks, not project tasks

### 4. Integrity Verification
```bash
python .claude/hooks/ssot_gate.py
```
Expected: exit 0. Hash mismatch → run `--update-hash` after confirming SSOT.md is correct.

### 5. Functional Smoke Test
```bash
python -m py_compile .claude/hooks/on_session_start.py
python -m py_compile .claude/hooks/on_stop.py
python -m py_compile .claude/hooks/ssot_gate.py
python -m py_compile .claude/hooks/post_tool_quality.py
```
Expected: exit 0 for each.

## Outputs

- `runtime/reports/REPORT_LATEST.md` — `## release_check_results` with pass/fail per item
- `decision`: `ready` | `blocked` (with reasons)

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `runtime/` in git status | `.gitignore` missing entry | Add `runtime/**` to `.gitignore` |
| Secret pattern found | Credential in source | Remove and rotate the credential |
| SSOT hash mismatch | SSOT.md changed without `make setup` | Run `python .claude/hooks/ssot_gate.py --update-hash` |
| Syntax error in Hook | Bug in hook script | Fix the hook script before release |
| CLAUDE.md > 200 lines | Too verbose | Move details to `docs/` and link |
| milestones.json has project tasks | Not reset to template | Replace with template placeholder content |
