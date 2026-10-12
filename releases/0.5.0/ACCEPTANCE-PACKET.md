# Owner acceptance packet: dev-platform v0.5.0 (stable candidate)

State: **verified-unaccepted**. No authorization exists. Nothing here creates, signs or attributes one. Independent of
v0.2.1, v0.3.0 and v0.4.0 (still separate verified-unaccepted candidates; their records are unchanged): acceptance is per
archive digest.

## 1. Identities
| | |
|---|---|
| **Archive sha256 (authorization subject)** | `9d6a9bc9e1a2f31f767368e6cc37f8d534824d01e18aedefc35708ab2c4646d3` |
| Tree digest (consumer pin) | `798ca5f8cd48fc656f5fb44ec901597350856b1e2b08f0d99c513fadd0335478` |
| Tag / revision | `v0.5.0` (annotated, not signature-signed; ruleset blocks update/delete) / `6d954c2453eeb0b7b81451b2f8165a0938117933` |
| Release workflow | run 38188032733; signer `syncom-systems/dev-platform/.github/workflows/release.yml@refs/tags/v0.5.0`, GitHub-hosted |
| GitHub release | immutable, pre-release flag, titled "dev-platform 0.5.0 (verified, NOT accepted)" |
| Attestations | SLSA provenance (archive, build-environment record, continuity record), CycloneDX SBOM |
| Build environment | linux-x86_64, `dev-platform-release`, certifiable, `hermetic: false`, identity digest `a31eef599f21ed869d53a15911593302630a695b1db840e0ba856164029895a6` |
| Predecessor continuity | 0.4.0 (exact-digest-pinned in the policy; verified-unaccepted) re-ran the full stage over this source |

## 2. Independent verification and trust anchors
`tools/verify_release.py` from `main` with operator pins and **the policy of this release's source revision**; revision from
`git ls-remote` on the tag; archive digest computed locally. 32/32 checks passed; `verified-unaccepted`; `confers: []`.
Records: `verification.independent.json`, `verification.ci.json`, `continuity.json`, `build-environment.json`,
`rejections.txt` (live negatives: invented provider, never-committed record, wrong revision, appended byte, continuity record
absent and altered, all rejected), `current-state.json` (the same release as a current decision: `verified-unaccepted`).

| Anchor | sha256 |
|---|---|
| `tools/verify_release.py` (unchanged since 0.2.1) | `791713d01198f47045c7abb210e73dd94976d266ed12351cfce53ea9d2b466a9` |
| `trust/policy.json` at the source revision (`approvers: []`, predecessor 0.4.0) | `d14beada42eea2793f90b3a319c78632adb7a3e273a742bc44fcaac14f83d49e` |
| `tools/install_release.py` (unchanged) | `473a2c73eb71904ea6ee0e010f2288976126d4560e3efd11c33c11e44f15bb93` |
| `tools/verify_app_release.py` (changed: operational/historical purposes, mandatory current-state discovery) | `c321beaf2ed56398377799801320c62852508d8ee69457b5c37d8d7ee5c9eb34` |
| `tools/verify_platform_current.py` (new) | `a358595bcebedb2a0c9e582993c006788f34fda9f74c07f315944f062da28c02` |

The policy used for acceptance is a separate file that you pin (the release's policy plus your approver entry; see
`docs/owner-acceptance-0.2.1.md`, which applies to every candidate). `main`'s `trust/policy.json` moves on with each
release and fails the continuity check for any older one.

## 3. What changed (milestone v0.5.0; version policy: minor, breaking default declared for 0.x)
| Issue | Capability | Evidence |
|---|---|---|
| #86 | Current-state authorization is mandatory for deployment, eligibility and rollback: every record in the evidence repository is read at one commit and judged like a supplied one; history is audited for deleted records; ref moves, outages, truncation, failed calls make the decision `failed` (`authorization-currency`); `rollback select` always applies it; `AppVerifier` accepts only a fresh current `approved` record (`currency.valid_until`, policy `freshness.max_age_seconds`, default 300); `--discover-authorizations` removed | `tests/test_app_release_verifier.py` (`CurrentState`, 23 cases), `tests/test_rollback_authenticated.py` |
| #87 | Historical inspection is explicit: `--historical` judges supplied records only and reports `historical-approval` (exit 4), never `approved` | same tests; `qualification/*.json` case "inspected as history shows only a historical approval" |
| #88 | End-to-end negatives: approval, then a revocation published independently and absent from the old bundle; evidence repository unreachable; revocation deleted from history | `qualification/*.json` `app_release.cases` (4 freshness cases) and `app_release.rollback.cases` (4 freshness cases) on all five profiles, linux and darwin; `live-qualification.json` (live history audit) |
| #89 | `tools/verify_platform_current.py`: "is this platform release currently accepted?" over the unchanged `verify_release.py`; a platform acceptance required by an application policy is read as current state | `tests/test_verify_platform_current.py`; `current-state.json`; `platform-acceptance-required.txt` |
| #90 | Genuine owner-acceptance procedure for v0.2.1 (finding: `main`'s policy fails v0.2.1 continuity; the release's own policy is used) | `docs/owner-acceptance-0.2.1.md`, `owner-preflight-0.2.1/current-state.json` |

