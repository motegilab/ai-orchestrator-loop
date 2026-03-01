# Security Policy

## Supported Scope
This repository accepts security reports for code under:
- `tools/orchestrator/`
- `policy/`
- `rules/` (policy/operational implications)

## Reporting a Vulnerability
- Do not open public issues containing exploit details or secret material.
- Report privately with:
  - affected file/path
  - impact summary
  - reproduction steps
  - suggested mitigation (if available)

## Sensitive Data Handling
- Never commit API keys, tokens, private keys, or `.env` secrets.
- If sensitive content is found, rotate credentials first, then report the path and pattern type.

## Disclosure
- We aim to acknowledge reports promptly and coordinate a fix before public disclosure.
