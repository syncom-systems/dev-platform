# Owner acceptance packet: dev-platform v0.9.0 (stable candidate)

State: **verified-unaccepted**. No authorization exists; nothing here creates, signs or attributes one. v0.2.1's acceptance does not
extend to this archive. Publishing the Homebrew formula of this release is distribution, not acceptance.

| | |
|---|---|
| **Archive sha256 (authorization subject)** | `770742bd162bb58a6103654f6e1d37d6a9ab3cbc31e86a1bb577d4391194d9c2` |
| Tree digest (consumer pin) | `1166f052261f1069028330ce69072a6548ea3a4dee639240f4970711ea0354d9` |
| Tag / revision | `v0.9.0` (annotated, not signature-signed) / `222a106614af317e742bbf6fd4717f7f9056b8c8` |
| Release workflow | run 39024768777; immutable pre-release "dev-platform 0.9.0 (verified, NOT accepted)" |
| Independent verification | 32/32 under operator pins and this revision's policy; `verified-unaccepted`; `confers: []` |
| Qualification | post-merge run 39024759988; 5 profiles on linux-x86_64 and darwin-arm64 |
| Continuity | predecessor 0.8.2 re-ran the full stage over this source (admitted) |

Anchors: `tools/verify_release.py` `a2d53075…6f2e` (unchanged since 0.7.0), `install_release.py` `473a2c73…bb93`, `verify_app_release.py`
`c53bf135…8172`, `verify_platform_current.py` `55af0f2e…98fe`, `verify_consumer_evidence.py` `2c5ee289…bbe7`, `consumer_run.py`
`bc502b37…9a36` (all unchanged from 0.8.2); new: `homebrew_formula.py` `362c4c6b…aefb`. Policy at the revision: file `204e0eca…6d29`.

Proposed scope if accepted: `platform-baseline` only, by a separate owner approval of this archive digest. Limits: `docs/homebrew.md`
(a Homebrew checksum is not provenance; the CLI is a launcher and never certifies itself) and `docs/consumer-integration.md`.
