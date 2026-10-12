# Owner acceptance of a release: click to approve

Subject for v0.2.1: archive sha256 `3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044`, scope
`platform-baseline` (`releases/0.2.1/ACCEPTANCE-PACKET.md`). Accepting is optional and blocks nothing else. Neither the
platform nor its agent approves anything: the approval is a click on GitHub by the owner's logged-in account on the
`owner-approval` environment, recorded by GitHub in the run and attested by the `accept` workflow (ADR 0020).
Until such a record passes the verifier the state is `verified-unaccepted`. The immutable release and `releases/0.2.1/`
are never modified.

The workflow is manual only (`workflow_dispatch`): it is not part of CI, pull requests, tagging or any ordinary workflow.

## Owner: three steps
1. **Read** `releases/0.2.1/ACCEPTANCE-PACKET.md` and confirm the policy file `releases/0.2.1-acceptance/trust-policy.json`
   (v0.2.1's own policy, byte-exact, plus you as the only approver for this provider). Merge the PR that adds it and note its
   sha256 outside the repo; that digest is what verification trusts you for.
2. **Start the run:** GitHub, Actions, `accept`, Run workflow on `main`: version `0.2.1`, digest `3cc47abb...2044`,
   decision `approved`. Or: `gh workflow run accept.yml -f version=0.2.1 -f digest=<sha256> -f decision=approved`.
3. **Approve:** the run waits for review. Open it, Review deployments, tick `owner-approval`, Approve. (Do this yourself in the
   browser; a run that has not been approved does nothing.)

Then tell the agent, or run it yourself: the agent downloads the run's `authorization-record` artifact and commits it
unchanged to `authorizations/` through a PR (the bytes are attested, so the committer does not matter and an altered
file is refused), then runs the verification below. Changing your mind is a new run with decision `revoked`.

## Verify (owner or agent; read-only)
```
python3 -I tools/verify_platform_current.py dev-platform-0.2.1.tar.gz \
  --verify-release tools/verify_release.py --verify-release-sha256 <pin of tools/verify_release.py on main> \
  --app-verifier tools/verify_app_release.py --app-verifier-sha256 <pin> \
  --version 0.2.1 --source-revision 750d065e9eab486b7153079b7162013b19cc8aad \
  --archive-sha256 3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044 \
  --environment dev-platform-0.2.1.build-environment.json --continuity dev-platform-0.2.1.continuity.json \
  --policy releases/0.2.1-acceptance/trust-policy.json --policy-sha256 <your policy pin> --out current.owner.json
```
Expected: `current acceptance: accepted` (exit 0). Exit codes: 0 accepted, 3 verified-unaccepted, 5 indeterminate,
4 historical-acceptance, 1 failed, 2 usage. Retain the output under `releases/0.2.1-acceptance/evidence/` through a PR.
The agent reports machine-verifiable acceptance only when the verifier says `accepted` from the approved record.

## What this trusts (and does not)
It trusts your GitHub login at the moment you click, GitHub's recording of the approval, the pinned `accept.yml` on `main`
(only you merge there), and Sigstore for the attestation. It does not distinguish you from anything else holding your
logged-in session or token; the alternative with a hardware-held key is the signed-commit provider below.

## Alternative: signed commit (kept)
The `github-signed-commit` provider still works for anyone who prefers a signature from their own key: the steps are in
the previous revision of this document (release v0.6.0, `docs/owner-acceptance-0.2.1.md`).

## If something fails
| Symptom | Meaning |
|---|---|
| `continuity` fails with "predecessor ... differs from the policy pin" | you used `main`'s `trust/policy.json`; use the policy from the source revision (step 0/1) |
| `AUTH ...: committer of commit ... is not <you>` | the commit was squash/rebase-merged or made through the web UI; GitHub is the committer. Recommit locally, signed, and push |
| `AUTH ...: not a validly signed commit` | signing key not registered or `commit.gpgsign` off |
| `AUTH ...: <you> is authenticated but is not an approver` | the policy you passed is not the one with your approver entry |
| `current acceptance: indeterminate` (exit 5), code `api-failure` / `ref-unresolved` / `listing-failed` | GitHub unreachable or the ref unresolvable: retry; this is not a verdict about the release |
| `indeterminate`, code `ref-moved` | something was pushed while reading: re-run |
| `indeterminate`, code `record-removed` | a record was deleted from `authorizations/` history. Restore it with a revert **by the approver** (never delete records). A path that anyone else ever touched stays unauthenticatable; publish a fresh record under a new name instead. The platform path has no acknowledgement mechanism |
| `indeterminate`, code `history-rewritten` | the evidence ref no longer contains a commit this machine audited earlier (force-push). Investigate before anything else; remove the audit state only once you understand why |
| `indeterminate`, code `history-too-long` / `audit-incomplete` | more than 10 000 commits touch `authorizations/`, or the per-run budget was exceeded: re-run with `--audit-state` until it completes |
| `verified-unaccepted` (exit 3) after the record was pushed | the state was read and the record is not authentic or not authorized: read the `AUTH` lines |

## Other candidates
The same rule holds for every candidate: verify with the trust policy of that release's source revision (the packet lists
its digest), never with a later `main` policy. Accepting 0.3.0, 0.4.0 or 0.5.0 is a separate decision about a separate
archive digest; accepting one does not accept another.
