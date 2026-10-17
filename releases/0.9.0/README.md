# 0.9.0 (stable candidate; verified-unaccepted)

Minor release (see `CHANGELOG.md`): Homebrew packaging of the public CLI (`tools/homebrew_formula.py`, tap
`syncom-systems/homebrew-dev-platform`), `dev-platform setup` (project-aware install of exactly the pinned release with that
release's trusted installer, toolchain verification or provisioning by the pinned release, its `doctor`), user-scoped and
job-local locations, `DEV_PLATFORM_PYTHON`, `doctor` delegation, and #128's `pr-check --facts` fields (ADR 0022).
`tools/verify_release.py` and `install_release.py` are unchanged from 0.7.0/0.8.x. Identities and pins: `identity.json`; packet:
`ACCEPTANCE-PACKET.md`.

Reproduce (a release is verified with the policy of its own source revision):
```
git show 222a106614af317e742bbf6fd4717f7f9056b8c8:trust/policy.json > policy-0.9.0.json   # file sha256 204e0eca…6d29
gh release download v0.9.0 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.9.0.tar.gz --version 0.9.0 \
  --source-revision 222a106614af317e742bbf6fd4717f7f9056b8c8 \
  --archive-sha256 770742bd162bb58a6103654f6e1d37d6a9ab3cbc31e86a1bb577d4391194d9c2 \
  --environment d/dev-platform-0.9.0.build-environment.json --continuity d/dev-platform-0.9.0.continuity.json \
  --policy policy-0.9.0.json
```
Records: `verification.independent.json` (32/32, `verified-unaccepted`), `verification.ci.json`, `continuity.json` (predecessor
0.8.2, full stage admitted), `build-environment.json`, `qualification/` (post-merge run 39024759988 on the tagged commit, sha256
index), `rejections.txt`, `homebrew/dev-platform.rb` (the tap formula, equal to `tools/homebrew_formula.py --identity identity.json`;
tested in `tests/test_homebrew_formula.py`). No authorization exists for this release; acceptance is per archive digest.
