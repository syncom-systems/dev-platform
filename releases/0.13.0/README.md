# 0.13.0 (verified)

Published by release.yml (https://github.com/syncom-systems/dev-platform/actions/runs/40010304049) from tag `v0.13.0` on `92096b7820ffbcaa29037bbd3ed5d837edff9641`. Generated
by `tools/release.py records`. Identity and pins: `identity.json`. Records: `verification.ci.json` (the workflow's),
`verification.independent.json` (the tagged verifier and policy, re-run outside CI), `build-environment.json`,
`continuity.json`, `homebrew/dev-platform.rb` (the tap formula).

Reproduce (a release is verified with the verifier and policy of its own source revision):
```
git show 92096b7820ffbcaa29037bbd3ed5d837edff9641:trust/policy.json > policy.json
git show 92096b7820ffbcaa29037bbd3ed5d837edff9641:tools/verify_release.py > verify_release.py
gh release download v0.13.0 --repo syncom-systems/dev-platform --dir d
python3 -I verify_release.py d/dev-platform-0.13.0.tar.gz --version 0.13.0 \
  --source-revision 92096b7820ffbcaa29037bbd3ed5d837edff9641 --archive-sha256 4c1a766982a52c27eb0943af356dea1a70e1702f9dc8f52b9563089eb88f1126 \
  --tree-digest 47493e1b99172e0c05f2f2b9252061e2805bc2ea49cf6b36fc15da910518c71e --environment d/dev-platform-0.13.0.build-environment.json \
  --continuity d/dev-platform-0.13.0.continuity.json --policy policy.json
```
