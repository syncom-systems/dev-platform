# 0.10.0 (stable candidate; verified-unaccepted)

Minor release (see `CHANGELOG.md`): optional, explicitly configured infrastructure capabilities in the one public CLI
(ADR 0023): configuration releases, the narrowing authorization policy and the generic provider (`dev-platform infra
resolve`), `dev-platform.infra-config/v1` with `infra init/validate/profile/release`, the local store, `infra doctor`,
read-only `infra discover/audit/drift`, `dev-platform workflow` (GitHub-hosted proposal), `[infra] config_digest_kind`,
mandatory authorization facts on resolved results, and non-activation and public-boundary regressions. Declared 0.x
incompatibilities are listed in the CHANGELOG. `tools/verify_release.py` and `install_release.py` are unchanged from
0.7.0-0.9.0. Identities and pins: `identity.json`; packet: `ACCEPTANCE-PACKET.md`.

Reproduce (a release is verified with the policy of its own source revision):
```
git show 59ac8a3c752de106a8f1d3df1c31a559fe0fd824:trust/policy.json > policy-0.10.0.json   # file sha256 355aa4d2…07a3
gh release download v0.10.0 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.10.0.tar.gz --version 0.10.0 \
  --source-revision 59ac8a3c752de106a8f1d3df1c31a559fe0fd824 \
  --archive-sha256 a3473a0260b16d571c2832228e2e02e9d07c8b535da2439cc4f2f69ccd74099b \
  --tree-digest a8d7a5004a2f56109d1c3b6c1cb2623ab6d8eb185bd445dc345834250af894aa \
  --environment d/dev-platform-0.10.0.build-environment.json --continuity d/dev-platform-0.10.0.continuity.json \
  --policy policy-0.10.0.json
```
Records: `verification.independent.json` (33/33, `verified-unaccepted`, outside CI), `verification.ci.json` (33/33),
`continuity.json` (predecessor 0.9.0, full stage admitted), `build-environment.json`, `qualification/` (post-merge run
39074378980 on the tagged commit, sha256 index), `rejections.txt` (appended byte, wrong source revision, wrong archive
digest, wrong tree digest: all refused), `homebrew/dev-platform.rb` (the tap formula, equal to
`tools/homebrew_formula.py --identity identity.json`; tested in `tests/test_homebrew_formula.py`). The release source
(`src/`) equals the tagged revision's `src/` (tree digest `610ec615…1a4a`). No authorization exists for this release;
acceptance is per archive digest.
