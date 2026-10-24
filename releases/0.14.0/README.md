# 0.14.0 (verified)

Published by release.yml (https://github.com/syncom-systems/dev-platform/actions/runs/40077853507) from tag `v0.14.0` on `b7cef929f226a2cd378c55047c0ccb936582e1a7`. Generated
by `tools/release.py records`. Identity and pins: `identity.json`. Records: `verification.ci.json` (the workflow's),
`verification.independent.json` (the tagged verifier and policy, re-run outside CI), `build-environment.json`,
`continuity.json`, `homebrew/dev-platform.rb` (the tap formula).

Reproduce (a release is verified with the verifier and policy of its own source revision):
```
git show b7cef929f226a2cd378c55047c0ccb936582e1a7:trust/policy.json > policy.json
git show b7cef929f226a2cd378c55047c0ccb936582e1a7:tools/verify_release.py > verify_release.py
gh release download v0.14.0 --repo syncom-systems/dev-platform --dir d
python3 -I verify_release.py d/dev-platform-0.14.0.tar.gz --version 0.14.0 \
  --source-revision b7cef929f226a2cd378c55047c0ccb936582e1a7 --archive-sha256 c1b82b5633476cc16f4d04543fd147b01a926b382bd5bc59dc54da7643084444 \
  --tree-digest b83a2d472e7fa621b075b7fd399f0197447b0ef112b593f6f3ef1d50e4060a57 --environment d/dev-platform-0.14.0.build-environment.json \
  --continuity d/dev-platform-0.14.0.continuity.json --policy policy.json
```
