# 0.4.0 (stable candidate; verified-unaccepted)

Qualification increment on the application-release approval path (ADR 0019). Identities and pins: `identity.json`; owner
packet: `ACCEPTANCE-PACKET.md`; template (not a decision): `authorization.template.json`; qualification records and their
sha256 index: `qualification/`. Reproduce:
```
gh release download v0.4.0 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.4.0.tar.gz --version 0.4.0 \
  --source-revision ea477c86d0dd388a6a7d93c87366a9931ad46a23 \
  --archive-sha256 91d81005dbd5dc082fb6ebed37ebc2a7173a7e336feb2a25764a8d5ee2daeb2e \
  --environment d/dev-platform-0.4.0.build-environment.json --continuity d/dev-platform-0.4.0.continuity.json \
  --policy trust/policy.json
```
after checking the anchors with `shasum -a 256`. No authorization exists. Acceptance is per archive digest: 0.2.1 and 0.3.0 are
separate candidates and neither is implied.
