# Prompt Template: Observe

Use this template as input to the `observe` Skill or as a manual prompt.

---

## OBSERVE — Problem Investigation

**Task**: Investigate the current failure or task before making any changes.

### Must Read First
1. `SSOT.md` — confirm scope and absolute rules
2. `runtime/runs/latest.json` — last run status and errors
3. `runtime/reports/REPORT_LATEST.md` — last report details
4. `tasks/milestones.json` — current task context

### Investigation Steps
1. Read the error or failure description from `runtime/reports/REPORT_LATEST.md`
2. Identify the single most likely root cause
3. Confirm the cause by reading the relevant source file(s)
4. Declare the scope of files that will be changed (no writes yet)

### Output Format
```
## hypothesis_one_cause
<single sentence describing the root cause>

## evidence
- file: <path>
- line: <line number if applicable>
- observation: <what confirms this is the cause>

## scope
Files that will be changed:
- <file1>
- <file2>

Files that will NOT be changed:
- SSOT.md
- policy/ssot_integrity.json
- (any other out-of-scope files)
```

### Constraints
- Do not write any files during Observe
- Identify exactly ONE cause
- If multiple causes exist, pick the most critical and defer the rest to future loops
