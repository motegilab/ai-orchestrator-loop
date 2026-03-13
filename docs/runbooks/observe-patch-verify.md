# Runbook: Observe → Patch → Verify

## Overview

The core work loop inside each Claude session follows this 3-step pattern:

```
Observe → Patch → Verify → Report
```

This is enforced by `CLAUDE.md` and by the Skill system. Skipping steps is not allowed.

## Step 1: Observe

**Goal**: Understand the problem. Evidence first.

Actions:
- Read `runtime/reports/REPORT_LATEST.md` and `runtime/runs/latest.json`
- Read relevant source files
- Identify exactly ONE root cause
- Record hypothesis in `issue_candidates` output

Outputs:
- Clear statement of the single cause
- List of files to be changed (max scope)
- No writes to source files yet

Triggered Skill: `observe` (auto-invoked when problem investigation is requested)

## Step 2: Patch

**Goal**: Apply the minimum change to fix the single cause.

Rules:
- One cause → one fix. Never bundle multiple fixes.
- Minimum diff — do not refactor surrounding code.
- Do not touch files outside the identified scope.
- Do not edit `SSOT.md` or `policy/ssot_integrity.json`.

Outputs:
- Changed files (recorded in `files_changed`)
- Diff summary

Triggered Skill: `patch` (auto-invoked on fix/implement requests)

## Step 3: Verify

**Goal**: Confirm the fix works. No claims without evidence.

Required:
- Run the verification command(s) defined in the task or runbook.
- Record exit code (0 = pass, non-zero = fail).
- Record stdout/stderr tail.
- Record `evidence_paths` pointing to output files.

Outputs:
- `exit_codes` list
- `evidence_paths` list
- Pass/fail determination

Triggered Skill: `verify` (auto-invoked after patch or when "confirm" is requested)

## Step 4: Report

**Goal**: Write a structured summary before the session ends.

Required fields (written to `runtime/reports/REPORT_LATEST.md`):
- `hypothesis_one_cause`
- `one_fix`
- `files_changed`
- `verify_commands`
- `exit_codes`
- `evidence_paths`
- `decision` (success / failed / blocked)

Triggered Skill: `report` (auto-invoked before Stop)

## What Happens on Failure

If any step fails:
1. Record `status: failed` and `top_errors` in `runtime/runs/latest.json`
2. Write `REPORT_LATEST.md` with `decision: failed`
3. Generate `next_session.md` with `## FAIL` and `## FIX` sections populated
4. Stop — do not attempt a second cause in the same session

The next `make loop-start` will pick up from `next_session.md` automatically.
