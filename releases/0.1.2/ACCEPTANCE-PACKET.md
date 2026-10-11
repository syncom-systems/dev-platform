# Owner acceptance packet: dev-platform v0.1.2 (corrected candidate)

State: **verified-unaccepted**. No authorization exists. Nothing here creates, signs or attributes one. v0.1.0 and
v0.1.1 are preserved unchanged and are not offered for acceptance (v0.1.0: verifier defect, see ADR 0016; v0.1.1:
failed publish gate, see `releases/0.1.1/ATTEMPT.md`).

## 1. Identities
| | |
|---|---|
| **Archive sha256 (authorization subject)** | `d8aee29970935783889b33c89c10ed5c017357a105a227db1bd90390b654a24d` |
| Tree digest (consumer pin) | `acd586da441c8bca8249342778f1261b1974ddbd4b9105d66ff43fe188395f3e` |
| Tag / revision | `v0.1.2` (annotated, not signature-signed; ruleset 24840008 blocks update/delete) / `c80891bd646622213bc8a5cf3a7eca32dc305cfc` |
| Release workflow | run 38136676056; signer `syncom-systems/dev-platform/.github/workflows/release.yml@refs/tags/v0.1.2`, GitHub-hosted |
| GitHub release | immutable (`gh release verify` and `verify-asset` pass), pre-release, titled "verified, NOT accepted" |
| Attestations | SLSA provenance (archive + build-environment record), CycloneDX SBOM |
| Build environment | linux-x86_64, profile `dev-platform-release`, certifiable, `hermetic: false`, identity digest `a31eef599f21ed869d53a15911593302630a695b1db840e0ba856164029895a6` (CPython 3.14.7 closure `520d9d6e…`, ruff 0.17.0 closure `4ca9f3d9…`, both closure-verified) |
| Manifest profiles | `dev-platform`, `dev-platform-release`, `python`, `rust-bazel`, `rust-cargo` |
| Rehearsal | 0.1.2-rc.1 (separate artifact, `releases/0.1.2-rc.1/`) |

## 2. Independent verification and trust anchors
`tools/verify_release.py` from `main`, run with operator-supplied pins; expected revision from the git tag; archive digest
computed locally. 27/27 checks passed; state `verified-unaccepted`; `confers: []`. Records: `verification.independent.json`,
`verification.ci.json`, `build-environment.json`, `rejections.txt`.

| Anchor | sha256 | Re-derive |
|---|---|---|
| `tools/verify_release.py` | `65b12b916ad1d3c780502b8ee66cba1e2a847c7e98514b2c1e24b94ccbfb48ff` | `shasum -a 256` |
| `trust/policy.json` (current, `approvers: []`) | `16e3af81d11bf7588b3098f4f230572e3ae0d2ac71bc6b1b5679bfcbe90837aa` | `shasum -a 256` |
| `tools/install_release.py` | `7e98915b33294c9f97ad734e4f8127667e9b45a856921429d82bbba8ca08e93e` | `shasum -a 256` |

Do not copy these from this file; compute them from a checkout you trust. **The policy pin changes when you add yourself
as an approver (section 6); that is expected and is the new trust anchor you pin.**

## 3. Supported and unsupported combinations
Qualified by real execution at the tagged revision (CI run 38136531273, `qualify` matrix incl. must-be-rejected cases):

| Profile | linux-x86_64 | darwin-arm64 |
|---|---|---|
| `python` | supported | supported |
| `rust-bazel` | supported | supported |
| `rust-cargo` | supported | supported |

Unsupported, certification fails closed to `diagnostic`: Python-in-Bazel (`rules_python`), mixed projects, Linux aarch64,
Windows, any unpinned tool or platform. (Change from v0.1.0: `rust-cargo` is now in the manifest and qualified.)

## 4. Assurance limitations
- **Not hermetic.** Tool identity is not execution-environment identity: system libraries are trusted by name or prefix,
  not content; host kernel, CPU, filesystem and loader are outside the evidence (stated in every environment record and
  certification). Bazel runs also leave the repository cache, host C toolchain and fetch-time network outside it; Cargo
  runs leave the host linker outside it.
- Release builds ran on linux-x86_64 only.
- `--isolate-env` (scrubbed environment variables) exists but is environment-variable isolation only, qualified for the
  `python` profile only, and is not required for certification.
- Acceptance is not certification; certification is a property of a consumer's check result.

## 5. Security findings and deviations
Alerts at time of writing: code scanning 0, Dependabot 0, secret scanning 0 open. Dependabot PR #28 (action bumps incl.
attestation actions) is unmerged on purpose.

Resolved since v0.1.0: the verifier now authenticates approvals (ADR 0016); the policy can no longer waive authorization;
unknown providers fail closed; negative tests cover unsigned records, invented providers, unauthorized signers, wrong
subject/digest, post-signing edits, revoked/superseded records, missing/over-broad scope, validity, and the installer path.

Outstanding:
1. Tag `v0.1.2` is not signature-signed.
2. Authenticity relies on GitHub's signature verification and account binding at verification time; a later key revocation
   does not alter an earlier verification record. The `github-signed-commit` check lists a path's history on `main`
   (up to 99 commits) and requires every commit on it to be the approver's signed commit.
3. Application-release approvals (`rollback select`) are shape-checked only and reported `approval_authentication:
   unverified`; they are not authenticated yet.
4. The `install_release.py` archive-digest default (derive from local file) still relies on the attestation for binding;
   pass `--archive-sha256` from your own record.
5. Predecessor-continuity rule (issue #4) unimplemented; no predecessor is trusted.
6. The publish gate's bounded retry for the release attestation was exercised on this run (first attempt "not yet
   available", then success).
7. 0.1.1's release object exists and is immutable; it cannot be removed. Do not use it.

## 6. What the owner must do (nothing is pre-made)
Authority is separate from authentication: a valid signature identifies you; the pinned policy decides whether you may
approve. The policy ships with no approvers.
1. Review this packet and re-derive the anchors and the verification yourself (reproduction command in `README.md`
   style: `python3 tools/verify_release.py <archive> --version 0.1.2 --source-revision c80891bd… --archive-sha256
   d8aee299… --policy trust/policy.json --environment <env.json>`).
2. Add yourself as an approver in `trust/policy.json` (`authorization.approvers`: `id`, `provider:
   github-signed-commit`, your GitHub `login`, `roles`, `may_approve: ["platform-release"]`, `may_confer:
   ["platform-baseline"]`) with your own GitHub-verified signed commit; pin the resulting policy sha256 out of band.
3. Fill `authorization.template.json` and commit it to `authorizations/<name>.json` with your own signed commit
   (push or merge commit; a squash or rebase merge makes GitHub the committer and the record is ignored).
4. Run the verifier with `--authorization <file>` and your pins. It reports `accepted` only if the record is authenticated
   (valid signature, author = committer = your login on every commit that touched the path), you are a listed approver,
   the digest matches, scope is `["platform-baseline"]`, and it is in force. Retain that output under `releases/0.1.2/`.

## 7. Proposed acceptance scope
`platform-baseline` only: accept archive `d8aee299…` as the first stable platform baseline for the combinations in
section 3, acknowledging sections 4 and 5. It does **not** confer certification, qualification beyond section 3, approval
of any consumer migration, or approval of any other release. The verifier prints these exclusions in `not_conferred`.
No production consumer migration is authorized by acceptance.
