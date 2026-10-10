# Owner acceptance packet: dev-platform v0.1.0

Status of the release at the time of writing: **verified-unaccepted**. No owner authorization exists. This packet
does not create, sign or attribute one. The published artifact, tag, attestations and verification records are
unchanged by it.

## 1. Identities (bind everything to the archive digest)

| | |
|---|---|
| Archive | `dev-platform-0.1.0.tar.gz` |
| **Archive sha256 (authorization subject)** | `f3ef0e50e23efc063e45041d6608ad87a7ea6150280529cd5bb969d168464dc2` |
| Tree digest (consumer pin) | `09adc0d2f1b3b6eba9c423b6cd258cd64b75899b5005e371d2b0692a8ccc4e4b` |
| Tag | `v0.1.0`, annotated, not GPG/SSH-signed; protected by ruleset 24840008 (no update/delete, no bypass) |
| Source revision | `279cd6d28e18df4293b3aa09d3f0224d58f30e38` |
| Release workflow run | https://github.com/syncom-systems/dev-platform/actions/runs/38071871979 |
| Signer identity | `syncom-systems/dev-platform/.github/workflows/release.yml@refs/tags/v0.1.0`, GitHub-hosted runner |
| GitHub release | immutable, pre-release flag, titled "dev-platform 0.1.0 (verified, NOT accepted)" |
| Attestations | SLSA provenance (archive; build-environment record), CycloneDX SBOM (archive) |

Build environment (linux-x86_64, profile `dev-platform-release`, assurance `certifiable`, `hermetic: false`,
identity digest `a31eef599f21ed869d53a15911593302630a695b1db840e0ba856164029895a6`):

| Tool | Version | Identity level | Closure sha256 (linux-x86_64) |
|---|---|---|---|
| CPython (python-build-standalone 20260807) | 3.14.7 | closure-verified | `520d9d6ebeba77ece9d776110bb89845d6b7560394038f2b6438ff244e7ba538` |
| ruff | 0.17.0 | closure-verified | `4ca9f3d98bc6e23e2b5a7e9f8ef50b4c2a3a96ff89a23b02a33347c954e7e10d` |

The release's `toolchains/manifest.json` ships profiles `dev-platform`, `dev-platform-release`, `python`,
`rust-bazel` (Bazelisk 1.29.0, Bazel 8.4.2 binary sha256 pinned per platform, rules_rust 0.61.0, rustc 1.85.0).
It does **not** contain `rust-cargo`.

Records (this directory): `identity.json`, `build-environment.json`, `verification.ci.json`,
`verification.independent.json`, `verification.installer.json`, `consumer-use.result.json`.

## 2. Independent verification and trust anchors

`tools/verify_release.py` (imports nothing from `dev_platform`), run from `main` and not from the release, with
operator-supplied pins; expected revision from `git ls-remote` on the tag; archive digest computed locally.
All **26 checks passed**: archive digest and structure, version and source binding, SBOM vs manifest, provenance
attestation, SBOM attestation, build-environment attestation, certificate fields against the signer policy,
environment evidence against the manifest pins. Result: `verified-unaccepted`.

Trust anchors (a reviewer must re-derive these themselves and compare, not copy them from this file):

| Anchor | sha256 |
|---|---|
| `tools/verify_release.py` | `49ff13fdfa2a7811b0fd7c523472dfda247516bb09c7d537aa8cf0acf53836f9` |
| `trust/policy.json` | `957acd7635f343acda9fae9bf23e26b123d765846d0ad2443f92ee3c6f7d88b4` |
| `tools/install_release.py` (installer; not part of the verification above) | `7e98915b33294c9f97ad734e4f8127667e9b45a856921429d82bbba8ca08e93e` |
| `tools/validate_authorization.py` (new; validates the owner record, sec. 6) | `baeece00273e25fbea4daddee88d90d73ada735d65bb7df617c31f485f72b36c` |

Rejections observed on this artifact: wrong source revision; one appended byte; another version claimed;
build-environment record absent; the rc.4 environment record; wrong verifier pin (exit 3); wrong policy pin
(exit 3). The installer refuses the release without `--allow-unaccepted`.

Independent reproduction:
```
gh release download v0.1.0 --repo syncom-systems/dev-platform --dir d
python3 tools/verify_release.py d/dev-platform-0.1.0.tar.gz --version 0.1.0 \
  --source-revision 279cd6d28e18df4293b3aa09d3f0224d58f30e38 \
  --archive-sha256 f3ef0e50e23efc063e45041d6608ad87a7ea6150280529cd5bb969d168464dc2 \
  --environment d/dev-platform-0.1.0.build-environment.json --policy trust/policy.json
```
after checking the two anchor digests above with `shasum -a 256`.

## 3. Supported and unsupported combinations

Supported means: `tools/qualify.py` passed with real tools on that platform, at the exact release revision
(CI run 38071693306: python and rust-bazel on ubuntu-24.04 and macos-15, including must-be-rejected cases).

