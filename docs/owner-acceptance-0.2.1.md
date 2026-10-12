# Owner acceptance of v0.2.1: executable steps

Subject: archive sha256 `3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044`, scope `platform-baseline`
(`releases/0.2.1/ACCEPTANCE-PACKET.md`). Only the owner can do this. Neither the platform nor its agent creates, signs,
attributes or commits the authorization; until the record below passes the verifier the state is `verified-unaccepted`.
The immutable v0.2.1 release and `releases/0.2.1/` are not modified by any step; evidence is retained in a new directory.

Absence of the record blocks nothing else: development, other candidates and application releases proceed independently.

| Part | Who | What it can do |
|---|---|---|
| **A. Preflight** | owner or agent | read-only: re-derive the anchors and the verification; confers nothing |
| **B. Establish identity and sign** | **the owner only** | the only steps that create authority: your approver entry (trust anchor) and your signed authorization record |
| **C. Verify and retain** | owner or agent | reads what the owner pushed, with the owner's pins; writes evidence, never an authorization |

The agent runs A and, once the owner has done B, C. It never runs B, never holds the owner's key or account, and reports
machine-verifiable acceptance only when C's verifier says `accepted` from the owner-signed record. A positive
platform-acceptance qualification is run only after that, from real owner-created evidence; none is fabricated before.

## Read this first: which policy file
A release is verified against the trust policy that belongs to it. `trust/policy.json` on `main` pins the *latest*
candidate's predecessor, so it **fails the continuity check for v0.2.1** (observed: "predecessor version differs from the
policy pin"). Do not edit `trust/policy.json` for this acceptance. Use v0.2.1's own policy, byte-exact from its source
revision, plus your approver entry, as a separate file you pin by digest. The authority comes from the digest you pin
out of band, not from where the file is stored.

Prerequisites: your GitHub commit-signing key is registered on your account (commits show "Verified" on GitHub); `gh` is
authenticated as you; a clean checkout of `main` you trust; `git config commit.gpgsign true` (or `-S` on every commit).
Push the signed commits **directly to `main`** (no branch protection blocks it). If you prefer a PR, merge it with a
**merge commit**; a squash or rebase merge makes GitHub the committer and the record is ignored.

## Part A. Preflight (read-only; confers nothing; owner or agent)
```
S=750d065e9eab486b7153079b7162013b19cc8aad
mkdir -p ~/dp-verify-0.2.1                                     # outside the repo; untrusted downloads
git show $S:trust/policy.json > ~/dp-verify-0.2.1/policy-0.2.1.json; shasum -a 256 ~/dp-verify-0.2.1/policy-0.2.1.json
#   must equal 403f9131d130629d988f46abbcc4980635c16c1646b9967b19b3b45594db9cc7
cd ~/dp-verify-0.2.1
gh release download v0.2.1 -R syncom-systems/dev-platform --pattern '*'
shasum -a 256 dev-platform-0.2.1.tar.gz                       # must equal 3cc47abb…2044
cd <your checkout of main>
python3 -I tools/verify_release.py ~/dp-verify-0.2.1/dev-platform-0.2.1.tar.gz --version 0.2.1 \
  --source-revision $S --archive-sha256 3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044 \
  --environment ~/dp-verify-0.2.1/dev-platform-0.2.1.build-environment.json \
  --continuity ~/dp-verify-0.2.1/dev-platform-0.2.1.continuity.json --policy ~/dp-verify-0.2.1/policy-0.2.1.json
```
Expected: every check `PASSED` and `acceptance: verified-unaccepted`. Anything else: stop and look (do not sign).
Also confirm the anchors: `shasum -a 256 tools/verify_release.py tools/verify_platform_current.py tools/verify_app_release.py`;
`verify_release.py` must equal `791713d01198f47045c7abb210e73dd94976d266ed12351cfce53ea9d2b466a9` (unchanged since 0.2.1)
and `install_release.py` `473a2c73eb71904ea6ee0e010f2288976126d4560e3efd11c33c11e44f15bb93`. Record the other two as
your own pins out of band.

## Part B1. OWNER ONLY: establish your approver identity (trust anchor change)
```
mkdir -p releases/0.2.1-acceptance
cp ~/dp-verify-0.2.1/policy-0.2.1.json releases/0.2.1-acceptance/trust-policy.json
```
Edit `releases/0.2.1-acceptance/trust-policy.json`, `authorization.approvers` (currently `[]`):
```json
{"id": "owner", "provider": "github-signed-commit", "login": "<your GitHub login>",
 "roles": ["owner"], "may_approve": ["platform-release"], "may_confer": ["platform-baseline"]}
```
Do not add `application-release` here: application approvals use a separate application policy (ADR 0019).
```
git add releases/0.2.1-acceptance/trust-policy.json
git commit -S -m "Owner approver policy for v0.2.1 acceptance"
git push origin main
git log -1 --format='%H %G?' -- releases/0.2.1-acceptance/trust-policy.json      # %G? must be G
shasum -a 256 releases/0.2.1-acceptance/trust-policy.json                         # this is the policy pin
```
Record that digest out of band (password manager, paper): it is the one thing the verification trusts you for.

