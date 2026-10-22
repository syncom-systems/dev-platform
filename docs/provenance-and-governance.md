# Application release provenance and governance

dev-platform defines portable records; it does not deploy, approve, store long-term or certify
anything on a regulator's behalf. External release/governance systems produce and consume them.

## The chain (all links by sha256 digest)

```
source revision ─┐
dependency resolution ─┤
platform release + profile + toolchain identity ─┼─> app-release/v1 ──> artifact digests
result records (evidence) ─┤                         ▲
authorization/v1 records ──┘ (referenced)            └── rollback = select an earlier approved release
```

`toolchain_identity_digest` is the `environment.identity_digest` of the full-stage result: a hash of
what was *observed* (profile, tool names, observed versions, identity strength).

## Records
- `dev-platform.app-release/v1` ([schema](../schemas/app-release-v1.schema.json)): requires source,
  dependency resolution digest, platform release/profile/toolchain identity, at least one artifact
  digest and at least one evidence reference. `dev-platform validate FILE` checks it.
- `dev-platform.authorization/v1` ([schema](../schemas/authorization-v1.schema.json)): subject digest,
  decision, approver (id, role, **identity assertion** from an identity provider), basis (ticket,
  policy, review), RFC 3339 **UTC** timestamp, `supersedes`, retention class and `until`.
  `effective_decision` resolves the current decision by explicit supersession; a `revoked` or
  superseded approval no longer authorizes.

## Approving and verifying an application release (ADR 0019)
`python3 -I tools/verify_app_release.py release.json --policy app-trust.json --platform-verifier tools/verify_release.py
--platform-verifier-sha256 PIN --mode release --source-revision SHA --lock Cargo.lock --root . --artifact app.tar=app.tar
--result result.json --advisory adv.json --authorization authorizations/app-1.0.0.json` re-derives every link and
reports `approved`, `unapproved` or `failed`. The approval is a record signed by an approver listed for that
application in the application-owned policy (`dev-platform.app-trust/v1`); it binds the canonical digest of the exact
release record and confers only `application-release-approval`. `dev-platform rollback select` runs it per candidate
under operator pins. Platform acceptance is a different decision and is neither required nor implied by default.

An application that wants more may say so in its own policy: a `platform_releases` entry with `require_acceptance:
true`, `archive_sha256` and `source_revision` adds the check `platform-acceptance`, for which the verifier re-runs
`tools/verify_release.py` over the named archive (`--platform-archive --platform-policy P --platform-policy-sha256 PIN
--platform-authorization ..`). The platform policy stays a separate trust anchor; the application approval still has to
come from the application's own approvers. A platform release verified under `trust/v2` (0.12.0 on) satisfies the check
when it is `verified`; there is no platform authorization to read (ADR 0024).

## Current versus historical authorization (freshness)
A bundle is a past: it holds the records that existed when it was written. A decision to deploy, to treat a release as
eligible or to roll back is about now, so `verify_app_release.py` (default purpose `operational`) and `rollback select`
always read the evidence repository's records at one commit, judge them with the supplied ones, and audit the history
for deleted records. A revocation published after the bundle was written ends eligibility with no flag. If the
state cannot be established (unreachable, truncated, moved while read, a failed call, a deleted record) the result is
`failed`, never `approved`. The record's `currency` block names the evidence commit and a `valid_until`
(`freshness.max_age_seconds` in the application policy, default 300 s); reuse nothing older. `--historical` inspects
supplied records only and reports `historical-approval` (exit 4), which is not an approval. Limits: the answer is as fresh as
GitHub's API at the moment of the read (no stronger than the transport and GitHub itself); a record that was never
published to the evidence ref cannot be found; a purge of history (force-push) is not detected by this mechanism; a
removed record needs an explicit restore before decisions resume.

Three results, never merged: `approved` (state read, authorized), `unapproved` (state read, nobody authorizes this
release: never approved or revoked; exit 3) and `indeterminate` (state could not be read or audited; exit 5, with coded
`currency.reasons`). The last two both forbid operational use; they differ in what the operator must do. History
scale: the audit lists commits touching `authorizations/` (up to 10 000) and reads the changes of each commit once;
`--audit-state DIR` keeps those immutable per-commit facts between runs and candidates, so a run reads only new commits
(budget 500 per run, progress kept, `audit-incomplete` until caught up). It is a cache of facts, never of a decision:
records are read and judged in full at the current head each time, and the earlier audited head must still be an
ancestor of the evidence ref (`history-rewritten` otherwise). A deleted record keeps the state `indeterminate` until it
is restored by an approver or the operator's pinned application policy acknowledges that exact removal
(`authorization.acknowledged_removals`), in which case the record is read from before its deletion and still counts.
Residual limits: a record added and deleted wholly inside a merged side branch is invisible to a path-filtered history;
keep the evidence ref linear. A force-push is noticed only by a consumer holding an earlier audit state.

## Immutable evidence bundles and retention (ADR 0019)
`dev-platform evidence bundle --out DIR --release release.json --result r.json --authorization a.json [--advisory ..]`
writes a write-once directory (files read-only) with a `manifest.json` listing every file by sha256 and prints the
manifest's own sha256: the one value the operator pins. `tools/verify_app_release.py --bundle DIR --manifest-sha256 PIN`
(and `dev-platform evidence bundle-verify`) refuse changed, missing, unlisted, symlinked or path-escaping files and a
release entry that does not match `release_sha256`. A later decision (revocation, re-approval) is a new bundle whose
`previous` names the old manifest digest; nothing is edited. `rollback select --bundle DIR=PIN` treats only bundled
releases as immutable targets (`--allow-unbundled` opts out and is labelled).

Retention contract (the storing system's obligations; the platform enforces none of it): a bundle's `retention` is its
longest-lived record (class order `standard` < `extended` < `regulated` < `permanent`; latest `until`, null =
indefinite). Do not delete a bundle before its `until`, nor while any retained approved release references the platform
release archive or evidence it names; keep the manifest digest in a system independent of the bundle. Class durations
are the operator's policy; none is implied. Authorization records are retained byte-for-byte (authenticity is checked
against the signed file in the evidence repository's history, which must be retained as well). No claim of regulatory
compliance is made.

## Separation of concerns
Execution identity (result), evidence (result), authorization (authorization record) and release
(app-release) are separate documents. A commit's author is not an approver; the validator refuses
`git-commit-author` assertions. Timestamps live in governance records, not in results, so results
stay reproducible.

## Long-lived auditability (design requirements on the storing system)
Append-only storage with tamper evidence (hash chain or WORM); retain results, SBOMs, release
manifests and authorizations for the declared retention class; keep the release archive (or its
attested digest and a recoverable copy) as long as any application release references it; record
supersession rather than editing. Unaddressed here: signing of authorization records (planned
milestone), electronic-signature requirements of specific regulations, validation (IQ/OQ/PQ) of the
platform itself. No claim of regulatory compliance is made.

## Evidence store
`dev-platform evidence put|verify --store DIR` keeps result records in a write-once store addressed by
canonical digest (`src/dev_platform/evidence.py`). Reads and scans re-derive the digest, so a modified or
misnamed file is reported, never served. `rollback select --evidence-store DIR` resolves an application
release's evidence digests from it (a corrupt store aborts selection). It is tamper-evident to anyone who
holds the digests; it is not a trust anchor and does not replace owner authorization.
