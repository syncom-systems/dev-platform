# Changelog

## Unreleased
- `dev-platform toolchain prove-bazel-rust` (#111): evidence that Bazel compiles with the declared Rust toolchain, not a host
  installation: Rustc action paths via external repositories, version equals the `MODULE.bazel` declaration, decoy host
  `rustc`/`cargo` never executed in a forced re-execution. Runs Bazel and the Bazel-provided `rustc --version` only (no
  Cargo). Part of the rust-bazel qualification on linux and darwin.
- Deterministic provisioning (#112): `toolchain provision --pinned --verify` realizes the pinned release's profile and verifies it
  against the same manifest in one step (exit 1 unless conformant and certifiable); the identity digest is identical for repeated
  clean provisioning (qualified in the pilot).
- Consumer evidence (#113): `tools/verify_consumer_evidence.py` (independent) checks a result record against the consumer's own
  pins (platform version/tree digest/profile, infra pin, Bazel Rust proof); `tools/consumer_run.py` and the reusable workflow
  `.github/workflows/consumer-pilot.yml` select the pinned release from public data only, provision, execute and verify; the
  pilot gains the public Bazel reference consumer (`fixtures-real/rust-bazel-9`) and attests the evidence bundle.
  `docs/consumer-integration.md` is the runbook (NGA phase 2 stays the owner's decision).
- Consumer-owned infrastructure configuration pin (ADR 0021, #99, #110): `[infra] provider/config_release/config_digest`
  in `dev-platform.toml`; the engine refuses any resolved identity that differs from the pin; untrusted events never call a
  provider and use only a vendored profile whose sha256 equals the pin; trusted events may use an operator-supplied
  resolver. The result record gains `infra`. `dev-platform infra digest` and `infra check-resolution`; conformance cases in
  `contracts/infra/v1/resolution-cases.json`. Breaking for 0.x: an infra profile without a pin is `unpinned` (not used).

## 0.7.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- New authorization provider `github-environment-approval` (ADR 0020): the owner accepts a platform release by approving a run
  of the manual `accept` workflow on the `owner-approval` environment; the workflow attests the resulting record and
  `verify_release.py` verifies it. Trust anchor change (new `verify_release.py` digest); `github-signed-commit` unchanged.

## 0.6.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- A current authorization state that cannot be established is its own result, `indeterminate` (exit 5), no longer folded
  into `failed` (breaking for 0.x consumers that matched `failed`): `approval.authorization_state`
  (`authorized`|`unauthorized`|`indeterminate`|`historical`|`not-established`), coded `currency.reasons`, and the same
  per-candidate `authorization_state` in `rollback select` rejections. `unapproved` keeps meaning the state was read
  and nobody authorizes the release; a defective release stays `failed`.
- Scalable evidence-history audit: up to 10 000 commits are listed (was 500 audited one by one);
  `--audit-state DIR` (verifier, `verify_platform_current.py`, `rollback select`) reuses per-commit facts between runs
  and candidates, saves progress when a run exceeds its budget (`audit-incomplete`), and notices a rewritten history
  (`history-rewritten`). The state caches immutable commit facts only; outcomes with and without it are identical.
- Recovery from deleted records: restore by an approver, or list the removal in the pinned application policy
  (`authorization.acknowledged_removals`); an acknowledged record is read from before its deletion and still counts.
- `docs/owner-acceptance-0.2.1.md` split into agent-executable and owner-only parts.

## 0.5.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Authorization freshness is mandatory (ADR 0019 item 12; breaking for 0.x). `tools/verify_app_release.py` defaults to
  the `operational` purpose: every record in the policy's evidence repository is read at one commit and judged, the
  history is audited for deleted records, and the result is `failed` when the current state cannot be established.
  `--discover-authorizations` is removed (it is no longer optional). `--historical` is the explicit inspection
  purpose: it never yields `approved` (it yields `historical-approval`, exit 4). Records carry `currency`
  (`observed_at`, `valid_until`, evidence commit); `AppVerifier` rejects an `approved` record that is not a fresh
  current-state one. Policy `freshness.max_age_seconds` (default 300).
- Platform acceptance required by an application policy is read as current state too; new
  `tools/verify_platform_current.py` answers "is this platform release currently accepted?" without changing
  `tools/verify_release.py` (the trust anchor).
- Test and qualification doubles model one repository (history, trees, deletions); new end-to-end negative cases:
  a revocation published independently of an old bundle, outage, deleted record, ref moving while read.

## 0.4.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Application policies may require an owner-accepted Dev Platform release (`require_acceptance` +
  `archive_sha256` + `source_revision` in `platform_releases`; schema-added, optional). `verify_app_release.py` and
  `rollback select` re-run the platform verifier (`--platform-*`) and add the `platform-acceptance` check; application
  and platform authority stay separate.
- `--discover-authorizations` (verifier and `rollback select`): records in the evidence repository are judged too, so
  a revocation missing from a bundle still counts. `rollback select` rejections now carry the authorization evidence.
- Qualification: Python profile application-release chain over a hash-locked dependency (`fixtures-real/python-locked`,
  zipapp built with `pip --require-hashes`); rollback refusal suite through the complete bundle/CLI/verifier path
  (`tools/qualify_rollback.py`); live GitHub signature/history qualification against a controlled fixture repository
  (`tools/qualify_live.py`; never reaches `approved`, see ADR 0019 item 13). 0.3.0's qualification claims are unchanged.
- Predecessor continuity: 0.3.0 (digest-pinned in the policy; verified-unaccepted) re-runs the full stage over this source.

## 0.3.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Application-release approval trust (ADR 0019, #52): `tools/verify_app_release.py` (independent, reuses the ADR 0016
  provider registry under a pin) authenticates application approvals, enforces an application-owned policy
  (`dev-platform.app-trust/v1`), binds source/dependencies/platform/toolchain/evidence/artifacts to the exact release
  digest, and handles revocation, supersession and advisories. `rollback select` now requires the pinned verifier
  (`--unauthenticated` is a labelled diagnostic). Shape validator aligned with the verified assertion shape.
- Immutable evidence bundles (`dev-platform evidence bundle|bundle-verify`, `verify_app_release.py --bundle`), retention
  contract, `rollback select --bundle`; qualification `--app-release` rejection cases over real results; pilot assembles
  and refuses to approve (flight). Stray `uv.lock` removed.
- Owner steps for formal acceptance of 0.2.1: `docs/owner-acceptance-0.2.1.md` (nothing pre-made).
- Dependency submission (#6): `dev-platform dependency-snapshot` and a workflow submit toolchain tool components to GitHub's
  dependency graph; observed on this repository: accepted, components listed, 0 alerts (only pypi purls can alert).
- Predecessor continuity: 0.2.1 (digest-pinned in the policy; verified-unaccepted) re-runs the full stage over this source.

## 0.2.1 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Installer consumes the predecessor-continuity record (found by independent verification of 0.2.0, whose tag's
  installer could not install it). 0.2.0 is retained verified-unaccepted and superseded.

## 0.2.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Declared host requirements (#60): `[[host]]` in dev-platform.toml, recorded in environment evidence (gates
  conformance, never raises assurance). New profiles `rust-cargo-1.99` and `rust-bazel-9` (qualified in CI).
  `toolchain provision [--pinned]`; `init` derives checks from build markers; `infra check|event-trust`;
  consumer pilot harness (flight); docs: infra integration, consumer quickstart, nga pilot plan.
- Advisory impact analysis (#7): version ranges, severity enum, `affected --impact [--github REPO]` with fix/patch/
  upgrade actions per release and pinned consumers. Proposals only.
- Predecessor continuity (#4): `tools/run_continuity.py`, `dev-platform.continuity/v1`, `continuity` check in the
  verifier, release workflow jobs `continuity`/`attest-continuity`; policy pins v0.1.2 as predecessor. Evidence only.
- ADR 0018: single admission policy contract. `runners.event_trust` (normative), optional `admission` section in
  `dev-platform.infra/v1`, `dev-platform pr-check` (violations / incomplete / indicators), conformance cases.
- Lifecycle: unauthenticated notices only suspend (warning); revocation is read from the pinned verifier's
  authenticated evidence. `plan queue`: milestone priority is not an exclusive queue.
- Release planning (ADR 0017): `dev-platform plan` (readiness, assign, version-check, patches, notes, manifest,
  state), `planning/release-policy.json` (versioning policy, assurance profiles), lifecycle state machine with no
  edge to `accepted` (observed only from a run of the pinned verifier), `release-plan.yml` (assign/report only),
  release milestones v0.1.3/v0.2.0/v0.3.0 and a Project; M1-M6 retired. v0.1.2 stays verified-unaccepted.
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
