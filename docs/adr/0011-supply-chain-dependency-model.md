# ADR 0011: Supply-chain dependency model

Status: Ratified (mechanisms Proposed; see [supply-chain.md](../supply-chain.md))

Supersedes [ADR 0009](0009-distribution-and-integrity.md).

- The platform is a security-trackable dependency. Every release ships a CycloneDX SBOM
  (`sbom.cdx.json`, digest bound in `release.json`), the toolchain manifest, and (from the release
  workflow) Sigstore build-provenance and SBOM attestations.
- Vulnerability handling does **not** assume GitHub-native alerts: Dependabot alerts require packages
  in a GitHub Advisory Database ecosystem, and a custom `dev-platform.toml` pin is not one. The
  platform provides its own `dev-platform.advisory/v1` records and `dev-platform affected`, which
  maps an advisory to affected releases (via SBOM and platform version) and to consumers (via pin,
  result or app-release records). GitHub integration is additive: dependency-submission snapshots and
  repository security advisories (see supply-chain.md).
