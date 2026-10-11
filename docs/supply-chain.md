# Supply-chain model for the platform as a dependency

Implemented unless marked *(planned)*.

## What a release carries
`release.json` (identity + toolchain manifest + source digest), `sbom.cdx.json` (CycloneDX 1.5:
platform component with source hash, every tool in every profile with purl/hash where known), both
inside the pinned tree. *(planned)* release attestations: SLSA build provenance and SBOM attestation
from `.github/workflows/release.yml` (untested until the first tag).

## Finding vulnerable releases and consumers
`dev-platform affected --advisory adv.json [--store DIR] consumer...` reads a
`dev-platform.advisory/v1` record (component + exact versions), matches it against every release in
the store (platform version and SBOM components), then reports which given consumer artifacts
(`dev-platform.toml` pin, result, app-release) reference an affected release. Exit 1 if anything is
affected, so it can gate or alert in automation. The fix is a new release (ADR 0010); consumers adopt
it by editing their pin.

## GitHub mechanisms: what they do and do not give us
Researched from GitHub documentation; not yet exercised against this repository.
- **Dependabot alerts** cover dependencies whose ecosystem the GitHub Advisory Database supports.
  A `[platform]` pin in `dev-platform.toml` is not a recognized manifest and `dev-platform` is not an
  advisory-database package, so **no native alert will fire for it**. We do not rely on one.
- **Dependency submission API** accepts snapshots of dependencies not visible in manifests and shows
  them in the dependency graph, but alerts still require a supported ecosystem. `dev-platform dependency-snapshot`
  builds the snapshot from the toolchain manifest (`.github/workflows/dependency-submission.yml` submits it for this
  repository; a consumer runs the same command from its pinned release). It submits the tool components that
  declare a purl (as their real ecosystems, e.g. `pkg:pypi/ruff@0.17.0`), so ecosystem tools such as ruff
  can get native alerts. Only supported purl types can alert; `pkg:generic`/`pkg:github` components appear in the
  graph without alerts. The platform release itself is not submitted (not an advisory-database package).
- **Repository security advisories** on this repo let us publish an advisory for `dev-platform`
  itself *(planned)*; the platform's own `advisory/v1` + `affected` remains the cross-consumer index.
- **Artifact attestations** (Sigstore; verified with `gh attestation verify`) provide provenance
  *(planned, see release-trust.md)*.
- **Dependabot for GitHub Actions** is configured (`.github/dependabot.yml`, weekly, grouped); action
  references are pinned by commit SHA, which Dependabot updates together with the version comment.
  Dependabot alerts and security updates are enabled on the repository, as is CodeQL default setup
  (actions, python, rust).

## Gaps
Tool digests are mostly `version-only` today; consumers' transitive dependency resolution is out of
scope here (it is an input digest to the app-release record).

## Advisory impact analysis (v0.2.0)
`dev-platform.advisory/v1` entries match exact `versions` and/or `ranges` (`>=0.17.0,<0.17.2`; an unparsable
installed version counts as affected). `dev-platform affected --advisory adv.json --impact [--github REPO]
[consumer...]` reports, per affected release, whether a later unaffected release already fixes it
(`upgrade`), whether a patch release on the supported line is needed (`patch-release`, with the next patch
version and the change kinds `security-fix`/`toolchain-patch` for `plan version-check`), or that the line is
unsupported (`no-patch-upgrade`); pre-release versions are ignored; consumers pinned to affected releases are
listed. Output is a proposal: the patch is built and verified through the normal pipeline and acceptance
remains the owner's separate act.

### Advisory process
1. **Report** privately (SECURITY.md; private vulnerability reporting is enabled). Do not open public issues.
2. **Record** it as `advisories/<id>.json` (`dev-platform.advisory/v1`, validated by the test suite).
3. **Analyse** with `dev-platform affected --advisory advisories/<id>.json --impact --github syncom-systems/dev-platform`
   (add `--github-draft` for a draft repository-advisory payload built from the same record).
4. **Plan** the patch on the supported line: open an issue in the patch milestone; `plan version-check` classifies
   the change (`security-fix`, `toolchain-patch`). A toolchain fix is a new release, never an edit of an old one.
5. **Build and verify** through the normal pipeline (release.yml, independent verification). The patched release
   is `verified-unaccepted` until the owner's separate authorization.
6. **Publish the repository advisory** (owner action: it is outward-facing); consumers pinned to affected releases
   are found with `affected` against their configs/results.
An unauthenticated report may *suspend* use of a release (lifecycle warning) but is not a governance decision
(ADR 0017).
