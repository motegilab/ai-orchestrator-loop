# Quality Policy (Verification and Evidence)

## Completion Rules
- No task is complete by narrative only.
- No mock-only completion claims are accepted.
- Completion requires command output and artifact evidence.

## Verification Layers
1. Unit/static checks when applicable (`python -m py_compile`, targeted tests).
2. Runtime checks for orchestrator loop (`make orch-health`, `make orch-post`, `make orch-report`).
3. Report integrity check: declared verify commands must appear in executed command logs.

## Evidence Requirements
- Each task must provide:
  - command(s) executed
  - exit code(s)
  - artifact path(s)
  - concise verdict (pass/fail/blocked)
- Evidence should be persisted under `tools/orchestrator_runtime/artifacts/**` and linked from runs/report.

## Failure Handling
- If evidence is missing, status must be `blocked` or `failed`.
- Report must include the missing evidence reason and one minimal next fix.

## Quality Gates for This Skeleton
- `tasks/milestones.json` remains valid JSON.
- `prompts/*.md` stays role-scoped and under 80 lines each.
- No secrets and no absolute path leakage.
