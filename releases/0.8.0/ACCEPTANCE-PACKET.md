# Owner acceptance packet: dev-platform v0.8.0 (stable candidate)

State: **verified-unaccepted**. No authorization exists; nothing here creates, signs or attributes one. v0.2.1's acceptance does
not extend to this archive.

| | |
|---|---|
| **Archive sha256 (authorization subject)** | `282b6af495b78fad5295c00ac6d92bee5ecb40d6689ee934c96e1a21684cf374` |
| Tree digest (consumer pin) | see `identity.json` `tree_digest_pin` |
| Tag / revision | `v0.8.0` (annotated, not signature-signed) / `2ccfe9c11eb83eae2e111ce6188f8b13faf7a4fc` |
| Release workflow | run 38281840850; immutable pre-release "dev-platform 0.8.0 (verified, NOT accepted)" |
| Independent verification | 32/32 under operator pins and this revision's policy; `verified-unaccepted`; `confers: []` |
| Qualification | CI run 38281833323; 5 profiles on linux-x86_64 and darwin-arm64; Rust proof ok for `rust-bazel` (1.85.0) and `rust-bazel-9` (1.97.1) on both |

Anchors: `tools/verify_release.py` `a2d53075…6f2e` (unchanged), `install_release.py` `473a2c73…bb93` (unchanged),
`verify_app_release.py` `c53bf135…8172` and `verify_platform_current.py` `55af0f2e…98fe` (unchanged); new:
`verify_consumer_evidence.py` and `consumer_run.py` (digests in `identity.json`). Policy at the revision: `3fc17cd0…43a1`.

What it adds for consumers: the pin set a consumer owns (`docs/consumer-integration.md`), the infra configuration pin and resolver
contract, verified deterministic provisioning, the Bazel Rust toolchain proof (Bazel only, no Cargo), and a consumer entry
point that produces independently verifiable evidence from public data only, safe in untrusted CI.

Trust limits unchanged from earlier packets (current-state semantics, shared-session approval, non-hermetic builds, unsigned tag,
OIDC), plus the consumer-evidence limits in `docs/consumer-integration.md` (consistency with pins, not proof the consumer job was not
subverted). Proposed scope if accepted: `platform-baseline` only, by a separate owner approval of this archive digest.
