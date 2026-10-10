# Contributing

- The platform verifies itself: `PYTHONPATH=src python3 -m dev_platform check --stage full` must be
  green (unit tests, ruff lint and format pinned in `dev-platform.toml`, docs checks). CI runs the same.
- Standard library only at runtime (ADR 0008). New dependencies need an ADR.
- Changing a contract (`schemas/`, config keys, result fields, exit codes) needs an ADR or ADR
  amendment, a schema/test update, and a CHANGELOG entry. Contract changes that break consumers
  bump the schema version.
- Weakening a check, obligation or invariant must be called out as such in the PR description.
- Never commit anything from private infrastructure (hostnames, runner inventory, credentials).
- Releases: tag `vX.Y.Z` only from a certified full-stage run; record the tree digest.
