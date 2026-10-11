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
come from the application's own approvers. `--discover-authorizations` also judges every record in the evidence
repository so a revocation absent from a bundle still counts.

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
