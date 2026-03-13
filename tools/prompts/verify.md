# Prompt Template: Verify

Use this template after Patch to confirm the fix works.

---

## VERIFY — Confirmation

**Prerequisite**: Patch phase must be complete. `files_changed` recorded.

### Required Actions
1. Run the verification command(s) for this fix
2. Record the exit code (0 = pass)
3. Record stdout/stderr tail as evidence
4. Write evidence to `runtime/artifacts/` if applicable

### Verification Commands (choose applicable)
```bash
# Syntax check for Python Hook scripts
python -m py_compile .claude/hooks/on_stop.py
python -m py_compile .claude/hooks/ssot_gate.py
python -m py_compile .claude/hooks/on_session_start.py
python -m py_compile .claude/hooks/post_tool_quality.py

# SSOT integrity check
python .claude/hooks/ssot_gate.py

# JSON validity check
python -m json.tool policy/policy.json
python -m json.tool policy/ssot_integrity.json

# Git status (confirm runtime/ not tracked)
git status
```

### Output Format
```
## verify_commands
- <command1>
- <command2>

## exit_codes
- <command1>: 0
- <command2>: 0

## evidence_paths
- runtime/artifacts/<relevant file>

## result
PASS | FAIL

## next_action
(if FAIL): <specific next step>
(if PASS): proceed to Report
```

### On Failure
- Do NOT attempt a second fix in the same session
- Record the failure in `REPORT_LATEST.md` with `decision: failed`
- The Stop Hook will generate `next_session.md` with `## FAIL` and `## FIX` populated
- Next `make loop-start` will resume from there
