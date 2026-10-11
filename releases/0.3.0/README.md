# 0.3.0 (stable candidate; verified-unaccepted)

Application-release trust chain (ADR 0019). Identities and pins: `identity.json`; owner packet: `ACCEPTANCE-PACKET.md`;
template (not a decision): `authorization.template.json`; chain qualification over real results:
`app-release-qualification.json`. Reproduce:
```
gh release download v0.3.0 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.3.0.tar.gz --version 0.3.0 \
  --source-revision 6ad52306e72ab3c3ad0ad7023c58015634880d31 \
  --archive-sha256 eb04ce489f3963ab24ed2e634f3213a4d1eabef87c4d667a7f2aaa040b9c604a \
  --environment d/dev-platform-0.3.0.build-environment.json --continuity d/dev-platform-0.3.0.continuity.json \
  --policy trust/policy.json
```
after checking the anchors with `shasum -a 256`. No authorization exists. 0.2.1 is a separate candidate: acceptance is per
archive digest and neither implies the other.
