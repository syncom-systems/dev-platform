# 0.17.0 (verified)

Published by release.yml (https://github.com/syncom-systems/dev-platform/actions/runs/40320527217) from tag `v0.17.0` on `8ec84f73c108b823324595ac39788052ea648617`. Generated
by `tools/release.py records`. Identity and pins: `identity.json`. Records: `verification.ci.json` (the workflow's),
`verification.independent.json` (the tagged verifier and policy, re-run outside CI), `build-environment.json`,
`continuity.json`, `homebrew/dev-platform.rb` (the tap formula).

Reproduce (a release is verified with the verifier and policy of its own source revision):
```
git show 8ec84f73c108b823324595ac39788052ea648617:trust/policy.json > policy.json
git show 8ec84f73c108b823324595ac39788052ea648617:tools/verify_release.py > verify_release.py
gh release download v0.17.0 --repo syncom-systems/dev-platform --dir d
python3 -I verify_release.py d/dev-platform-0.17.0.tar.gz --version 0.17.0 \
  --source-revision 8ec84f73c108b823324595ac39788052ea648617 --archive-sha256 cd9e8938688b0b1a1c1d5cb7d5a88eb71d04f1dc8a31e23c062e8a4198920bde \
  --tree-digest 80a8e4ed5afd43d0d59a3ef2b6ca8de7a8d21900778496f6e32911ab00635f98 --environment d/dev-platform-0.17.0.build-environment.json \
  --continuity d/dev-platform-0.17.0.continuity.json --policy policy.json
```
