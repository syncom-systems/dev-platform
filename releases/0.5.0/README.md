# 0.5.0 (stable candidate; verified-unaccepted)

Authorization freshness (ADR 0019 item 12): current deployment, release-eligibility and rollback decisions read the
current authorization state and fail closed; historical inspection is a separate, labelled purpose. Identities and pins:
`identity.json`; owner packet: `ACCEPTANCE-PACKET.md`; template (not a decision): `authorization.template.json`;
qualification records and their sha256 index: `qualification/`.

A release is verified with the trust policy of its own source revision (it pins the predecessor); `main` moves on.
Reproduce:
```
git show 6d954c2453eeb0b7b81451b2f8165a0938117933:trust/policy.json > policy-0.5.0.json   # sha256 d14beada…49e
gh release download v0.5.0 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.5.0.tar.gz --version 0.5.0 \
  --source-revision 6d954c2453eeb0b7b81451b2f8165a0938117933 \
  --archive-sha256 9d6a9bc9e1a2f31f767368e6cc37f8d534824d01e18aedefc35708ab2c4646d3 \
  --environment d/dev-platform-0.5.0.build-environment.json --continuity d/dev-platform-0.5.0.continuity.json \
  --policy policy-0.5.0.json
```
after checking the anchors with `shasum -a 256`. The same question as a current decision: `tools/verify_platform_current.py`
(`current-state.json`). No authorization exists. Acceptance is per archive digest: 0.2.1, 0.3.0 and 0.4.0 are separate
candidates and none is implied.

Other records here: `rejections.txt` (live negatives), `live-qualification.json` (final run, 11 cases) and
`live-qualification.attempt-1.json` (first run: 10 of 11 as designed; the 11th, "record never committed", behaved correctly
but the harness expected the old wording "no commit on main touches", while evidence is now read at a commit id; the
expectation was corrected and the run repeated, both retained), `platform-acceptance-required.txt`,
`owner-preflight-0.2.1/current-state.json` (read-only check of v0.2.1 as a current decision: `verified-unaccepted`, no
records in the evidence repository).
