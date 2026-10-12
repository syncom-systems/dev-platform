# Owner acceptance packet: dev-platform v0.8.1 (stable candidate)

State: **verified-unaccepted**. No authorization exists; nothing here creates, signs or attributes one. v0.2.1's acceptance does not extend to this
archive.

| | |
|---|---|
| **Archive sha256 (authorization subject)** | `5671100327d3b8bdfbf74277ae0b21bde39ec2f1f85d4abde12799647740a898` |
| Tree digest (consumer pin) | see `identity.json` `tree_digest_pin` |
| Tag / revision | `v0.8.1` (annotated, not signature-signed) / `5fa25c68814ee9f4d284682215fa4c98198103ff` |
| Release workflow | run 38297833603; immutable pre-release "dev-platform 0.8.1 (verified, NOT accepted)" |
| Independent verification | 32/32 under operator pins and this revision's policy; `verified-unaccepted`; `confers: []` |
| Qualification | CI run 38297824758; 5 profiles on linux-x86_64 and darwin-arm64; Rust proof ok for both Bazel profiles on both platforms |

Anchors: `tools/verify_release.py` `a2d53075…6f2e` (unchanged since 0.7.0; reconciled in `docs/verifier-anchor-lineage.md`),
`install_release.py` `473a2c73…bb93`, `verify_app_release.py` `c53bf135…8172`, `verify_platform_current.py` `55af0f2e…98fe` (all unchanged);
changed: `verify_consumer_evidence.py`, `consumer_run.py` (digests in `identity.json`). Policy at the revision: `90748710…1120`.

Proposed scope if accepted: `platform-baseline` only, by a separate owner approval of this archive digest. Limits as in earlier packets and
`docs/consumer-integration.md` (consumer evidence is consistency with pins, not trustworthy execution).
