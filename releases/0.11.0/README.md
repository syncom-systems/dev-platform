# 0.11.0 (verified-unaccepted)

Published by release.yml (https://github.com/syncom-systems/dev-platform/actions/runs/39760925914) from tag `v0.11.0` on `0d388486e679bed5517d5c513a719e47c9290c9d`. Generated
by `tools/release.py records`. Identity and pins: `identity.json`. Records: `verification.ci.json` (the workflow's),
`verification.independent.json` (the tagged verifier and policy, re-run outside CI), `build-environment.json`,
`continuity.json`, `homebrew/dev-platform.rb` (the tap formula).

Reproduce (a release is verified with the verifier and policy of its own source revision):
```
git show 0d388486e679bed5517d5c513a719e47c9290c9d:trust/policy.json > policy.json
git show 0d388486e679bed5517d5c513a719e47c9290c9d:tools/verify_release.py > verify_release.py
gh release download v0.11.0 --repo syncom-systems/dev-platform --dir d
python3 -I verify_release.py d/dev-platform-0.11.0.tar.gz --version 0.11.0 \
  --source-revision 0d388486e679bed5517d5c513a719e47c9290c9d --archive-sha256 df2a9f58861036b0725143e300c5887fd7c9c4c292d0e752c9696975a2ca2ee0 \
  --tree-digest fde7e708bc3e7ee3e62dde83dd3e5209b47c3d22da3f1a84b786b136dcd80372 --environment d/dev-platform-0.11.0.build-environment.json \
  --continuity d/dev-platform-0.11.0.continuity.json --policy policy.json
```
