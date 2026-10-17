# Owner acceptance packet: dev-platform v0.10.0 (stable candidate)

State: **verified-unaccepted**. No authorization exists; nothing here creates, signs or attributes one. v0.2.1's acceptance does not
extend to this archive. Publishing the Homebrew formula of this release is distribution, not acceptance.

| | |
|---|---|
| **Archive sha256 (authorization subject)** | `a3473a0260b16d571c2832228e2e02e9d07c8b535da2439cc4f2f69ccd74099b` |
| Tree digest (consumer pin) | `a8d7a5004a2f56109d1c3b6c1cb2623ab6d8eb185bd445dc345834250af894aa` |
| Tag / revision | `v0.10.0` (annotated, not signature-signed) / `59ac8a3c752de106a8f1d3df1c31a559fe0fd824` |
| Release workflow | run 39074397641; immutable pre-release "dev-platform 0.10.0 (verified, NOT accepted)" |
| Independent verification | 33/33 under operator pins and this revision's policy; `verified-unaccepted`; `confers: []` |
| Qualification | post-merge run 39074378980; 5 profiles on linux-x86_64 and darwin-arm64 |
| Continuity | predecessor 0.9.0 re-ran the full stage over this source (admitted) |

Anchors: `tools/verify_release.py` `a2d53075…6f2e` (unchanged since 0.7.0), `install_release.py` `473a2c73…bb93`, `verify_app_release.py`
`c53bf135…8172`, `verify_platform_current.py` `55af0f2e…98fe`, `verify_consumer_evidence.py` `2c5ee289…bbe7`, `consumer_run.py`
`bc502b37…9a36`, `homebrew_formula.py` `362c4c6b…aefb` (all unchanged from 0.9.0). Policy at the revision: file `355aa4d2…07a3`
(predecessor 0.9.0; routine continuity pin update).

Proposed scope if accepted: `platform-baseline` only, by a separate owner approval of this archive digest. Limits: `docs/homebrew.md`
(a Homebrew checksum is not provenance; the CLI is a launcher and never certifies itself), `docs/infrastructure.md` (a declared
runner is not thereby registered or secure) and `docs/consumer-integration.md`.
