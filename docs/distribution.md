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

## Bootstrap contract and upgrading the CLI

The CLI is the bootstrap: it verifies a project's pinned release and runs it from a verified snapshot, and nothing more
([ADR 0026](adr/0026-stable-bootstrap-contract.md)). It does not validate the release's record or toolchain manifest;
the release does that itself when it runs, whatever manifest features it uses. So a project's ability to install its
pinned release does not depend on the age of the installed CLI, and a CLI upgrade never changes a project's release.

| Situation | What happens |
|---|---|
| Fresh machine | install the CLI (`brew install syncom-systems/dev-platform/dev-platform`, or the trusted installer for the CLI release, [installation](installation.md)); `dev-platform setup` in the project installs and verifies the pinned release, provisions its profile |
| CLI 0.15.0 or later, any pinned release from 0.8.0 | the release is installed with its own pinned trusted installer, verified, run from a snapshot; releases from 0.15.0 prepare their own environment (`toolchain prepare`, contract 1), earlier ones are driven through the same function over their manifest |
| Different projects, different releases | each runs its own verified release and toolchain directory; releases and toolchains coexist in the store |
| Rollback | revert the pin change; the earlier release is still in the store (`release: present`) |

**Transition from CLIs up to 0.14.0.** Those CLIs validate a release's record and manifest with their own bundled schema
before running it, are published and immutable, and therefore reject a release that uses features they do not know
(0.12.1 and 0.13.0 report `invalid release: toolchain manifest: ...`; 0.14.0 reports `release X is newer than this
dev-platform CLI`). They cannot be changed. The one-time step is to install a CLI of 0.15.0 or later:
`brew update && brew upgrade dev-platform`, or install the CLI release with the trusted installer
([installation](installation.md)); no manual change of Homebrew directories or the release store is needed.
Installed releases, toolchains, caches and project pins are valid as they are and are reused (`release: present`,
`toolchain: reused`). Setup never runs `brew` and never changes a pin. After that step no later release's schema
can strand the CLI; a future change of the bootstrap contract itself is a release-readiness blocker until a migration
path is published (`trust/bootstrap-compat.json`).

A release at 0.15.0 or later that declares a bootstrap contract the CLI does not implement is refused before anything of
it runs: `release X requires bootstrap contract N; ... install a newer CLI`.

## Release discipline

Tag `vX.Y.Z` only from a commit where `dev-platform check --stage full` is certified; the release
notes record the tree digest. Config `schema_version` and result/infra `schema` strings change only
with a major bump and a documented migration.
