# Owner acceptance packet: dev-platform v0.2.1 (stable candidate)

State: **verified-unaccepted**. No authorization exists. Nothing here creates, signs or attributes one.
Independent of v0.1.2: acceptance is per archive digest, and accepting one release says nothing about another.
Preserved and not offered: v0.1.0 (verifier defect, ADR 0016), v0.1.1 (failed publish gate), v0.2.0 (retained
verified-unaccepted; its tag's installer cannot supply the continuity record, `releases/0.2.0/README.md`). v0.1.2
remains a separate candidate.

## 1. Identities
| | |
|---|---|
| **Archive sha256 (authorization subject)** | `3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044` |
| Tree digest (consumer pin) | `7cc140322520220bce0292e599c8d9e1c36d0785981af02070175d32fc4165b5` |
| Tag / revision | `v0.2.1` (annotated, not signature-signed; ruleset 24840008 blocks update/delete) / `750d065e9eab486b7153079b7162013b19cc8aad` |
| Release workflow | run 38158695472; signer `syncom-systems/dev-platform/.github/workflows/release.yml@refs/tags/v0.2.1`, GitHub-hosted |
| GitHub release | immutable, pre-release flag, titled "dev-platform 0.2.1 (verified, NOT accepted)" |
| Attestations | SLSA provenance (archive, build-environment record, continuity record), CycloneDX SBOM |
| Build environment | linux-x86_64, `dev-platform-release`, certifiable, `hermetic: false`, identity digest `a31eef599f21ed869d53a15911593302630a695b1db840e0ba856164029895a6` |
| Manifest profiles | `dev-platform`, `dev-platform-release`, `python`, `rust-bazel`, `rust-bazel-9`, `rust-cargo`, `rust-cargo-1.99` |
| Predecessor continuity | 0.2.0 (digest-pinned in the policy; verified-unaccepted) re-ran the full stage over this source: admitted, exit 0 |

## 2. Independent verification and trust anchors
`tools/verify_release.py` from `main` with operator pins; expected revision from `git ls-remote` on the tag; archive digest
computed locally. 32/32 checks passed; `verified-unaccepted`; `confers: []`. Records: `verification.independent.json`,
`verification.ci.json`, `continuity.json`, `build-environment.json`, `rejections.txt` (live negatives: invented provider,
never-committed record, wrong revision, appended byte, absent and altered continuity record, installer refusal, wrong
verifier pin).

| Anchor | sha256 |
|---|---|
| `tools/verify_release.py` | `791713d01198f47045c7abb210e73dd94976d266ed12351cfce53ea9d2b466a9` |
| `trust/policy.json` (`approvers: []`) | `403f9131d130629d988f46abbcc4980635c16c1646b9967b19b3b45594db9cc7` |
| `tools/install_release.py` | `473a2c73eb71904ea6ee0e010f2288976126d4560e3efd11c33c11e44f15bb93` |

Re-derive them with `shasum -a 256` from a checkout you trust; do not copy from this file. The policy pin changes when you
add yourself as an approver (section 6): that is expected and is the new anchor you pin. The installer shipped at this tag
installs this artifact (`rejections.txt`: installs with `--allow-unaccepted`, state stays `verified-unaccepted` even when
given an invented authorization).

## 3. Supported and unsupported combinations
Qualified by real execution at the tagged revision (CI run 38158696379, must-be-rejected cases included):

| Profile | linux-x86_64 | darwin-arm64 |
|---|---|---|
| `python` | supported | supported |
| `rust-cargo` (rustc 1.85.0) | supported | supported |
| `rust-cargo-1.99` (rustc 1.99.0) | supported | supported |
| `rust-bazel` (Bazel 8.4.2, rules_rust 0.61.0, rustc 1.85.0) | supported | supported |
| `rust-bazel-9` (Bazel 9.2.0, rules_rust 0.74.0, rustc 1.97.1) | supported | supported |

Unsupported (certification fails closed to `diagnostic`): Python-in-Bazel (`rules_python`), mixed projects, Linux aarch64,
Windows, any unpinned tool or platform. "Supported" means the fixture passed under the profile, not that any consumer is
migrated.

## 4. Assurance limitations
- **Not hermetic.** Tool identity is not execution-environment identity; system libraries are trusted by name or prefix;
  kernel, CPU, filesystem, loader outside the evidence. Bazel leaves its repository cache, host C toolchain and fetch-time
  network outside the evidence; Cargo leaves the host linker outside it.
- Host tools a project declares (`[[host]]`) are observed by probed version only, never verified by content.
- Release builds ran on linux-x86_64 only.
- Continuity is evidence, not authority: the predecessor is itself unaccepted and its code ran in the CI runner environment.
- `--isolate-env` is environment-variable isolation only, qualified for `python` only.
- Acceptance is not certification.

## 5. Findings and deviations
Alerts: code scanning 0, Dependabot 0, secret scanning 0 open. Dependabot PR #28 is held (#54).

Consumer pilot (flight, pinned commit, `pilot` workflow) results are evidence about adoption friction, not qualification:
`rust-cargo` cannot build flight (dependencies need rustc >= 1.88); `rust-cargo-1.99` certifies on linux-x86_64 (tmux 3.4
observed); on macOS the declared `tmux` host requirement is reported unavailable. See `pilot/consumers.json`.

Outstanding:
1. Tag `v0.2.1` is not signature-signed (#53, owner decision).
2. Authenticity relies on GitHub's signature verification at verification time.
3. Application-release approvals (`rollback select`) are shape-checked only (`approval_authentication: unverified`, #52).
4. `install_release.py` derives the archive digest from the local file unless `--archive-sha256` is given; pass it.
5. The 0.2.0 -> 0.2.1 chain exists because 0.2.0 was found defective by independent verification; both immutable releases remain.
6. nga adoption phases 2-4 and publication of any repository security advisory are owner decisions (#67 and the nga issue).

## 6. What the owner must do (nothing is pre-made)
Authority is separate from authentication: a valid signature identifies you; the pinned policy decides whether you may approve.
1. Review this packet; re-derive the anchors and the verification (`python3 tools/verify_release.py <archive> --version 0.2.1
   --source-revision 750d065e… --archive-sha256 3cc47abb… --environment <env.json> --continuity <continuity.json>
   --policy trust/policy.json`).
2. Add yourself as an approver in `trust/policy.json` (`authorization.approvers`: `id`, `provider: github-signed-commit`, your
   GitHub `login`, `roles`, `may_approve: ["platform-release"]`, `may_confer: ["platform-baseline"]`) with your own
   GitHub-verified signed commit; pin the resulting policy sha256 out of band.
3. Fill `authorization.template.json`, commit it as `authorizations/<name>.json` with your own signed commit (push or merge
   commit; squash/rebase makes GitHub the committer and the record is ignored).
4. Run the verifier with `--authorization <file>` and your pins; it reports `accepted` only for an authenticated, authorized,
   in-force record bound to this digest. Retain the output under `releases/0.2.1/`.

## 7. Proposed acceptance scope
`platform-baseline` only: accept archive `3cc47abb…` as a stable platform baseline for the combinations in section 3, acknowledging
sections 4 and 5. It does not confer certification, qualification beyond section 3, approval of any consumer migration (nga
included), or approval of any other release.
