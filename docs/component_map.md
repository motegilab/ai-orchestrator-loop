# Component Map (Loop-First)

## Goal
Define components and boundaries before feature work, so each loop iteration can target one component only.

## Components
| ID | Component | Main Paths | Responsibility |
|---|---|---|---|
| C1 | Governance | `rules/`, `ASSISTANT.md` | Normative rules and operating constraints |
| C2 | Machine Policy | `policy/policy.json` | Scope/command/integrity policy values |
| C3 | Webhook Core | `tools/orchestrator/server.py` | Receive event, normalize, gate, persist run |
| C4 | Prompt Planner | `tools/orchestrator/planner.py` | Build `next_prompt.md` from latest evidence |
| C5 | Report Engine | `tools/orchestrator/report.py` | Build `REPORT_LATEST.md` and integrity sections |
| C6 | Task Entrypoints | `tools/orchestrator/scripts/make_tasks.py` | Deterministic make tasks and local orchestration |
| C7 | Local Runner | `tools/orchestrator/scripts/run_next_local.py` | Execute one local cycle and post result |
| C8 | Runtime State | `tools/orchestrator_runtime/**` | Generated evidence only (runs/reports/logs/artifacts) |
| C9 | Human Ops Docs | `docs/`, `tasks/`, `prompts/` | Human-facing guidance and staged tasks |

## Boundary Rules
- C1/C2 are upstream constraints; runtime components must not rewrite them automatically.
- C3 writes run records; C4/C5 read those records and emit prompt/report artifacts.
- C6/C7 are entrypoints; they call into C3 via webhook and must keep command surface narrow.
- C8 is output-only memory; source components read from it but do not treat it as normative policy.
- C9 documents workflows; it does not execute code.

## Interface Contracts
- C3 -> C8:
  - `runs/latest.json`
  - `runs/YYYY-MM-DD_runNNN.json`
  - `logs/next_prompt.md`
- C5 -> C8:
  - `reports/REPORT_LATEST.md`
  - `reports/YYYY-MM-DD_runNNN.md`
  - integrity artifacts under `artifacts/`
- C6/C7 -> C3:
  - webhook payload with `event_id`, `status`, `summary`, evidence pointers

## Split Points For Future Changes
- Decision logic only: edit C4 (`planner.py`)
- Run/report classification only: edit C5 (`report.py`)
- Scope/command blocking only: edit C3 (`server.py`) plus C2 (`policy.json`) values
- Operator UX only: edit C6 (`make_tasks.py`) and C9 docs

## Loop Execution Unit
1. Observe C8 (`latest.json`, `REPORT_LATEST.md`)
2. Pick one target component (C3/C4/C5/C6/C7/C9)
3. Apply one-cause/one-fix in that component only
4. Verify with make tasks and evidence paths
5. Report outcome back into C8

