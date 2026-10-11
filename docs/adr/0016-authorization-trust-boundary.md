# 0016 Authorization trust boundary

Status: Ratified (owner directive, 2026-10-11). Supersedes the `tools/validate_authorization.py` proposal
that accompanied the v0.1.0 acceptance packet; the owner did not ratify that two-tool design.

## Defect found
Until v0.1.0 the authoritative verifier (`tools/verify_release.py`) produced `accepted` from any
authorization record whose identity provider was not literally `git-commit-author`/`git-config`. An unsigned
file naming an invented provider sufficed, and a policy flag could disable the requirement. v0.1.0 is
unaffected only because no authorization exists for it; it stays `verified-unaccepted` and immutable.

## Decision
The verifier itself authenticates authorization before it can produce `accepted`. The questions are separate
and each fails closed:

| Question | Where answered | Failure mode |
|---|---|---|
| Technical verification | verifier checks (archive, attestations, SBOM, environment) | `failed` |
| Authenticated identity | provider registry in the verifier; evidence fetched and verified at verification time, never read from the record | record ignored, listed with reasons |
| Approval authority | `trust/policy.json` `authorization.approvers` (identity, provider, `may_approve`, `may_confer`) | authenticated but not an approver: ignored |
| Decision scope | record `scope.confers`, a subset of what the approver may confer and of `{platform-baseline}` | ignored |
| Binding | `subject.kind == platform-release`, `subject.digest ==` archive sha256, record byte-identical to the signed file | ignored |
| Validity | `decided_at` not in the future, `validity` window | ignored |
| Supersession, revocation | only authenticated, authorized records count; latest live decision wins; equal timestamps fail closed | not accepted |

Registry (initial): `github-signed-commit`. Every commit that touched the record's path on the pinned ref
must carry a GitHub-verified valid signature with author and committer equal to the asserted login (a squash
or rebase merge makes GitHub the committer and is refused). A valid signature is identity evidence; authority
comes only from the approver registry in the pinned policy. Unknown providers, git authorship and unlisted
providers are refused. `stable_requires_authorization` cannot be disabled (verification fails).

An approval confers exactly `platform-baseline`. It never confers certification, qualification beyond the
release's own evidence, or any consumer migration; the verification record states this under
`acceptance.not_conferred`.

## Trust anchors
The approver registry is a trust anchor and is therefore an owner decision: the policy ships with
`approvers: []`, so nothing can be accepted until the owner adds themselves (a policy change, pinned out of
band like any other). Neither the platform nor its agent adds approvers or creates records.

## Known limits
- Authenticity depends on GitHub's signature verification and account binding at verification time; a later
  key revocation is not visible in an old verification record.
- Application-release approvals (`rollback select`) validate record shape and the provider registry only; they
  are not authenticated yet and the output says so. Do not treat them as authenticated approval.
