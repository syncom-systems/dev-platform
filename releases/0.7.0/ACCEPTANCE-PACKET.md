# Owner acceptance packet: dev-platform v0.7.0 (stable candidate)

State: **verified-unaccepted**. No authorization exists; nothing here creates, signs or attributes one.

| | |
|---|---|
| **Archive sha256 (authorization subject)** | `eddf140a7cf4a57d97b9380afbe921b220a28ae257d9eb27b7dbd2c8f4c50931` |
| Tree digest (consumer pin) | `911dd9b06d7f6107c55778eb4482d6785b9cef1f919cabd0a846c7bd734a17b1` |
| Tag / revision | `v0.7.0` (annotated, not signature-signed) / `583413c49dc3bdbe84ff08f0d17092ac8db7f81f` |
| Release workflow | run 38241606888; immutable pre-release "dev-platform 0.7.0 (verified, NOT accepted)" |
| Independent verification | 32/32 under operator pins and this revision's policy; `verified-unaccepted`; `confers: []` |
| Qualification | CI run 38241598482; 5 profiles on linux-x86_64 and darwin-arm64 (`qualification/INDEX.json`) |

Anchors: `tools/verify_release.py` `a2d53075b8bf11bb14f4a2dffb0b40fc6e66b04af73801951fcd768ba29f6f2e` (changed: new provider),
`tools/install_release.py` `473a2c73…bb93` (unchanged), `verify_app_release.py` `c53bf135…8172` and
`verify_platform_current.py` `55af0f2e…98fe` (unchanged from 0.6.0). Policy at the revision: `c371ab9f…e1ad`.

What changed: provider `github-environment-approval` (ADR 0020). Trusts the owner's GitHub login at the click, GitHub's
approval record, the pinned `accept.yml` on `main`, and Sigstore; it cannot tell the owner from anything holding the same
logged-in session or token. Self-review is allowed on the `owner-approval` environment (single-owner repository).

Acceptance of this release is a separate decision from v0.2.1's and from every other candidate's. Procedure:
`docs/owner-acceptance-0.2.1.md` with this release's identities. Proposed scope: `platform-baseline` only. Limitations of
earlier packets (current-state semantics, live path, non-hermetic builds, unsigned tag, OIDC) are unchanged.
