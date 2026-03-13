# Prompt Template: Patch

Use this template after Observe has identified the root cause.

---

## PATCH — Minimal Fix

**Prerequisite**: Observe phase must be complete. One cause identified.

### Input Required
- `hypothesis_one_cause` from Observe output
- `scope` (list of files to change) from Observe output

### Patch Rules
1. Change only files in the declared scope
2. Minimum diff — do not refactor surrounding code
3. Do not change SSOT.md or policy/ssot_integrity.json
4. One cause = one fix. Stop after fixing this cause.
5. Add no new features or cleanup beyond the fix

### Steps
1. Read the target file(s) fully before editing
2. Apply the minimum change to address the one cause
3. Record what was changed in `files_changed`

### Output Format
```
## one_fix
<single sentence describing what was changed and why>

## files_changed
- <file1>: <brief description of change>
- <file2>: <brief description of change>

## diff_summary
<key lines added/removed — not a full diff, just the critical parts>
```

### Constraints
- No writes outside declared scope
- No bundled fixes
- PreToolUse Hook will block writes to protected files automatically
