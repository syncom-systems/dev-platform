# Owner acceptance packet: dev-platform v0.3.0 (stable candidate)

State: **verified-unaccepted**. No authorization exists. Nothing here creates, signs or attributes one.
Independent of v0.2.1 (and every other candidate): acceptance is per archive digest. Preserved and not offered: v0.1.0,
v0.1.1, v0.2.0 (see their records). v0.2.1 remains a separate candidate whose owner steps are in
`docs/owner-acceptance-0.2.1.md`.

## 1. Identities
| | |
|---|---|
| **Archive sha256 (authorization subject)** | `eb04ce489f3963ab24ed2e634f3213a4d1eabef87c4d667a7f2aaa040b9c604a` |
| Tree digest (consumer pin) | `2db65de81bfddb53519bbd3a2f8bb1f1184d10044277355abb3f833284dd6724` |
| Tag / revision | `v0.3.0` (annotated, not signature-signed; ruleset 24840008 blocks update/delete) / `6ad52306e72ab3c3ad0ad7023c58015634880d31` |
| Release workflow | run 38164549279; signer `syncom-systems/dev-platform/.github/workflows/release.yml@refs/tags/v0.3.0`, GitHub-hosted |
| GitHub release | immutable, pre-release flag, titled "dev-platform 0.3.0 (verified, NOT accepted)" |
| Attestations | SLSA provenance (archive, build-environment record, continuity record), CycloneDX SBOM |
| Build environment | linux-x86_64, `dev-platform-release`, certifiable, `hermetic: false`, identity digest `a31eef599f21ed869d53a15911593302630a695b1db840e0ba856164029895a6` |
| Predecessor continuity | 0.2.1 (digest-pinned in the policy; verified-unaccepted) re-ran the full stage over this source: admitted, exit 0 |

## 2. Independent verification and trust anchors
`tools/verify_release.py` from `main` with operator pins; expected revision from `git ls-remote` on the tag; archive digest
computed locally. 32/32 checks passed; `verified-unaccepted`; `confers: []`. Records: `verification.independent.json`,
`verification.ci.json`, `continuity.json`, `build-environment.json`, `rejections.txt` (live negatives: invented provider,
never-committed record, wrong revision, appended byte, absent and altered continuity record, installer refusal and wrong
verifier pin).

| Anchor | sha256 |
|---|---|
| `tools/verify_release.py` (unchanged since 0.2.1) | `791713d01198f47045c7abb210e73dd94976d266ed12351cfce53ea9d2b466a9` |
| `trust/policy.json` (`approvers: []`, predecessor 0.2.1) | `9a4e866509f5fe69ab6dbaf1df0733bb163bd5ac1824b893a4743ea40c948c50` |
| `tools/install_release.py` (unchanged) | `473a2c73eb71904ea6ee0e010f2288976126d4560e3efd11c33c11e44f15bb93` |
| `tools/verify_app_release.py` (new: application-release verifier) | `d566e90f9c5a3b2f30a729e34f6fcb02b4ffc5d494fbf52c3834acee8005abd4` |

Re-derive them with `shasum -a 256` from a checkout you trust. The policy pin changes when you add yourself as an approver:
that is expected and is the new anchor you pin. `tools/verify_app_release.py` is not inside the release archive (like
`verify_release.py`); it is fetched from the repository at the tag and must match the pin.