| Profile | linux-x86_64 | darwin-arm64 | In v0.1.0 manifest |
|---|---|---|---|
| `python` | supported | supported | yes |
| `rust-bazel` | supported | supported | yes |
| `rust-cargo` | **not claimed for v0.1.0** (qualified later on main only) | **not claimed** | no |
| Python-in-Bazel (`rules_python`), mixed | unsupported (certification fails closed) | unsupported | no |
| Linux aarch64, Windows | unsupported | n/a | no |

Release builds themselves ran on linux-x86_64 only. Any other platform or unpinned tool yields assurance
`diagnostic`, which cannot be certified. Support for `rust-cargo` requires a new release.

## 4. Assurance limitations (not claimed away)

- **Not hermetic.** Tool identity is not execution-environment identity. System libraries are trusted by name or
  prefix (`closure.system_libs`), not by content; the host kernel, CPU, filesystem and loader are outside the
  evidence. Environment records and certified results carry `scope.hermetic = false` and these limitations.
- Bazel runs additionally leave the Bazel repository cache, the host C toolchain and fetch-time network outside the
  evidence. Cargo runs leave the host linker outside the evidence.
- `dlopen`ed objects are covered only if inside a closure digest.
- Linkage checks list direct dependencies of native objects; they are an inspector's output, not a proof.
- Accepting this release does not certify it: certification is a property of a consumer's check result.
- A consumer certified under this release is certified for its checks on a stated platform and profile only.

## 5. Known security findings and unresolved deviations

Monitoring at time of writing: code-scanning alerts 0 open; Dependabot alerts 0 open; secret-scanning alerts 0.
Open Dependabot PR #28 (seven action bumps incl. attestation actions) is intentionally unmerged; it does not
affect v0.1.0, whose workflow pins actions by commit SHA.

Deviations affecting acceptance:

1. **The verifier alone cannot validate the owner's identity.** `verify_release.py` treats any identity assertion
   whose provider is not `git-commit-author`/`git-config` as sufficient: an unsigned record naming any provider
   would yield `accepted`. Mitigation, without changing the pinned verifier or policy: acceptance is only valid
   after `tools/validate_authorization.py` passes (sec. 6), run before the record is given to the verifier.
   Hardening the verifier itself would be a new pinned version.
2. The v0.1.0 tag is annotated but unsigned (tamper-resistance rests on the ruleset and immutable release).
3. `install_release.py` derives the expected archive digest from the local file when `--archive-sha256` is omitted;
   pass it explicitly from this packet.
4. The first-release self-upgrade rule (previous release as continuity evidence, issue #4) is unimplemented; for
   v0.1.0 there is no predecessor and the trust base is only the pins above.
5. Signing of authorization records by the platform, and a durable evidence store (M4 remainder), do not exist.
6. Failed attempts rc.1 and rc.3 are retained and never promoted; rc.2, rc.4 and rc.5 are separate verified
   pre-releases with different digests and carry no authority for v0.1.0.

## 6. Authorization record required (`dev-platform.authorization/v1`)

Template: `authorization.template.json` (every placeholder fails validation until replaced). Required content:

- `subject = {kind: "platform-release", digest: "f3ef0e50…464dc2"}` (the full archive sha256 above)
- `decision`: `approved` (or `rejected`)
- `decided_by`: `id`, `role`, and `identity_assertion = {provider: "github-signed-commit", login, reference}`
- `basis = {kind, reference}`; `decided_at` (UTC); `supersedes` (empty unless replacing); `retention`
  (`class`, `until`: null for indefinite)

Effects: the verifier honours the latest non-superseded record for this digest; `decision: revoked` withdraws.
A git author name is never an identity assertion.

## 7. Proposed acceptance scope and mechanism (for the owner to ratify or change)

Scope of the proposed approval, nothing broader:

- Accept archive `f3ef0e50…464dc2` as the first stable platform baseline, for the combinations in sec. 3 marked
  supported, with the limitations in sec. 4 and deviations in sec. 5 acknowledged.
- Does not certify the release, does not extend qualification, does not approve any consumer migration, and
  does not approve any other version (including `rust-cargo` support).

Mechanism for recording the owner's actual identity and approval:

1. The owner reviews this packet and independently re-derives the anchors and verification (sec. 2).
2. The owner fills the template themselves and commits it to `authorizations/platform-release-0.1.0.json` with
   their own GitHub-verified signed commit. The merge must preserve that commit (push or merge-commit; a squash or
   rebase merge makes GitHub the committer and is refused).
3. An operator pins the owner's GitHub login out of band and runs:
   ```
   python3 tools/validate_authorization.py --record <file> --path authorizations/platform-release-0.1.0.json \
     --archive-sha256 f3ef0e50e23efc063e45041d6608ad87a7ea6150280529cd5bb969d168464dc2 --owner-login <login>
   ```
   It requires a valid signed commit with author and committer both the pinned login, and byte-identical content.
4. Only then is the record passed to the verifier (`--authorization`), which should report `accepted`; that
   record, the validator output and the verifier output are retained in `releases/0.1.0/`.

Until step 4 completes with all checks passing, the release stays `verified-unaccepted` and the GitHub release
keeps its "NOT accepted" title. Changing that title or flag after acceptance is itself a new, separately
recorded step (the release is immutable; the acceptance lives in the records, not in the release object).

No production consumer migration is authorized by acceptance of this baseline.
