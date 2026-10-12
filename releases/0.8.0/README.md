# 0.8.0 (stable candidate; verified-unaccepted)

Consumer integration (ADR 0021): consumer-owned exact pins for the platform release and the infrastructure configuration
(`[infra]`), a provider resolver contract with a fail-closed comparison to the pin, `toolchain provision --pinned --verify`,
`toolchain prove-bazel-rust`, `tools/consumer_run.py` + the reusable workflow `consumer-pilot.yml`, the independent
`tools/verify_consumer_evidence.py`, `pr-check --facts`. Runbook: `docs/consumer-integration.md`. Identities and pins:
`identity.json`; owner packet: `ACCEPTANCE-PACKET.md`. `tools/verify_release.py` is unchanged from 0.7.0.

Reproduce (a release is verified with the policy of its own source revision):
```
git show 2ccfe9c11eb83eae2e111ce6188f8b13faf7a4fc:trust/policy.json > policy-0.8.0.json   # sha256 3fc17cd0…43a1
gh release download v0.8.0 --repo syncom-systems/dev-platform --dir d
python3 -I tools/verify_release.py d/dev-platform-0.8.0.tar.gz --version 0.8.0 \
  --source-revision 2ccfe9c11eb83eae2e111ce6188f8b13faf7a4fc \
  --archive-sha256 282b6af495b78fad5295c00ac6d92bee5ecb40d6689ee934c96e1a21684cf374 \
  --environment d/dev-platform-0.8.0.build-environment.json --continuity d/dev-platform-0.8.0.continuity.json \
  --policy policy-0.8.0.json
```
after checking the anchors with `shasum -a 256`. Records: `verification.independent.json` (32/32, `verified-unaccepted`),
`verification.ci.json`, `continuity.json`, `build-environment.json`, `qualification/` (CI run, sha256 index; the `rust-bazel*`
files carry `bazel_rust_toolchain`, the Rust proof, on linux and darwin), `rejections.txt` (tampered archive, wrong revision,
wrong digest, altered consumer pins). No authorization exists for this release. Acceptance is per archive digest: v0.2.1's
acceptance (`releases/0.2.1-acceptance/`) implies nothing about 0.3.0-0.8.0.
