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
