# Runbook: Environment Check

## What is an Environment Check?

Before starting a loop session, the system verifies that all required components are present
and correctly configured. This prevents silent failures mid-loop.

The check runs automatically via the **SessionStart Hook** (`on_session_start.py`),
but can also be triggered manually.

## Required Components

| Component | Check | Command |
|-----------|-------|---------|
| Claude Code CLI | Installed and authenticated | `claude --version` |
| Python 3.9+ | Available in PATH | `python --version` or `python3 --version` |
| GNU Make | Available in PATH | `make --version` |
| SSOT.md | Exists at repo root | File check |
| CLAUDE.md | Exists at repo root | File check |
| policy/policy.json | Exists | File check |
| policy/ssot_integrity.json | Hash matches SSOT.md | `python .claude/hooks/ssot_gate.py` |

## How to Run (Windows / Git Bash)

```bash
# Full setup check (recommended first time)
make setup

# Quick status check (reads last run)
make loop-status

# Manual integrity check only
python .claude/hooks/ssot_gate.py

# Manual hash update (after intentionally editing SSOT.md)
python .claude/hooks/ssot_gate.py --update-hash
```

## PowerShell Alternative

```powershell
# Run the env check script
.\tools\scripts\orch_env_check.ps1
```

## Future Artifacts

When fully implemented, env-check will produce:
- `runtime/artifacts/env_check.json` — machine-readable result
- `runtime/logs/health.txt` — human-readable summary

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `SSOT-GATE: BLOCKED` on startup | SSOT.md was modified without updating hash | Run `make setup` |
| `WARNING: 必須ファイルが見つかりません` | Missing required files | Check file paths in SessionStart output |
| `claude: command not found` | Claude Code CLI not installed | Install from claude.ai |
| `python3: command not found` | Python not in PATH | Install Python 3.9+ or use `python` instead |