## 4. Qualification (CI run 38188024282 at the tagged revision)
All five profiles (`python`, `rust-cargo`, `rust-cargo-1.99`, `rust-bazel`, `rust-bazel-9`) on linux-x86_64 and darwin-arm64:
admitted, certified, chain cases (19 for python, 17 otherwise) and 17 rollback cases all as expected (`qualification/INDEX.json`
lists each file with its sha256). `rust-bazel*` execute Bazel only; no Cargo is run for them. The NGA and flight repositories
were not modified. v0.4.0's and earlier qualification claims are not widened; these records are additional evidence for 0.5.0.

## 5. Freshness semantics and limitations (read these)
- **What "current" means.** The state as read from the GitHub API at `observed_at`, at one commit of the evidence ref.
  A verification is reusable only until `valid_until` and only as evidence of that moment; the consumer re-verifies for each
  decision. There is no offline current decision: offline (`--historical`) can only say `historical-approval`.
- **Not detected:** a force-push or history purge of the evidence ref; a record never published to the ref; a compromised
  transport or GitHub itself. Deleting a record from the ref's history is detected and fails closed until it is restored.
- **Cost:** each candidate in `rollback select` runs its own snapshot (history audit is O(commits touching `authorizations/`),
  at most 500). History longer than that fails closed.
- Platform acceptance: `tools/verify_release.py` itself still judges only the records it is handed (it is the unchanged
  trust anchor); the current-state wrapper and the application verifier hand it the discovered ones.
- **Live GitHub never reaches `approved`.** Records committed through GitHub's API name `web-flow` as committer and are refused
  by design; a positive live approval needs a second GitHub identity with its own registered signing key (#79; not provisioned,
  by decision). The positive is exercised only against recording doubles (real verifier and CLI code).
- The live record is reproducible only with read access to the private fixture repository; CI does not run it. The live run
  also created a scratch branch in the fixture to prove deleted-record detection against real GitHub.
- Qualification builds a platform release from the checkout without source-uri/revision stamping, so its platform tree digest
  identifies that build, not the released archive's (observed: `c2030038…` vs `798ca5f8…`); the link is the source revision.
  Consequently `platform-acceptance-required.txt` shows the policy refusing the real archive for a tree mismatch (platform
  verification `failed`), not for lack of acceptance; the lack-of-acceptance refusal on the real 0.3.0 archive is
  `releases/0.4.0/platform-acceptance-required.txt`.
- Platform-acceptance requirement: one platform archive per run. Not hermetic (as before); release builds ran on linux-x86_64 only.
- Breaking (0.x, declared): `verify_app_release.py` defaults to the operational purpose and needs GitHub access;
  `--discover-authorizations` is removed; consumers that treated exit 0 or `approved` from offline runs must use `--historical`
  and handle `historical-approval`. `trust/policy.json` changed only in the continuity predecessor (evidence, no authority;
  approvers remain empty; ratified as routine release engineering).
- Acceptance is not certification. Tag `v0.5.0` is not signature-signed (#53). OIDC provider open (#76). Acceptance of any release,
  nga adoption phases 2-4 and advisory publication remain owner decisions. No regulatory-compliance claim is made.

## 6. What the owner must do (nothing is pre-made)
Follow `docs/owner-acceptance-0.2.1.md`, substituting this release's identities and policy digest: re-derive anchors and
verification, create the pinned policy (this release's policy plus your approver entry), copy `authorization.template.json` to
`authorizations/<name>.json`, commit with your own signed commit (push directly, or merge commit; never squash/rebase), run the
verifier and the current-state check with your pins, retain the output.

## 7. Proposed acceptance scope
`platform-baseline` only, for archive `9d6a9bc9…` and the profiles and platforms in section 4, acknowledging section 5. No
certification, application approval, consumer migration or approval of any other release.
