# AI Orchestrator Loop (Public Extract)

This repository is a focused OSS extract of the AI Orchestrator Loop runtime.

## Scope
- Webhook ingest server (`POST /webhook`, `GET /health`)
- Event normalization and run logs
- Next prompt generation
- Report generation

## Repository Layout
- `tools/orchestrator/`: implementation
- `rules/`: SSOT and SSOT-first rules
- `policy/`: machine-readable policy
- `tools/orchestrator_runtime/`: runtime outputs (ignored; `.gitkeep` only)

## Quickstart
1. Install Python 3.11+.
2. From repo root:
```bash
make orch-restart
make orch-health
make orch-post
make orch-report
```

## Safety Notes
- Runtime outputs must stay out of Git (`tools/orchestrator_runtime/**`).
- Do not place secrets in this repository.
- Use localhost operation by default (`127.0.0.1:8765`).

## License
This project is licensed under MIT. See `LICENSE`.

## Security
See `SECURITY.md` for vulnerability reporting guidance.
