# 0.2.1 (stable candidate; verified-unaccepted)

Corrective patch for 0.2.0 (installer + continuity). Identities and pins: `identity.json`; owner packet:
`ACCEPTANCE-PACKET.md`; template (not a decision): `authorization.template.json`. Reproduce:
```
gh release download v0.2.1 --repo syncom-systems/dev-platform --dir d
python3 tools/verify_release.py d/dev-platform-0.2.1.tar.gz --version 0.2.1 \
  --source-revision 750d065e9eab486b7153079b7162013b19cc8aad \
  --archive-sha256 3cc47abb71afcd279383f2c46386f46183f460ff3e91af7656a407030ba42044 \
  --environment d/dev-platform-0.2.1.build-environment.json --continuity d/dev-platform-0.2.1.continuity.json \
  --policy trust/policy.json
```
after checking the anchors with `shasum -a 256`. No authorization exists.
