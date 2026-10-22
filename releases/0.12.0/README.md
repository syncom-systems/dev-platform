# 0.12.0 (verified)

Published by release.yml (https://github.com/syncom-systems/dev-platform/actions/runs/39789862632) from tag `v0.12.0` on `fd551d173c45e7de5a85147546b9d6765bfbd667`. Generated
by `tools/release.py records`. Identity and pins: `identity.json`. Records: `verification.ci.json` (the workflow's),
`verification.independent.json` (the tagged verifier and policy, re-run outside CI), `build-environment.json`,
`continuity.json`, `homebrew/dev-platform.rb` (the tap formula).

Reproduce (a release is verified with the verifier and policy of its own source revision):
```
git show fd551d173c45e7de5a85147546b9d6765bfbd667:trust/policy.json > policy.json
git show fd551d173c45e7de5a85147546b9d6765bfbd667:tools/verify_release.py > verify_release.py
gh release download v0.12.0 --repo syncom-systems/dev-platform --dir d
python3 -I verify_release.py d/dev-platform-0.12.0.tar.gz --version 0.12.0 \
  --source-revision fd551d173c45e7de5a85147546b9d6765bfbd667 --archive-sha256 437cf69370775d000439f0dba73e8b4cf0005b07135497a61a7e2f3c8e417857 \
  --tree-digest f399e7c942a1d59bca69abebe80992a49d5b7d738bbc44fcbf6a069879762b17 --environment d/dev-platform-0.12.0.build-environment.json \
  --continuity d/dev-platform-0.12.0.continuity.json --policy policy.json
```
