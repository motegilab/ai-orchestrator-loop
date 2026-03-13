# Security Policy

## Supported Versions

This is a template repository. Security policies apply to the template itself.

| Version | Supported |
|---------|-----------|
| latest (main) | Yes |

## Reporting a Vulnerability

If you discover a security vulnerability in this template, please report it via GitHub Issues
or by contacting the repository maintainers directly.

**Do not include secrets, tokens, or credentials in any issue or pull request.**

## Security Practices for This Template

### What This Repo Must NOT Contain

- API keys, tokens, or credentials of any kind
- Private absolute paths to local machines
- Personal information
- Runtime artifacts (`runtime/` is excluded from Git via `.gitignore`)

### Runtime Security

- `runtime/` is fully excluded from Git tracking
- All Hook scripts operate on local files only (no network calls in v1)
- `policy/ssot_integrity.json` stores only SHA-256 hashes (no secrets)

### When Adapting This Template

When using this as a base for a new project:
1. Never commit `runtime/` contents
2. Never commit API keys (use environment variables or a secrets manager)
3. Review `policy/` files before committing — they should contain only configuration, not secrets
4. Run `make setup` after cloning to generate your own integrity hashes

## Notification Integrations (Future)

Discord/Slack webhook URLs must be stored in environment variables or a secrets manager,
never hardcoded in `policy/notifications.json` or any tracked file.
