# ADR 0022: Homebrew distribution of the CLI and project-aware setup

Status: Proposed (v0.9.0)

## Problem
Installing the platform on a development machine meant running the trusted installer by hand with seven pins, then
`setup_env.py`, then exporting paths. A package manager makes the CLI easy to get and to upgrade, but a package
manager's checksum is not release provenance, and an upgraded CLI must not move any project to another platform
release (ADR 0002, 0014).

## Decision
1. **A tap, the CLI only.** The public tap `syncom-systems/homebrew-dev-platform` (org convention:
   `homebrew-flight`) carries one formula, `dev-platform`, rendered deterministically from a release identity by
   `tools/homebrew_formula.py`: URL of the immutable release asset, its archive sha256, and a test requiring the
   installed tree to equal the release's tree digest pin. It depends on `gh` and `python@3.14` (stdlib only). It
   installs the release tree byte for byte into `libexec` and a `bin/dev-platform` that runs it with `python -I`.
   No private repository, configuration, credential, runner inventory or policy is packaged or referenced.
2. **The CLI is a launcher.** In a project, `check`, `explain` and (new) `doctor` delegate to the pinned release run
   from a verified snapshot. `brew upgrade` changes the CLI only.
3. **`dev-platform setup`** composes existing mechanisms, no new release management: project discovery; agreement of
   `dev-platform.toml` and `dev-platform.release-pins.json`; for a missing release, the trusted installer, verifier
   and policy from the public repository at the pinned revision, checked against the pinned digests, then the
   pinned `install_release.py` (full verification, admission by the consumer's flags); for a present release, the
   tree digest and the installer's record; the pinned release's own `toolchain verify --require-certifiable` (reuse)
   or `toolchain provision --pinned` plus the same verification; its `doctor`. It only reads the project.
   It supports releases from 0.8.0 (the first with pinned provisioning).
4. **Locations** (`dev_platform.locations`): user-scoped XDG defaults; `DEV_PLATFORM_HOME`, `DEV_PLATFORM_STORE`,
   `DEV_PLATFORM_TOOLCHAINS`, `DEV_PLATFORM_CACHE` and matching flags; in CI a job-local `$RUNNER_TEMP/dev-platform`
   unless a location is named. The cache is never trusted (re-checked against pins on every use).
5. **The interpreter.** Profiles that verify the running interpreter (`{python}`) are verified on the provisioned
   python; `DEV_PLATFORM_PYTHON` (exported by `setup`) makes the launcher re-execute the release on it. It only
   selects: the release verifies the interpreter against its manifest.

## Consequences
- A project's release changes only through its pins; Homebrew cannot reach it. Corrupted or mismatched store entries
  are refused and left in place, never repaired silently.
- The tap is updated by a pull request after each release; its CI verifies the named archive with the trusted
  installer and the formula against the rendering of the release identity before merge.
- The CLI's own provenance rests on the formula review and Homebrew's checksum unless the user also runs the trusted
  installer on the downloaded archive (documented in `docs/homebrew.md`); the CLI never certifies itself.
- Limits: toolchain profiles have sources for darwin-arm64 and linux-x86_64 only; `setup` needs `gh` authenticated
  for installation. CI should keep using job-local installs (`consumer_run.py`, `consumer-pilot.yml`).
