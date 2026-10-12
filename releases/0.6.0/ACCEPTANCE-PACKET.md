# Owner acceptance packet: dev-platform v0.6.0 (stable candidate)

State: **verified-unaccepted**. No authorization exists. Nothing here creates, signs or attributes one. Independent of
v0.2.1, v0.3.0, v0.4.0 and v0.5.0 (still separate verified-unaccepted candidates; their records are unchanged): acceptance is per
archive digest.

## 1. Identities
| | |
|---|---|
| **Archive sha256 (authorization subject)** | `98902922986ebead1d6a00943dcc98cc464ce3cc317faf8c39de7299bd778e1d` |
| Tree digest (consumer pin) | `68520aa4ee7c02e84a7eff0f248ac742d7d8eb08295a51a7a40753400407aea9` |
| Tag / revision | `v0.6.0` (annotated, not signature-signed; ruleset blocks update/delete) / `4994d2b55b6df699795cd121a0a78c0a0cd33963` |
| Release workflow | run 38222634166; signer `syncom-systems/dev-platform/.github/workflows/release.yml@refs/tags/v0.6.0`, GitHub-hosted |
| GitHub release | immutable, pre-release flag, titled "dev-platform 0.6.0 (verified, NOT accepted)" |
| Attestations | SLSA provenance (archive, build-environment record, continuity record), CycloneDX SBOM |
| Build environment | linux-x86_64, `dev-platform-release`, certifiable, `hermetic: false`, identity digest `a31eef599f21ed869d53a15911593302630a695b1db840e0ba856164029895a6` |
| Predecessor continuity | 0.5.0 (exact-digest-pinned in the policy; verified-unaccepted) re-ran the full stage over this source |

## 2. Independent verification and trust anchors
`tools/verify_release.py` from `main` with operator pins and **the policy of this release's source revision**; revision from
`git ls-remote` on the tag; archive digest computed locally. 32/32 checks passed; `verified-unaccepted`; `confers: []`.
Records: `verification.independent.json`, `verification.ci.json`, `continuity.json`, `build-environment.json`,
`rejections.txt` (live negatives: invented provider, never-committed record, wrong revision, appended byte, continuity record
absent and altered, all rejected), `current-state.json` (the same release as a current decision: `verified-unaccepted`).

| Anchor | sha256 |
|---|---|
| `tools/verify_release.py` (unchanged since 0.2.1) | `791713d01198f47045c7abb210e73dd94976d266ed12351cfce53ea9d2b466a9` |
| `trust/policy.json` at the source revision (`approvers: []`, predecessor 0.5.0) | `437bff36df3619d58221c97470970b067e2e6eee61a38def793b539992e47232` |
| `tools/install_release.py` (unchanged) | `473a2c73eb71904ea6ee0e010f2288976126d4560e3efd11c33c11e44f15bb93` |
| `tools/verify_app_release.py` (changed in 0.6.0: `indeterminate`, audit state, acknowledged removals) | `c53bf1351e4f87e7871e616b7eeaee8eca9cb999218e8f70519321cd361d8172` |
| `tools/verify_platform_current.py` (changed in 0.6.0: `indeterminate`, audit state) | `55af0f2e20818b879fa998259e0e4d16da96afdbe48cd187e9203658408398fe` |

The policy used for acceptance is a separate file that you pin (the release's policy plus your approver entry; see
`docs/owner-acceptance-0.2.1.md`, which applies to every candidate). `main`'s `trust/policy.json` moves on with each
release and fails the continuity check for any older one.

## 3. What changed (milestone v0.6.0; version policy: minor, breaking output declared for 0.x)
| Issue | Capability | Evidence |
|---|---|---|
| #94 | `indeterminate` (exit 5): the current authorization state could not be established. Distinct from `unapproved` (state read, nobody authorizes; exit 3) and `failed` (the release itself is invalid). Records carry `approval.authorization_state` and coded `currency.reasons`; `rollback select` rejections carry `authorization_state` | `tests/test_app_release_verifier.py` (`HistoryAudit`), `tests/test_rollback_authenticated.py`, `qualification/*.json` |
| #95 | Scalable authenticated evidence-history audit: up to 10 000 commits listed; per-commit immutable facts reused through `--audit-state` (a cache of facts only; outcomes are identical with and without it, asserted in tests and in a qualification case); progress kept across runs (`audit-incomplete`); an earlier audited head that is no longer an ancestor is `history-rewritten`; damaged state refused | same; `qualification/*.json` case "a warm audit state decides exactly as a cold run"; real-GitHub exercise of the compare/ancestry path against the fixture repository |
| #96 | Recovery from a deleted record: restore by an approver, or the operator-pinned application policy lists `acknowledged_removals` (`{path, commit}`); the record is read from before its deletion and still counts, so a deleted revocation never un-revokes. The platform path accepts restoration only | `HistoryAudit` tests; qualification case "deleted revocation acknowledged in the pinned policy still revokes" |
| #97 | Live positive platform-acceptance qualification after a genuine owner authorization: **not done and not fabricated**; owner-dependent | `docs/owner-acceptance-0.2.1.md` Part C |

