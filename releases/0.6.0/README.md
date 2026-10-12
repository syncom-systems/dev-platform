# 0.6.0 (stable candidate; verified-unaccepted)

Operational robustness of current-state authorization (ADR 0019 item 12 refinement): an unestablishable current state is
its own result, `indeterminate` (exit 5), distinct from `unapproved`; the evidence-history audit scales (`--audit-state`);
a deleted record is recoverable without ever dropping it. Identities and pins:
`identity.json`; owner packet: `ACCEPTANCE-PACKET.md`; template (not a decision): `authorization.template.json`;
qualification records and their sha256 index: `qualification/`.

A release is verified with the trust policy of its own source revision (it pins the predecessor); `main` moves on.
Reproduce:
```
git show 4994d2b55b6df699795cd121a0a78c0a0cd33963:trust/policy.json > policy-0.6.0.json   # sha256 437bff36…232
gh release download v0.6.0 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.6.0.tar.gz --version 0.6.0 \
  --source-revision 4994d2b55b6df699795cd121a0a78c0a0cd33963 \
  --archive-sha256 98902922986ebead1d6a00943dcc98cc464ce3cc317faf8c39de7299bd778e1d \
  --environment d/dev-platform-0.6.0.build-environment.json --continuity d/dev-platform-0.6.0.continuity.json \
  --policy policy-0.6.0.json
```
after checking the anchors with `shasum -a 256`. The same question as a current decision: `tools/verify_platform_current.py`
(`current-state.json`). No authorization exists. Acceptance is per archive digest: 0.2.1, 0.3.0, 0.4.0 and 0.5.0 are separate
candidates and none is implied.

Other records here: `rejections.txt` (live negatives), `live-qualification.json` (11 cases against real GitHub, all as designed), `platform-acceptance-required.txt`,
`owner-preflight-0.2.1/current-state.json` (read-only check of v0.2.1 as a current decision: `verified-unaccepted`, no
records in the evidence repository).
