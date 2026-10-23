# Distribution design

Status: the store layout, digest pin, verified-snapshot launcher, release build (toolchain manifest + SBOM) and override rules are **implemented**. Supersedes the earlier "release = source tree" design (ADR 0010, 0011, 0014).
Everything marked *(planned)* is design only.

## Artifacts

| Artifact | Form | Integrity |
|---|---|---|
| Platform release | immutable directory: `src/`, `release.json` (toolchain profiles), `sbom.cdx.json`; built by `dev-platform release build` | sha256 tree digest pinned by consumers; provenance, SBOM and build-environment attestations from `release.yml`, verified by the trusted installer ([release trust](release-trust.md)) |
| Launcher | the same package; entry point `dev-platform` | Homebrew tap `syncom-systems/homebrew-dev-platform` (since 0.9.0, [homebrew.md](homebrew.md), [installation](installation.md)): formula sha256 = archive digest, test = tree digest; `dev-platform setup` installs a project's pinned release with the trusted installer |
| Reusable GitHub workflow | `.github/workflows/consumer-pilot.yml` (`workflow_call`; [consumer integration](consumer-integration.md)). `check.yml` is an unfinished placeholder that fails closed (no bootstrap): do not use it | consumers reference it by full commit SHA, never a branch or floating tag |
| Skills / Claude Code plugin | *(planned)* `integrations/` directory in the same release | covered by the same release digest |

## Store

`$DEV_PLATFORM_STORE`, else `$DEV_PLATFORM_HOME/versions`, else `${XDG_DATA_HOME:-~/.local/share}/dev-platform/versions/<version>/src/dev_platform/`
(toolchains and cache: [homebrew.md](homebrew.md#locations)).
Versions are write-once; a different digest for an existing version is an error. The launcher
reads only. Digest rules: sorted relative paths + contents, `__pycache__`/`*.pyc` excluded,
symlinks rejected.

## Consumer flow

1. `dev-platform init --platform-version X --profile P --sha256 D` writes the pin (version, digest, toolchain profile).
2. CI uses the reusable `consumer-pilot.yml` at the pinned release's commit: it installs version X with the trusted
   installer into a job-local store, checks D, provisions the toolchain and runs `dev-platform check --stage full`
   ([installation](installation.md#7-ci-job-local-installation-no-homebrew)).
3. Upgrading = editing version + digest in a reviewed PR.

## Upgrading the CLI

The CLI is only the launcher: it validates the pinned release's record and toolchain manifest with its own rules before
anything of the release runs. A release that uses a format an older CLI does not know (0.13.0 added profile `bazel`
sections, `rust-components` sources and `bound_to` tools) cannot be validated by that CLI. CLIs up to 0.12.1 report this
as `invalid release: toolchain manifest: ...`; they are published and are not changed. From 0.14.0 the CLI compares the
pinned version with its own and, when the pin is newer, says so: `release X is newer than this dev-platform CLI (Y) ...
upgrade the CLI`, with the validation result appended, and still executes nothing.

Upgrade path: `brew update && brew upgrade dev-platform` ([homebrew.md](homebrew.md#upgrade-pin-roll-back)), or install the
CLI release you need with the trusted installer ([installation](installation.md)). Validation is unchanged, a newer CLI
validates every older release as before, and project pins, installed releases and CI (`consumer-pilot.yml` runs at the
pinned release's own commit) are not affected.

## Release discipline

Tag `vX.Y.Z` only from a commit where `dev-platform check --stage full` is certified; the release
notes record the tree digest. Config `schema_version` and result/infra `schema` strings change only
with a major bump and a documented migration.
