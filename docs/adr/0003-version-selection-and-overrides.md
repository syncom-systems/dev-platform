# ADR 0003: Version selection, overrides and self-hosting

Status: Superseded in part by [ADR 0014](0014-release-trust-bootstrap-and-execution.md) (launcher mechanism and self-hosted certification; the override rules remain in force)

## Decision
- **Launcher.** `dev-platform` reads the pin, resolves the release in the store
  (`$DEV_PLATFORM_STORE`, else `$XDG_DATA_HOME/dev-platform/versions`), verifies it, and re-executes
  itself with `PYTHONPATH` set to the pinned release (loop-guarded by `DEV_PLATFORM_REEXEC`). The
  launcher only reads the store; installation is a separate, explicit step.
- **Overrides.** `DEV_PLATFORM_OVERRIDE=<checkout>` selects a development checkout or release
  candidate. It is local and explicit, is rejected (exit 3) when `CI=true`, `GITHUB_ACTIONS=true` or
  `--protected` is present, is recorded as `platform.mode = "override"`, and makes results
  non-certifiable.
- **Self-hosting.** A repository that *is* the platform declares `platform.self_hosted = true`
  instead of a pin; it then checks itself with the code under test. Results carry
  `mode = "self"`.

## Open
Whether `self` results may count toward releasing the platform itself, or whether a release must be
re-verified by the previous pinned release (bootstrapping rule). Tracked in the architecture doc.
