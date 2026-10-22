# 0.12.1 (verified)

Published by release.yml (https://github.com/syncom-systems/dev-platform/actions/runs/39845322381) from tag `v0.12.1` on `75269bc0f30fb88593c7904e7778fcdda1cb6a6e`. Generated
by `tools/release.py records`. Identity and pins: `identity.json`. Records: `verification.ci.json` (the workflow's),
`verification.independent.json` (the tagged verifier and policy, re-run outside CI), `build-environment.json`,
`continuity.json`, `homebrew/dev-platform.rb` (the tap formula).

Reproduce (a release is verified with the verifier and policy of its own source revision):
```
git show 75269bc0f30fb88593c7904e7778fcdda1cb6a6e:trust/policy.json > policy.json
git show 75269bc0f30fb88593c7904e7778fcdda1cb6a6e:tools/verify_release.py > verify_release.py
gh release download v0.12.1 --repo syncom-systems/dev-platform --dir d
python3 -I verify_release.py d/dev-platform-0.12.1.tar.gz --version 0.12.1 \
  --source-revision 75269bc0f30fb88593c7904e7778fcdda1cb6a6e --archive-sha256 9ceecb639aea07e67d8bb92123f1df5d5f3003c09224363ab4286fd18aaeea26 \
  --tree-digest ab18610679fb84429b922d29c48b5c2b58551b0239c2fa5e5330e0a593c94b45 --environment d/dev-platform-0.12.1.build-environment.json \
  --continuity d/dev-platform-0.12.1.continuity.json --policy policy.json
```