Owner acceptance procedure for v0.2.1 now separates what only the owner can do (Part B) from what is agent-executable
(Parts A and C); Parts A and C were rehearsed against the real v0.2.1 release (`owner-preflight-0.2.1/current-state.json`:
`verified-unaccepted`, no records, audit state exercised).

## 4. Qualification (CI run 38222621252 at the tagged revision)
All five profiles (`python`, `rust-cargo`, `rust-cargo-1.99`, `rust-bazel`, `rust-bazel-9`) on linux-x86_64 and darwin-arm64:
admitted, certified, chain cases (22 for python, 20 otherwise) and 17 rollback cases all as expected (`qualification/INDEX.json`
lists each file with its sha256). `rust-bazel*` execute Bazel only; no Cargo is run for them. The NGA and flight repositories
were not modified. v0.4.0's and earlier qualification claims are not widened; these records are additional evidence for 0.6.0.

## 5. Semantics and limitations (read these)
- **Three results, never merged.** `approved` (state read, authorized), `unapproved` (state read, nobody authorizes: never
  approved, revoked, superseded, expired; exit 3), `indeterminate` (state could not be read or audited; exit 5, coded
  reasons: `api-failure`, `ref-unresolved`, `ref-moved`, `history-too-long`, `audit-incomplete`, `history-rewritten`,
  `audit-state-invalid`, `record-removed`, `record-unreadable`, `listing-failed`). Both 3 and 5 forbid operational use; a
  defective release stays `failed` and an outage never masks it. `historical-approval` (exit 4) is inspection only.
- **What "current" means.** The state as read from the GitHub API at `observed_at`, at one commit of the evidence ref;
  reusable only until `valid_until` (policy `freshness.max_age_seconds`, default 300, at most 3600). No offline current
  decision exists: offline (`--historical`) can only say `historical-approval`.
- **Scale model.** Cost of a run is O(commits touching `authorizations/` / 100) list requests + O(records) reads + one
  detail read per commit not yet audited. With `--audit-state` a warm run reads no commit detail; a run over its budget
  (500 new commits) saves progress and reports `audit-incomplete` until caught up. Beyond 10 000 commits touching
  `authorizations/` the state is `indeterminate` (`history-too-long`). Each rollback candidate still runs its own
  snapshot (head, listing, record reads), but shares the audit state. The state caches facts about immutable commits only;
  it holds no decision and no record content; every record is read and judged in full at the current head each time.
- **Recovery.** Deleted record: `indeterminate` (`record-removed`) until an approver restores it (a path any non-approver
  ever touched can no longer authenticate; publish under a new name) or the operator's pinned application policy
  acknowledges that exact removal. `history-rewritten`: investigate; remove the audit state only after understanding why.
  `audit-state-invalid`: delete the file (costs time only). Platform path: restoration only.
- **Not detected:** a force-push of the evidence ref by a consumer with no earlier audit state; a record never published to
  the ref; a record added and deleted wholly inside a merged side branch (keep the evidence ref linear); a compromised
  transport or GitHub itself; tampering with the local audit state file other than damage (it is the operator's file).
- Platform acceptance: `tools/verify_release.py` itself still judges only the records it is handed (unchanged trust
  anchor, `791713d0…`); the current-state wrapper and the application verifier hand it the discovered ones.
- **Live GitHub never reaches `approved`.** Records committed through GitHub's API name `web-flow` as committer and are
  refused by design; a live positive needs a second GitHub identity with its own signing key (#79), not provisioned by
  decision (a controlled non-production arrangement would be considered only for a requirement that cannot otherwise be
  met; none has been identified: the positive is exercised against recording doubles with the real verifier and CLI code).
- The live record is reproducible only with access to the private fixture repository; CI does not run it. The live run
  also created a scratch branch in the fixture to prove deleted-record detection against real GitHub.
- Qualification builds a platform release from the checkout without source stamping, so its platform tree digest
  identifies that build, not the released archive's; consequently `platform-acceptance-required.txt` shows the policy
  refusing the real archive for a tree mismatch; the lack-of-acceptance refusal on a real archive is
  `releases/0.4.0/platform-acceptance-required.txt`. One platform archive per run. Not hermetic; release builds ran on
  linux-x86_64 only.
- Breaking (0.x, declared): consumers that matched `failed` for an unreadable authorization state must handle
  `indeterminate` (exit 5). `trust/policy.json` changed only in the continuity predecessor (evidence, no authority;
  approvers remain empty; ratified as routine release engineering).
- Acceptance is not certification. Tag `v0.6.0` is not signature-signed (#53). OIDC provider open (#76). Acceptance of any
  release, nga adoption phases 2-4 and advisory publication remain owner decisions. No regulatory-compliance claim is made.

## 6. What the owner must do (nothing is pre-made)
Follow `docs/owner-acceptance-0.2.1.md`, substituting this release's identities and policy digest: re-derive anchors and
verification, create the pinned policy (this release's policy plus your approver entry), copy `authorization.template.json` to
`authorizations/<name>.json`, commit with your own signed commit (push directly, or merge commit; never squash/rebase), run the
verifier and the current-state check with your pins, retain the output.

## 7. Proposed acceptance scope
`platform-baseline` only, for archive `9d6a9bc9…` and the profiles and platforms in section 4, acknowledging section 5. No
certification, application approval, consumer migration or approval of any other release.
