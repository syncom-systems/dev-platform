# Changelog

## Unreleased
- 0.1.0-rc.3 candidate: tool identity by runtime closure (`closure-verified`; a bare executable digest no
  longer certifies), pinned hash-locked release-profile environment, SBOM correspondence and SBOM
  attestation verification, trusted installer (`tools/install_release.py`), real Bazel/rules_rust and
  CPython qualification in CI, Bazel binary pinned and enforced at execution, Dependabot for Actions and
  pip, immutable-release probe and post-publish assertion. ADR 0015.
- 0.1.0-rc.2 pre-release: first fully verified pipeline run (see releases/0.1.0-rc.2).
- 0.1.0-rc.1 pre-release: first exercise of the release pipeline (never accepted; see docs/release-trust.md).
- Revision 2: releases are environments (toolchain manifest + profiles + SBOM, `release build|verify`);
  environment verification recorded in results (`environment`, breaking pre-release change to
  `dev-platform.result/v1`); verified-snapshot launcher closes the verify/exec race; self-hosted
  results are no longer certifiable; `platform.profile` is required in pins; app-release,
  authorization and advisory record contracts with `validate` and `affected`; ADRs 0010-0014
  (supersede 0009, part of 0003).
- Foundation: config schema v1, result schema v1, infra profile v1, launcher with digest-pinned
  releases, detection, selection and evidence state machine, adapters (bazel, python, cargo, exec),
  logical runner routing, CLI (init, detect, doctor, explain, check, digest), ADRs 0001-0009.
