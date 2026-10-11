# Changelog

## Unreleased
- Authorization trust boundary (ADR 0016): the verifier authenticates authorization records through a provider
  registry, enforces an approver registry in the trust policy, scope, validity, supersession and revocation; the
  separate validate_authorization tool is removed. Policy switch to waive authorization removed. Fixes the defect
  that any non-git provider name sufficed for `accepted` (v0.1.0 had no authorization and is unaffected).
- Infra contract conformance kit (contracts/infra/v1) and strict profile validation; schema $ids use the real org.
- Version-keyed toolchain store; scrubbed-environment execution mode (docs/execution-isolation.md).
- Owner acceptance packet for 0.1.0 (releases/0.1.0/ACCEPTANCE-PACKET.md), unsigned authorization template, and
  tools/validate_authorization.py (pinned-owner signed-commit validation). No authorization exists; 0.1.0 stays
  verified-unaccepted.
- 0.1.0 stable candidate (published verified-unaccepted; acceptance needs an owner authorization record):
  environment evidence states non-hermetic scope and limitations (also copied into certification);
  verifier checks the attested build-environment record against the manifest pins; policy requires
  it; workflow publishes by verified state, never implying acceptance. Supported scope is exactly the
  qualified combinations; others fail closed to diagnostic.
- 0.1.0-rc.4 candidate (0.1.0-rc.3 failed at the build-environment gate, see releases/0.1.0-rc.3): tool identity by runtime closure (`closure-verified`; a bare executable digest no
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