## 3. Implemented capabilities (milestone v0.3.0; ADR 0019)
| Issue | Capability | Evidence |
|---|---|---|
| #52 | Application-release approvals authenticated by an independent verifier that reuses the ADR 0016 provider registry under a pin; application-owned policy `dev-platform.app-trust/v1` (per-application approvers, no wildcard, platform approvers have no authority); approval confers only `application-release-approval` | `tests/test_app_release_verifier.py` (52 tests) |
| #12 | `provenance assemble`: app-release record from a certified result, lock files and artifact digests | `tests/test_provenance.py`; qualification chain |
| #13 | Write-once evidence bundles pinned by one manifest digest, read independently; retention contract; signing = GitHub-verified signed commits. OIDC provider split to #76 | `tests/test_bundle.py`; `docs/provenance-and-governance.md` |
| #14 | `rollback select`: authenticated, bound, unrevoked, advisory-clean, bundled releases only; fails closed without pins | `tests/test_rollback_authenticated.py`, `tests/test_bundle.py` |
| #6 | `dependency-snapshot` + workflow | observed on this repository, below |
| - | Exact binding of source revision, dependency resolution, Dev Platform release (against the application's policy), toolchain identity, result digests and artifact bytes to the release digest the approval names; revocation, supersession, advisory impact | verifier checks; 13-case chain qualification |

Application approval is separate from platform acceptance: the application policy lists the platform releases it accepts
(version and tree digest); whether a platform release was accepted is not an input, and neither decision implies the other.

## 4. Qualification and negative evidence
Qualified by real execution at the tagged revision (CI run 38164541328): profiles `python`, `rust-cargo`,
`rust-cargo-1.99`, `rust-bazel` (Bazel 8.4.2), `rust-bazel-9` (Bazel 9.2.0, rules_rust 0.74.0, rustc 1.97.1) on
linux-x86_64 and darwin-arm64 with the platform's must-be-rejected cases. New: `tools/qualify.py --app-release` runs the
application-release chain over each **real certified result** with 13 accept/reject cases (authenticated approval
`approved`; no approval, unsigned, non-approver, other release, revocation `unapproved`; source pin, manipulated result, missing
evidence, artifact bytes, dependency state, platform not allowed, advisory `failed`): all as expected for the four Rust
profiles on both platforms (`app-release-qualification.json`). The `rust-bazel*` runs execute Bazel only; no Cargo is run
for them (the NGA Bazel-only requirement), and the NGA repository was not touched or reachable (private). Rejection cases
are also unit-tested (`tests/test_app_release_verifier.py`: unsigned or squash-merged commits, edited-after-signing,
invented/authorship providers, wrong application, platform-release owner, scope escalation, wrong subject, future/expired,
revocation by an unauthorized person, equal timestamps, stale/forged/missing evidence, tampered artifact or lock,
platform not in policy, advisories) and for bundles (changed, unlisted, deleted, symlinked, traversal, wrong pin).

Consumer pilot (flight, pinned commit; PR #74 run): the chain is assembled from flight's real result and the verifier returns
`unapproved`, also when a forged unsigned approval is offered (linux `rust-cargo-1.99`); `rust-cargo` and macOS runs
are refused at assembly because the result is not certified. Evidence about adoption friction, not qualification.

Dependency submission (#6): snapshot accepted (run 38164018103); the dependency graph lists uv, ruff, cpython, rust, bazel,
bazelisk; Dependabot alerts 0. Only pypi purls can alert (ruff, uv). A positive alert was not observed.

## 5. Assurance limitations and deviations
- **The authenticated approval path was never exercised against live GitHub.** No application approver exists; the
  positive case and every signature case ran against a recording double at the `gh api` boundary (real verifier code,
  faked GitHub). The live provider code is the one already used for platform records.
- **Not hermetic**, as in 0.2.1 (tool identity is not execution-environment identity; Bazel repository cache, host C
  toolchain and Cargo's host linker are outside the evidence). Release builds ran on linux-x86_64 only.
- Chain qualification used `git archive` of the fixture as a stand-in artifact; the `python` profile's fixture has no lock
  file, so its chain was skipped (reported as such). `--mode select` cannot re-read lock files or artifact bytes and lists
  what it did not evaluate; "no advisories supplied" is reported, not treated as safe.
- The application policy is a trust anchor owned by the application, pinned out of band; an approver's removal ends
  their approvals only when the verifier is re-run. Authenticity depends on GitHub's signature verification at
  verification time. Approver separation of duties (e.g. approver is not the release author) is not enforced.
- Breaking changes declared (0.x minor): `rollback select` now requires pins and bundles (`--unauthenticated`,
  `--allow-unbundled` are labelled diagnostics); the shape validator for authorization records now requires
  `login` and `path` (it previously asked for a `reference` no verifier read) and a `scope.confers` matching the subject kind.
- Acceptance is not certification. Tag `v0.3.0` is not signature-signed (#53). A second identity provider (OIDC) is open (#76).
  Acceptance of 0.2.1, nga adoption phases 2-4 and any security advisory publication remain owner decisions.
- No regulatory-compliance claim is made; retention class durations are the operator's policy.

## 6. What the owner must do (nothing is pre-made)
Authority is separate from authentication. Follow `docs/owner-acceptance-0.2.1.md`, substituting this release:
re-derive the anchors and the verification (command in `README.md`); add yourself as a `platform-release` approver in
`trust/policy.json` with a signed commit (once; it serves every release) and pin the new policy digest; copy
`authorization.template.json` to `authorizations/<name>.json`, fill it and commit with your own signed commit (push or
merge commit; never squash/rebase); run the verifier with `--authorization` and your pins; retain the output. Application
approvers are a separate matter for each application's own policy (ADR 0019); do not add them to `trust/policy.json`.

## 7. Proposed acceptance scope
`platform-baseline` only: accept archive `eb04ce48…` as a platform baseline for the profiles and platforms in section 4,
acknowledging section 5. It does not confer certification, application approval, qualification beyond section 4, approval of any
consumer migration (nga included) or of any other release.
