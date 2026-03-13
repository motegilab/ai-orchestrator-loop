# Runbook: Release Checklist (OSS Readiness)

Use this checklist before pushing a new version of the template to GitHub.

## Pre-Release Checks

### Repository Safety

- [ ] `runtime/` is fully excluded by `.gitignore` (run `git status` — `runtime/` must not appear)
- [ ] No secrets, tokens, or API keys in any tracked file
- [ ] No private absolute paths (e.g., `C:\Users\yourname\...`) in any tracked file
- [ ] `policy/notifications.json` has `"enabled": false` and no webhook URLs
- [ ] `.env` files are not tracked

### Required Files Present

- [ ] `README.md` — includes quickstart instructions
- [ ] `LICENSE` — MIT or compatible
- [ ] `SECURITY.md` — vulnerability reporting guidance
- [ ] `CLAUDE.md` — within 200 lines
- [ ] `SSOT.md` — design source of truth
- [ ] `Makefile` — loop-start / loop-stop / loop-status / setup
- [ ] `.gitignore` — `runtime/**` excluded
- [ ] `.claude/settings.json` — Hook definitions
- [ ] `policy/policy.json`
- [ ] `policy/ssot_integrity.json`

### Template Neutrality

- [ ] `CLAUDE.md` and `SSOT.md` describe the template, not a specific project
- [ ] `tasks/milestones.json` reflects template tasks, not project-specific tasks
- [ ] No hardcoded project names in docs

### Integrity

- [ ] `policy/ssot_integrity.json` hash matches current `SSOT.md`
  ```bash
  python .claude/hooks/ssot_gate.py
  ```
- [ ] All Hooks run without error on a clean `make loop-start`

## Post-Release

- [ ] Tag the release: `git tag v1.x.x`
- [ ] Update `README.md` with the new version if applicable
- [ ] Verify the GitHub template flag is enabled (Settings → Template repository)

## Triggered Skill

The `release` Skill in `.claude/skills/release/SKILL.md` automates most of these checks.
