# 0.8.2 (stable candidate; verified-unaccepted)

Corrective patch over 0.8.1 (see `CHANGELOG.md`): the reusable consumer workflow `consumer-pilot.yml` supplies the read-only job token to
`gh attestation verify` (the installer alone receives it), needs only `contents: read` (attestation is the separate
`consumer-pilot-attest.yml`), and keeps the consumer, the platform source and the evidence in sibling directories so the consumer's tree
stays clean. `tools/verify_release.py` is unchanged from 0.7.0 (`a2d53075…`; `docs/verifier-anchor-lineage.md`). Identities and pins:
`identity.json`; packet: `ACCEPTANCE-PACKET.md`.

Reproduce (a release is verified with the policy of its own source revision):
```
git show f617b37edde2b5e550c813ea4b47c886a761dc62:trust/policy.json > policy-0.8.2.json   # file sha256 577bcf92…98cb
gh release download v0.8.2 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.8.2.tar.gz --version 0.8.2 \
  --source-revision f617b37edde2b5e550c813ea4b47c886a761dc62 \
  --archive-sha256 993c03fda1b0958dcc2ebee5484cdf620a7a953cf62df041bcddf7713a84f66f \
  --environment d/dev-platform-0.8.2.build-environment.json --continuity d/dev-platform-0.8.2.continuity.json \
  --policy policy-0.8.2.json
```
Records: `verification.independent.json` (32/32, `verified-unaccepted`), `verification.ci.json`, `continuity.json`, `build-environment.json`,
`qualification/` (CI run, sha256 index), `rejections.txt`, `consumer-workflow-validation/` (a hosted consumer run through the reusable
workflows at this revision: run 38316395793, evidence `consistent` 17/17, Rust 1.97.1 provided by Bazel, no decoy invoked, evidence
attestation verified with `gh attestation verify`). No authorization exists for this release; acceptance is per archive digest.