## Part B2. OWNER ONLY: sign and commit the authorization record
```
mkdir -p authorizations
cp releases/0.2.1/authorization.template.json authorizations/platform-0.2.1.json
```
Replace every `<...>`: `id` (e.g. `platform-0.2.1-owner`), `decision: approved`, `decided_by.id` (`owner`),
`identity_assertion.login` (your login), `identity_assertion.path` (`authorizations/platform-0.2.1.json`), `decided_at`
(UTC now, `YYYY-MM-DDTHH:MM:SSZ`), optional `validity.not_after`; delete the `_comment` line. Leave `subject.digest`,
`scope.confers: ["platform-baseline"]`, `basis` and `retention` as they are unless you intend otherwise.
```
git add authorizations/platform-0.2.1.json
git commit -S -m "Authorize dev-platform 0.2.1 (platform-baseline)"
git push origin main
git log --format='%H %G? %an <-> %cn' -- authorizations/platform-0.2.1.json    # every line: G, same author and committer
```
The record is write-once: do not edit it after signing (a modified record is ignored). Changing your mind is a new
signed record (`decision: revoked`, or a superseding one), never an edit and never a deletion.

## Part C1. Verify, as a current decision (owner or agent, after B)
First the pinned anchor, exactly as in step 0 plus the record and your policy:
```
python3 -I tools/verify_release.py ~/dp-verify-0.2.1/dev-platform-0.2.1.tar.gz --version 0.2.1 \
  --source-revision 750d065e9eab486b7153079b7162013b19cc8aad \
  --archive-sha256 3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044 \
  --environment ~/dp-verify-0.2.1/dev-platform-0.2.1.build-environment.json \
  --continuity ~/dp-verify-0.2.1/dev-platform-0.2.1.continuity.json \
  --policy releases/0.2.1-acceptance/trust-policy.json --authorization authorizations/platform-0.2.1.json \
  --out ~/dp-verify-0.2.1/verification.owner.json
```
Expected: all checks `PASSED`, `AUTH ... authentic`, `acceptance: accepted`, `confers: ["platform-baseline"]`.

Then the same question as a **current** one (it also reads every record in the evidence repository at one commit,
audits the history for deleted records, and fails closed if that cannot be established). This is the form to use
whenever acceptance matters later (a deployment gate, a release-eligibility decision):
```
python3 -I tools/verify_platform_current.py ~/dp-verify-0.2.1/dev-platform-0.2.1.tar.gz \
  --verify-release tools/verify_release.py --verify-release-sha256 791713d0…b466a9 \
  --app-verifier tools/verify_app_release.py --app-verifier-sha256 <your pin> \
  --version 0.2.1 --source-revision 750d065e9eab486b7153079b7162013b19cc8aad \
  --archive-sha256 3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044 \
  --environment ~/dp-verify-0.2.1/dev-platform-0.2.1.build-environment.json \
  --continuity ~/dp-verify-0.2.1/dev-platform-0.2.1.continuity.json \
  --policy releases/0.2.1-acceptance/trust-policy.json --policy-sha256 <your policy pin> \
  --out ~/dp-verify-0.2.1/current.owner.json
```
Expected: `current acceptance: accepted` (exit 0) and a `currency` block naming the evidence commit.
Add `--audit-state <dir inside your checkout or scratch space>` to reuse already-audited history between runs (cost only).
Exit codes: 0 accepted, 3 verified-unaccepted (the state was read; nobody currently accepts it), 5 indeterminate (the state
could not be read or audited; `currency.reasons` has coded causes), 4 historical-acceptance, 1 failed, 2 usage. Run it again whenever
you need to know: a later revocation changes the answer to `verified-unaccepted` with no flag to remember. `--historical`
exists for inspecting old evidence offline of any later change; it can only say `historical-acceptance`, which is not
a current acceptance.

## Part C2. Retain the evidence (owner or agent; a PR is fine, it touches nothing under `authorizations/`)
```
mkdir releases/0.2.1-acceptance/evidence
cp ~/dp-verify-0.2.1/verification.owner.json ~/dp-verify-0.2.1/current.owner.json releases/0.2.1-acceptance/evidence/
shasum -a 256 tools/verify_release.py tools/verify_platform_current.py tools/verify_app_release.py \
  releases/0.2.1-acceptance/trust-policy.json authorizations/platform-0.2.1.json > releases/0.2.1-acceptance/evidence/pins.txt
git add releases/0.2.1-acceptance && git commit -S -m "Retain v0.2.1 acceptance verification" && git push origin main
```
Only report machine-verifiable acceptance if `acceptance.state` is `accepted` from the owner-signed record. If any check
fails, retain the output as-is and do not edit the record after signing; supersede it with a new signed record instead.

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
