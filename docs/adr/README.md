# Architecture decision records

Status values: **Ratified** (required by the founding mission; changing it needs explicit owner
sign-off) and **Proposed** (a design choice made to deliver the first vertical slice; open to
revision). Superseded records stay in place.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-public-core-private-infrastructure.md) | Public core, private infrastructure | Ratified |
| [0002](0002-immutable-versions-and-pinning.md) | Immutable side-by-side versions and pinning | Ratified (amended by 0010) |
| [0003](0003-version-selection-and-overrides.md) | Version selection, overrides and self-hosting | Superseded in part by 0014 |
| [0004](0004-adapters-and-declared-requirements.md) | Adapters; discovered facts versus declared requirements | Ratified |
| [0005](0005-logical-runners-and-trust-routing.md) | Logical runner requirements and trust-based routing | Ratified |
| [0006](0006-verification-semantics.md) | Verification semantics: obligation is independent of cost | Ratified |
| [0007](0007-agent-independence.md) | Agent independence | Ratified |
| [0008](0008-implementation-language-and-config-format.md) | Implementation language and configuration format | Proposed |
| [0009](0009-distribution-and-integrity.md) | Distribution and integrity | Superseded by 0011, 0014 |
| [0010](0010-unified-platform-and-toolchain-releases.md) | Unified platform and toolchain releases | Ratified |
| [0011](0011-supply-chain-dependency-model.md) | Supply-chain dependency model | Ratified |
| [0012](0012-application-release-provenance.md) | Application release provenance | Ratified |
| [0013](0013-governance-and-auditability.md) | Governance and auditability | Ratified |
| [0014](0014-release-trust-bootstrap-and-execution.md) | Release trust, bootstrap and verify-then-execute | Ratified |
| [0015](0015-closure-identity-and-trust-base.md) | Closure identity, SBOM correspondence and the verification trust base | Ratified (owner directive, turn 4) |
| [0016](0016-authorization-trust-boundary.md) | Authorization trust boundary | Superseded by 0024 for platform releases (ratified 2026-10-11) |
| [0017](0017-release-lifecycle-and-planning.md) | Release lifecycle and GitHub-native planning | Proposed |
| [0018](0018-admission-policy-single-contract.md) | One admission policy contract; the PR checker evaluates, it does not decide | Proposed |
| [0019](0019-application-release-approval-trust.md) | Application-release approval trust | Proposed |
| [0020](0020-environment-approval-provider.md) | GitHub Environment approval as an authorization provider | Superseded by 0024 for platform releases |
| [0021](0021-consumer-pins-and-infra-resolution.md) | Consumer-owned pins and infrastructure resolution | Proposed |
| [0022](0022-homebrew-cli-and-project-setup.md) | Homebrew distribution of the CLI and project-aware setup | Proposed |
| [0023](0023-infrastructure-capabilities-in-the-public-platform.md) | Generic infrastructure capabilities in the public platform; organization data stays private | Proposed |
| [0024](0024-single-owner-release-authority.md) | Single-owner release authority: verified releases, no approval records | Proposed |
| [0025](0025-platform-owned-bazel-configuration.md) | Platform-owned Bazel configuration for Rust and Python | Proposed |
