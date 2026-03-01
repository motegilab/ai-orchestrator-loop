# Architecture (File-Based Task Skeleton)

## Purpose
Define a minimal, OSS-safe structure for milestone/wave/task planning that fits the current SSOT + report loop.

## Allowed Directories
- `tools/orchestrator/`: executable implementation
- `rules/`: normative SSOT and operation rules
- `policy/`: machine policy defaults
- `tasks/`: file-based autonomy memory (`milestones.json`)
- `prompts/`: role prompts (planner/builder/verifier)
- `docs/`: human-readable architecture and quality rules
- `tools/orchestrator_runtime/`: runtime outputs only (ignored except `.gitkeep`)

## Dependency Direction
1. `rules/` and `policy/` define constraints.
2. `tasks/milestones.json` defines milestone/wave/task intent.
3. `prompts/` defines role behavior consuming 1 and 2.
4. `tools/orchestrator/` executes and emits runtime artifacts.
5. `tools/orchestrator_runtime/` stores evidence for reports.

No reverse dependency is allowed from `tools/orchestrator_runtime/` back into `rules/` or `policy/`.

## Scope Guard Intent
- Keep implementation changes under `tools/orchestrator/**`.
- Keep planning artifacts under `tasks/`, `prompts/`, `docs/`.
- Do not mix runtime evidence with source files.
