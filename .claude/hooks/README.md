# .claude/hooks — Hook Scripts

All hooks are Python 3.9+, standard library only. No pip installs required.

## Hook Registration

Defined in `.claude/settings.json`. Summary:

| Event | Script | Purpose |
|-------|--------|---------|
| `SessionStart` | `on_session_start.py` | Load previous context, inject into Claude's session |
| `UserPromptSubmit` | `ssot_gate.py --mode=prompt` | Verify SSOT.md integrity before each prompt |
| `PreToolUse` (Write/Edit/MultiEdit) | `ssot_gate.py` | Block writes to protected files |
| `PostToolUse` (Write/Edit) | `post_tool_quality.py` | Audit log every file change |
| `Stop` | `on_stop.py` | Generate run record, report, and next_session.md |

## Scripts

### `on_session_start.py`
- Reads `runtime/runs/latest.json` and `runtime/reports/REPORT_LATEST.md`
- Reads `runtime/logs/next_session.md` if it exists
- Writes a summary to stdout → becomes Claude's `additionalContext`

### `ssot_gate.py`
- Checks SHA-256 of `SSOT.md` against `policy/ssot_integrity.json`
- Blocks writes to: `SSOT.md`, `policy/ssot_integrity.json`, `.git/`
- `--mode=prompt`: runs only integrity check (no tool input check)
- `--update-hash`: regenerates the hash (run after intentional SSOT edits)

### `on_stop.py`
- Generates `runtime/runs/YYYY-MM-DD_runNNN.json`
- Updates `runtime/runs/latest.json`
- Generates `runtime/reports/REPORT_LATEST.md`
- Generates `runtime/logs/next_session.md`
- Checks `stop_hook_active` to prevent infinite loops

### `post_tool_quality.py`
- Appends every Write/Edit event to `runtime/artifacts/audit_log.jsonl`
- Non-blocking (exit 0 always)

## Adding a New Hook

1. Create the Python script in `.claude/hooks/`
2. Register it in `.claude/settings.json` under the appropriate event
3. Test with a dry run before enabling in production loops
4. Scripts must be safe and non-destructive (never delete files)
