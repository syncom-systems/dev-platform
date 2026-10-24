# 0.15.0 (verified)

Published by release.yml (https://github.com/syncom-systems/dev-platform/actions/runs/40091895420) from tag `v0.15.0` on `0c6af99b24889870820ce2459a83980ee4e208c5`. Generated
by `tools/release.py records`. Identity and pins: `identity.json`. Records: `verification.ci.json` (the workflow's),
`verification.independent.json` (the tagged verifier and policy, re-run outside CI), `build-environment.json`,
`continuity.json`, `homebrew/dev-platform.rb` (the tap formula).

Reproduce (a release is verified with the verifier and policy of its own source revision):
```
git show 0c6af99b24889870820ce2459a83980ee4e208c5:trust/policy.json > policy.json
git show 0c6af99b24889870820ce2459a83980ee4e208c5:tools/verify_release.py > verify_release.py
gh release download v0.15.0 --repo syncom-systems/dev-platform --dir d
python3 -I verify_release.py d/dev-platform-0.15.0.tar.gz --version 0.15.0 \
  --source-revision 0c6af99b24889870820ce2459a83980ee4e208c5 --archive-sha256 8f6a662cb051cbfac0b6e6d7c1a55dfc3799ddacab4b6b95dffb75caf5a9bd9f \
  --tree-digest 2e572b0802935fc2b47bf00fe612b6d7d93bde942dd8456872a96bcf3371592e --environment d/dev-platform-0.15.0.build-environment.json \
  --continuity d/dev-platform-0.15.0.continuity.json --policy policy.json
```
