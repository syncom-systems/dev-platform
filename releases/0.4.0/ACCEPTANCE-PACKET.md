# Owner acceptance packet: dev-platform v0.4.0 (stable candidate)

State: **verified-unaccepted**. No authorization exists. Nothing here creates, signs or attributes one. Independent of
v0.2.1 and v0.3.0 (still separate verified-unaccepted candidates; their records are unchanged): acceptance is per archive digest.

## 1. Identities
| | |
|---|---|
| **Archive sha256 (authorization subject)** | `91d81005dbd5dc082fb6ebed37ebc2a7173a7e336feb2a25764a8d5ee2daeb2e` |
| Tree digest (consumer pin) | `7a79d87580a4928f10337963602075ea133c8f8244dc99959d473f758d801931` |
| Tag / revision | `v0.4.0` (annotated, not signature-signed; ruleset blocks update/delete) / `ea477c86d0dd388a6a7d93c87366a9931ad46a23` |
| Release workflow | run 38179791647; signer `syncom-systems/dev-platform/.github/workflows/release.yml@refs/tags/v0.4.0`, GitHub-hosted |
| GitHub release | immutable, pre-release flag, titled "dev-platform 0.4.0 (verified, NOT accepted)" |
| Attestations | SLSA provenance (archive, build-environment record, continuity record), CycloneDX SBOM |
| Build environment | linux-x86_64, `dev-platform-release`, certifiable, `hermetic: false`, identity digest `a31eef599f21ed869d53a15911593302630a695b1db840e0ba856164029895a6` |
| Predecessor continuity | 0.3.0 (digest-pinned in the policy; verified-unaccepted) re-ran the full stage over this source |

## 2. Independent verification and trust anchors
`tools/verify_release.py` from `main` with operator pins; revision from `git ls-remote` on the tag; archive digest computed
locally. 32/32 checks passed; `verified-unaccepted`; `confers: []`. Records: `verification.independent.json`,
`verification.ci.json`, `continuity.json`, `build-environment.json`, `rejections.txt` (live negatives: invented provider,
never-committed record, wrong revision, appended byte, continuity record absent and altered).

| Anchor | sha256 |
|---|---|
| `tools/verify_release.py` (unchanged since 0.2.1) | `791713d01198f47045c7abb210e73dd94976d266ed12351cfce53ea9d2b466a9` |
| `trust/policy.json` (`approvers: []`, predecessor 0.3.0) | `0e7cf3e643fee6c12a44966f9fe24ffe2ecd795d0a8f40894c41c9aa08c13e25` |
| `tools/install_release.py` (unchanged) | `473a2c73eb71904ea6ee0e010f2288976126d4560e3efd11c33c11e44f15bb93` |
| `tools/verify_app_release.py` (changed: platform-acceptance requirement, authorization discovery) | `6c4b5d78bfe16675d8513f5d227f21ce1d1d69714d6122c6c9f603a46a3199c4` |

The policy pin changes when you add yourself as an approver; that is expected and is the new anchor you pin.
`tools/verify_app_release.py` is not inside the release archive; fetch it at the tag and match the pin.

## 3. What changed (milestone v0.4.0; version policy: minor, schema-added and tool-added)
| Issue | Capability | Evidence |
|---|---|---|
| #80 | Python profile application-release chain over a real hash-locked dependency (`six==1.16.0`, `--require-hashes`) and a zipapp artifact built from it; a wrong lock hash is refused at install | `qualification/python-*.json` (15 chain cases each) |
| #81 | Optional application policy requirement that the Dev Platform release be owner-accepted (`require_acceptance`, `archive_sha256`, `source_revision`): the verifier re-runs the platform verifier, adds the check `platform-acceptance`; application and platform authority stay separate (a platform approval cannot approve an application and the reverse) | `tests/test_app_release_verifier.py` (`RequiredPlatformAcceptance`); live: `platform-acceptance-required.txt` (the real 0.3.0 archive is `verified-unaccepted`, so the policy refuses it) |
| #82 | Rollback refusals through the complete evidence path (bundle, pinned CLI, verifier subprocess): revoked, superseded, advisory against the application, advisory against the platform release, tampered bundle, unsigned, edited after signing, non-approver, unbundled release, missing verification evidence, missing pins, wrong verifier pin; `--discover-authorizations` makes a revocation that no bundle contains count | `qualification/*.json` `app_release.rollback` (15 cases, every profile, linux and darwin) |
| #79 (open) | Live GitHub signature and commit-history path against a controlled private fixture repository, identity `github-actions[bot]` only | `live-qualification.json` (8 cases) |

## 4. Qualification (CI run 38179786582 at the tagged revision)
All five profiles (`python`, `rust-cargo`, `rust-cargo-1.99`, `rust-bazel`, `rust-bazel-9`) on linux-x86_64 and darwin-arm64:
certified, platform negative cases rejected, chain cases and rollback cases all as expected (`qualification/INDEX.json`
lists each file with its sha256). `rust-bazel*` execute Bazel only; no Cargo is run for them. The NGA and flight repositories
were not modified. v0.3.0's qualification claims are not widened by these records; they are additional evidence for 0.4.0.

## 5. Limitations (read these)
- **Live GitHub never reaches `approved`.** GitHub signs records committed through its API with its own key and names `web-flow`
  as committer; the verifier requires author == committer == the approver, so those records are refused (observed live and
  recorded). A positive live approval needs a second GitHub identity with its own registered signing key. None exists; creating
  one (and its authority over any application) is an owner decision. The positive case is exercised only against a recording
  double at the `gh` executable (`tools/qualify_rollback.py`, real verifier and CLI code). No personal account was used or
  impersonated; the fixture repository is private and holds no application.
- The live record is reproducible only with read access to the private fixture repository; CI does not run it.
- Platform-acceptance requirement: one platform archive per run; candidates built with another platform release fail closed.
  The requirement has been exercised live only against a release that is not accepted (refusal); the accepted path is unit-tested
  with a fake `gh`, since no accepted platform release exists.
- Discovery is opt-in. Without `--discover-authorizations` a stale bundle shows its old approval (qualified and stated).
- Python chain: the zipapp is built with `pip --require-hashes` from PyPI at qualification time; artifact bytes are not
  reproducible across platforms. Not hermetic (as before); release builds ran on linux-x86_64 only.
- Breaking changes: none declared (optional fields and flags only). `trust/policy.json` changed only in the continuity
  predecessor (evidence, no authority); approvers remain empty.
- Acceptance is not certification. Tag `v0.4.0` is not signature-signed (#53). OIDC provider open (#76). Acceptance of any
  release, nga adoption phases 2-4 and advisory publication remain owner decisions. No regulatory-compliance claim is made.

## 6. What the owner must do (nothing is pre-made)
As in `releases/0.3.0/ACCEPTANCE-PACKET.md` section 6 and `docs/owner-acceptance-0.2.1.md`, substituting this release's
identities: re-derive anchors and verification, add yourself as `platform-release` approver in `trust/policy.json` with a
signed commit, copy `authorization.template.json` to `authorizations/<name>.json`, commit with your own signed commit
(push or merge commit; never squash/rebase), run the verifier with your pins, retain the output.

## 7. Proposed acceptance scope
`platform-baseline` only, for archive `91d81005…` and the profiles and platforms in section 4, acknowledging section 5. No
certification, application approval, consumer migration or approval of any other release.
