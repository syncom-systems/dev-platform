# Owner acceptance of v0.2.1: executable steps

Subject: archive sha256 `3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044`, scope `platform-baseline`
(`releases/0.2.1/ACCEPTANCE-PACKET.md`). Only the owner can do this. Neither the platform nor its agent creates, signs,
attributes or commits the authorization; until the record below passes the verifier the state is `verified-unaccepted`.
The immutable v0.2.1 release and `releases/0.2.1/` are not modified by any step; evidence is retained in a new directory.

Prerequisites: your GitHub commit-signing key is registered on your account (commits show "Verified" on GitHub); `gh` is
authenticated as you; a clean checkout of `main` you trust. Work on a branch in that checkout and merge with a **merge
commit** (or push directly): a squash or rebase merge makes GitHub the committer and the record is ignored.

## 1. Establish your approver identity (trust anchor change)
```
git switch -c owner/approver-identity
```
Edit `trust/policy.json`, `authorization.approvers`:
```json
{"id": "owner", "provider": "github-signed-commit", "login": "<your GitHub login>",
 "roles": ["owner"], "may_approve": ["platform-release"], "may_confer": ["platform-baseline"]}
```
Do not add `application-release` here: application approvals use a separate application policy (ADR 0019).
```
git commit -S -am "Trust policy: owner as platform-release approver"
git push -u origin owner/approver-identity    # open the PR; merge with a MERGE COMMIT
git switch main && git pull
git log -1 --format='%H %G?' -- trust/policy.json      # %G? must be G (good signature)
shasum -a 256 trust/policy.json tools/verify_release.py tools/install_release.py
```
Record these three digests out of band. The policy digest is the new anchor you pin; the verifier digest must equal
`791713d01198f47045c7abb210e73dd94976d266ed12351cfce53ea9d2b466a9` and the installer
`473a2c73eb71904ea6ee0e010f2288976126d4560e3efd11c33c11e44f15bb93` unless you deliberately move them.

## 2. Sign and commit the authorization record
```
git switch -c owner/accept-0.2.1
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
git push -u origin owner/accept-0.2.1          # PR; merge with a MERGE COMMIT
git switch main && git pull
git log --format='%H %G?' -- authorizations/platform-0.2.1.json    # every line: G
```

## 3. Independently verify against the pinned artifact, verifier and policy
```
mkdir -p ~/dp-verify-0.2.1 && cd ~/dp-verify-0.2.1          # outside the repo; untrusted downloads
gh release download v0.2.1 -R syncom-systems/dev-platform --pattern '*'
shasum -a 256 dev-platform-0.2.1.tar.gz                       # must equal 3cc47abb…2044
REV=$(git ls-remote https://github.com/syncom-systems/dev-platform refs/tags/v0.2.1^{} | cut -f1)   # expect 750d065e…
cd <your checkout of main>
python3 -I tools/verify_release.py ~/dp-verify-0.2.1/dev-platform-0.2.1.tar.gz --version 0.2.1 \
  --source-revision "$REV" \
  --archive-sha256 3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044 \
  --environment ~/dp-verify-0.2.1/dev-platform-0.2.1.build-environment.json \
  --continuity ~/dp-verify-0.2.1/dev-platform-0.2.1.continuity.json \
  --policy trust/policy.json --authorization authorizations/platform-0.2.1.json \
  --out ~/dp-verify-0.2.1/verification.owner.json
```
(Same invocation as `releases/0.2.1/README.md`, plus the authorization.) Before running, check `shasum -a 256 tools/verify_release.py trust/policy.json` equals the pins
from step 1. Expected: all checks `PASSED`, `AUTH ... authentic`, `acceptance: accepted`, `confers: ["platform-baseline"]`.

## 4. Retain the evidence
```
git switch -c owner/accept-0.2.1-evidence
mkdir releases/0.2.1-acceptance
cp ~/dp-verify-0.2.1/verification.owner.json releases/0.2.1-acceptance/
shasum -a 256 tools/verify_release.py trust/policy.json authorizations/platform-0.2.1.json > releases/0.2.1-acceptance/pins.txt
git add releases/0.2.1-acceptance && git commit -S -m "Retain v0.2.1 acceptance verification" && git push -u origin HEAD
```
Only report machine-verifiable acceptance if `acceptance.state` is `accepted` from the owner-signed record. If any check
fails, retain the output as-is and do not edit the record after signing (a modified record is ignored); supersede it with a
new signed record instead.
