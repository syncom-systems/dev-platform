# Distribution design

Status: the store layout, digest pin, verified-snapshot launcher, release build (toolchain manifest + SBOM) and override rules are **implemented**. Supersedes the earlier "release = source tree" design (ADR 0010, 0011, 0014).
Everything marked *(planned)* is design only.

## Artifacts

| Artifact | Form | Integrity |
|---|---|---|
| Platform release | immutable directory: `src/`, `release.json` (toolchain profiles), `sbom.cdx.json`; built by `dev-platform release build` | sha256 tree digest pinned by consumers; *(planned)* Sigstore/SLSA attestations from `release.yml` |
| Launcher | the same package; entry point `dev-platform` | bootstrap script *(planned)*: fetch release archive by version, verify the pinned digest **before** unpacking into the store |
| Reusable GitHub workflow | `.github/workflows/check.yml` (`workflow_call`) | consumers reference it by full commit SHA, never a branch or floating tag |
| Skills / Claude Code plugin | *(planned)* `integrations/` directory in the same release | covered by the same release digest |

## Store

`$DEV_PLATFORM_STORE` or `$XDG_DATA_HOME/dev-platform/versions/<version>/src/dev_platform/`.
Versions are write-once; a different digest for an existing version is an error. The launcher
reads only. Digest rules: sorted relative paths + contents, `__pycache__`/`*.pyc` excluded,
symlinks rejected.

## Consumer flow

1. `dev-platform init --platform-version X --profile P --sha256 D` writes the pin (version, digest, toolchain profile).
2. CI uses the reusable workflow, which installs version X, checks D, then runs
   `dev-platform check --stage pre-merge --base origin/<default>`.
3. Upgrading = editing version + digest in a reviewed PR.

## Release discipline

Tag `vX.Y.Z` only from a commit where `dev-platform check --stage full` is certified; the release
notes record the tree digest. Config `schema_version` and result/infra `schema` strings change only
with a major bump and a documented migration.
