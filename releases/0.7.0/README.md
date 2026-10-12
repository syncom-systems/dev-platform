# 0.7.0 (stable candidate; verified-unaccepted)

New authorization provider `github-environment-approval` (ADR 0020): the owner accepts a release by approving a run of the
manual `accept` workflow on the `owner-approval` environment; the workflow attests the authorization record and
`tools/verify_release.py` verifies it (pinned workflow, ref, trigger, runner), then applies the unchanged approver, scope
and validity policy. The signed-commit provider is unchanged. Trust anchor change: `verify_release.py` has a new digest
(`a2d53075…6f2e`; `identity.json`). Owner procedure: `docs/owner-acceptance-0.2.1.md`; packet: `ACCEPTANCE-PACKET.md`.

Reproduce (a release is verified with the policy of its own source revision):
```
git show 583413c49dc3bdbe84ff08f0d17092ac8db7f81f:trust/policy.json > policy-0.7.0.json   # sha256 c371ab9f…e1ad
gh release download v0.7.0 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.7.0.tar.gz --version 0.7.0 \
  --source-revision 583413c49dc3bdbe84ff08f0d17092ac8db7f81f \
  --archive-sha256 eddf140a7cf4a57d97b9380afbe921b220a28ae257d9eb27b7dbd2c8f4c50931 \
  --environment d/dev-platform-0.7.0.build-environment.json --continuity d/dev-platform-0.7.0.continuity.json \
  --policy policy-0.7.0.json
```
after checking the anchors with `shasum -a 256`. Records: `verification.independent.json` (32/32, `verified-unaccepted`),
`verification.ci.json`, `continuity.json`, `build-environment.json`, `qualification/` (CI run, sha256 index),
`rejections.txt` (a record claiming the new provider without the workflow's attestation, rejected by real GitHub).
No authorization exists. Acceptance is per archive digest: no other candidate's state is implied.
