# 0020 GitHub Environment approval as an authorization provider

Status: Superseded by [ADR 0024](0024-single-owner-release-authority.md) for platform releases: `accept.yml` is removed
and the platform verifier reads no approval record. The provider remains in the registry for application-release
approvals (ADR 0019). Proposed (v0.7.0; the owner directed simple approval by a logged-in GitHub click, "I trust my
login to GitHub")

## Context
`github-signed-commit` needs a locally held signing key and a commit whose author and committer are the approver. For the
owner's occasional release acceptance that is more machinery than the risk it removes. A web-editor commit cannot be used
(GitHub is the committer). GitHub already records a human approval for a protected Environment, and Sigstore can bind it.

## Decision
Provider `github-environment-approval`, enabled per policy (`authorization.providers`) with a pinned
`authorization.environment_approval {repo, workflow, ref}`.
- `.github/workflows/accept.yml` is `workflow_dispatch` only. Its job targets the `owner-approval` environment (required
  reviewer: the owner), so it starts only after an approval click. It checks the digest equals the published archive of
  that version, reads the approver from the run's approvals (exactly one), writes the authorization record and attests it.
- `verify_release.py` accepts the record only if `gh attestation verify` shows those exact bytes attested by the pinned
  workflow at the pinned ref, trigger `workflow_dispatch`, GitHub-hosted runner; the approver login must then be in the policy
  with the same provider, role and claim as for any other provider. Everything after authentication is unchanged.
- The committer of the record file is irrelevant: authenticity is the attestation, so an agent may commit the downloaded file
  and cannot alter it.
- Records are write-once by content: revocation is another run with decision `revoked`.

## Consequences
- Trust anchor change: `tools/verify_release.py` has a new digest from 0.7.0. Older releases are verified with the new
  verifier and their own policy plus the owner's separate policy file; the signed-commit provider is unchanged.
- Trusts: the owner's GitHub login/session at the click, GitHub's approval record, the `accept.yml` on `main` (merged only by
  the owner), Sigstore. Not trusted to separate the owner from an agent holding the same logged-in session or token.
- Self-review must be allowed on the environment (single-owner repository).
- Application-release approval (ADR 0019) is untouched and independent.

## Security consideration: shared session (issue #115)
The approval is a click by whoever holds the owner's logged-in GitHub session or token. Agents working in this repository
use the same account, so the record cannot distinguish the owner from an agent acting through that session. This was
accepted by the owner for platform acceptance ("I trust my login to GitHub") and the v0.2.1 acceptance stands: it is
reopened only by new evidence of a defect, not by this limitation.

Future stronger assurance, if acceptance ever protects something that warrants it, is a new provider (a new trust-model
decision of the owner) such as: an approval signed with a key the owner holds (the signed-commit provider already supports
this and stays available), a passkey-gated Sigstore signature, or a separate identity for agents so that the owner's account
is never available to them. Until then, consumers must treat acceptance as "approved through the owner's GitHub login", and
verify it as a current decision (`tools/verify_platform_current.py`), never as a stored fact.
