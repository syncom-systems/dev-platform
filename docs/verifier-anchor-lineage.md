# Lineage of the platform verifier anchor (`tools/verify_release.py`)

The independent verifier is a trust anchor: operators pin its sha256. The pin changed once, in 0.7.0. This page reconciles it.

| Releases | `verify_release.py` sha256 | Source |
|---|---|---|
| 0.2.1, 0.3.0, 0.4.0, 0.5.0, 0.6.0 | `791713d01198f47045c7abb210e73dd94976d266ed12351cfce53ea9d2b466a9` | `releases/<v>/identity.json` equals the blob at tag `v<v>` for each |
| 0.7.0, 0.8.0 | `a2d53075b8bf11bb14f4a2dffb0b40fc6e66b04af73801951fcd768ba29f6f2e` | same; 0.8.0 reports it as "unchanged" relative to 0.7.0, which is correct and not a return to the old digest |

## Was the change legitimate, documented and independently verified?
- **Legitimate and scoped.** Exactly one commit changed the file between 0.6.0 and 0.7.0: PR #104 (`1475cde`, ADR 0020), made at the
  owner's direction ("make it simple", approval by a logged-in GitHub click). The diff is one hunk: one line removed (the provider
  registry `PROVIDERS = {"github-signed-commit": ...}`) and 81 added (the `github-environment-approval` provider function and the
  two-entry registry). Nothing else in the file changed; `_auth_github_signed_commit` and every other check are byte-identical.
- **Documented.** ADR 0020, the 0.7.0 packet (`releases/0.7.0/ACCEPTANCE-PACKET.md`, "changed: new provider"), `CHANGELOG.md`
  ("Trust anchor change"), the 0.7.0 `identity.json` pin, and the v0.2.1 acceptance evidence
  (`releases/0.2.1-acceptance/evidence/pins.txt` records the new digest).
- **Independently verified (reproducible).** Run the old (`git show v0.6.0:tools/verify_release.py`) and the new verifier over every
  published archive 0.2.1 to 0.8.0 with that release's own policy, source revision and records: both produce the same 32 checks with the
  same statuses and the same `acceptance.state` (`verified-unaccepted`) for all seven releases (checked 2026-10-12). The only behavioural
  difference is the new provider: on the v0.2.1 owner record the old verifier says `ignored (identity provider
  'github-environment-approval' is not supported (fail closed))`, the new one `authentic` and `accepted`. The signed-commit provider
  tests (`tests/test_authorization.py`) were not changed by the PR; `tests/test_environment_approval.py` was added (9 cases:
  unattested, edited, wrong workflow/ref/trigger/runner/repo/issuer, unknown approver, missing policy, revocation, service failure).

## Consequences to keep in mind
- The v0.2.1 acceptance is verifiable only with a verifier that implements the environment-approval provider (`a2d53075…` or later
  with the same provider); an operator still pinning `791713d0…` correctly sees `verified-unaccepted`, never a false acceptance.
- Each pin change is a trust-anchor change: it needs a documented reason, a minimal diff and this kind of cross-release regression
  before it is adopted, and it is the owner's decision. Routine predecessor-continuity pin updates are not anchor changes.
