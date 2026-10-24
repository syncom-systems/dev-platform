# 0.16.0 (verified)

Published by release.yml (https://github.com/syncom-systems/dev-platform/actions/runs/40101744004) from tag `v0.16.0` on `99374ccdae5eb649b91dda63ccd85376c69171c9`. Generated
by `tools/release.py records`. Identity and pins: `identity.json`. Records: `verification.ci.json` (the workflow's),
`verification.independent.json` (the tagged verifier and policy, re-run outside CI), `build-environment.json`,
`continuity.json`, `homebrew/dev-platform.rb` (the tap formula).

Reproduce (a release is verified with the verifier and policy of its own source revision):
```
git show 99374ccdae5eb649b91dda63ccd85376c69171c9:trust/policy.json > policy.json
git show 99374ccdae5eb649b91dda63ccd85376c69171c9:tools/verify_release.py > verify_release.py
gh release download v0.16.0 --repo syncom-systems/dev-platform --dir d
python3 -I verify_release.py d/dev-platform-0.16.0.tar.gz --version 0.16.0 \
  --source-revision 99374ccdae5eb649b91dda63ccd85376c69171c9 --archive-sha256 1b26322af31fba17be42c3282b9ad4445afcc068672c55ed83c0e108636aecd3 \
  --tree-digest db307a51b36b3ed3ebc8b681a4603491cea14f5c5938e375ccc2a100455aa7a0 --environment d/dev-platform-0.16.0.build-environment.json \
  --continuity d/dev-platform-0.16.0.continuity.json --policy policy.json
```
