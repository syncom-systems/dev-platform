# Owner acceptance packet: dev-platform v0.8.2 (stable candidate)

State: **verified-unaccepted**. No authorization exists; nothing here creates, signs or attributes one. v0.2.1's acceptance does not extend to this
archive.

| | |
|---|---|
| **Archive sha256 (authorization subject)** | `993c03fda1b0958dcc2ebee5484cdf620a7a953cf62df041bcddf7713a84f66f` |
| Tree digest (consumer pin) | see `identity.json` `tree_digest_pin` |
| Tag / revision | `v0.8.2` (annotated, not signature-signed) / `f617b37edde2b5e550c813ea4b47c886a761dc62` |
| Release workflow | run 38315825837; immutable pre-release "dev-platform 0.8.2 (verified, NOT accepted)" |
| Independent verification | 32/32 under operator pins and this revision's policy; `verified-unaccepted`; `confers: []` |
| Qualification | CI run 38315818816; 5 profiles on linux-x86_64 and darwin-arm64 |
| Reusable workflow validation | hosted consumer run 38316395793 (`consumer-workflow-validation/`) |

Anchors: `tools/verify_release.py` `a2d53075…6f2e` (unchanged since 0.7.0), `install_release.py` `473a2c73…bb93`, `verify_app_release.py`
`c53bf135…8172`, `verify_platform_current.py` `55af0f2e…98fe`, `verify_consumer_evidence.py` `2c5ee289…bbe7` (all unchanged from 0.8.1);
changed: `consumer_run.py` `bc502b37…9a36`. Policy at the revision: file `577bcf92…98cb`.

Proposed scope if accepted: `platform-baseline` only, by a separate owner approval of this archive digest. Limits as in earlier packets and
`docs/consumer-integration.md` (consumer evidence is consistency with pins, not trustworthy execution).
