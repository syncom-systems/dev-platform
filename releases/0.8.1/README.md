# 0.8.1 (stable candidate; verified-unaccepted)

Patch release over 0.8.0 (implementation fix, see `CHANGELOG.md`): `tools/consumer_run.py` proves the Bazel Rust toolchain over exactly the
consumer's own Bazel check targets (0.8.0 used `//...`); the consumer evidence verdict is `consistent`/`inconsistent` and
`verification.json` lists `not_established`; reference resolver for the infra contract; workflow timeouts. `tools/verify_release.py` is
unchanged from 0.7.0 (`a2d53075…`; lineage: `docs/verifier-anchor-lineage.md`). Identities and pins: `identity.json`; packet:
`ACCEPTANCE-PACKET.md`.

Reproduce (a release is verified with the policy of its own source revision):
```
git show 5fa25c68814ee9f4d284682215fa4c98198103ff:trust/policy.json > policy-0.8.1.json   # sha256 90748710…1120
gh release download v0.8.1 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.8.1.tar.gz --version 0.8.1 \
  --source-revision 5fa25c68814ee9f4d284682215fa4c98198103ff \
  --archive-sha256 5671100327d3b8bdfbf74277ae0b21bde39ec2f1f85d4abde12799647740a898 \
  --environment d/dev-platform-0.8.1.build-environment.json --continuity d/dev-platform-0.8.1.continuity.json \
  --policy policy-0.8.1.json
```
Records: `verification.independent.json` (32/32, `verified-unaccepted`), `verification.ci.json`, `continuity.json`, `build-environment.json`,
`qualification/` (CI run, sha256 index; Rust proof ok on both Bazel profiles, linux and darwin), `rejections.txt`. No authorization exists
for this release; acceptance is per archive digest.
